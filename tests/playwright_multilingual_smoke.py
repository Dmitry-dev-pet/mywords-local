"""Real Flask/Vue/Chromium smoke with actual HTTP-served Kokoro MP3 playback.

Only English/Russian Web Speech is mocked. Native HTMLAudioElement playback,
MP3 decoding, timers, and ended/error events are NOT mocked. External network
requests are blocked: offline here means internet-free localhost/Termux, not an
unavailable local Flask server. This cannot certify a physical Android speaker,
background suspension, or a listener's pronunciation judgment.

Each run creates a disposable SQLite database. No personal database is opened.
Set PLAYWRIGHT_CHROMIUM_EXECUTABLE and MYWORDS_SERVER_PYTHON when needed.
"""
from pathlib import Path
from subprocess import DEVNULL, Popen
import json
import os
import sqlite3
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("MYWORDS_SMOKE_PORT", "18879"))
URL = f"http://127.0.0.1:{PORT}"
INIT = r"""(() => {
  const calls = [];
  const voices = [
    {name:'English test voice',lang:'en-US',voiceURI:'voice-en'},
    {name:'Russian test voice',lang:'ru-RU',voiceURI:'voice-ru'},
    // Deliberately only pt-BR, never a system pt-PT voice.
    {name:'Brazilian test voice',lang:'pt-BR',voiceURI:'voice-br'}
  ];
  const speech = {
    getVoices(){return voices;}, pending:false, speaking:false, token:0,
    cancel(){this.token++;this.speaking=false;}, pause(){}, resume(){},
    speak(u){
      const token = this.token;this.speaking=true;
      calls.push({text:u.text,lang:u.lang,voice:u.voice?.voiceURI,at:performance.now()});
      u.onstart?.();setTimeout(()=>{if(this.token===token){this.speaking=false;u.onend?.()}},30);
    }
  };
  Object.defineProperty(window,'speechSynthesis',{configurable:true,value:speech});
  Object.defineProperty(window,'SpeechSynthesisUtterance',{configurable:true,value:
    class {constructor(text){this.text=text;}}});
  window.__mockSpeechCalls=calls;
  window.__mediaEvents=[];window.__mediaElements=[];
  const originalPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function(...args) {
    if(!window.__mediaElements.includes(this)) {
      window.__mediaElements.push(this);
      for(const event of ['playing','ended','pause','error','loadedmetadata']) {
        this.addEventListener(event,()=>window.__mediaEvents.push({
          event,src:this.currentSrc || this.src,time:this.currentTime,
          duration:this.duration,rate:this.playbackRate,at:performance.now(),
          preservesPitch:this.preservesPitch,error:this.error?.code
        }));
      }
    }
    // Observability only: call the real browser play() and retain its promise.
    return originalPlay.apply(this,args);
  };
  if(!localStorage.getItem('mywords.local.practice.v1')) {
    localStorage.setItem('mywords.local.practice.v1',JSON.stringify({
      rate:1.5,repeats:2,pauseMs:500,order:'en',languagePauseMs:500
    }));
  }
})();"""
NO_SPEECH = r"""Object.defineProperty(window,'speechSynthesis',{configurable:true,value:undefined});
Object.defineProperty(window,'SpeechSynthesisUtterance',{configurable:true,value:undefined});"""


def serve(database):
    env = os.environ.copy()
    env['MYWORDS_TEST_DB'] = str(database)
    env['PORT'] = str(PORT)
    python = os.environ.get('MYWORDS_SERVER_PYTHON', sys.executable)
    process = Popen([python, 'server.py'], cwd=ROOT, env=env,
                    stdout=DEVNULL, stderr=DEVNULL)
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f'Flask exited unexpectedly: {process.returncode}')
        try:
            with urlopen(URL + '/api/health', timeout=1) as response:
                health = json.load(response)
                if health['ok'] and health['vue_ready']:
                    return process
        except OSError:
            pass
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError('Flask/Vue runtime did not start')


def review_rows(database):
    """Only the disposable database created inside this test's temp directory."""
    with sqlite3.connect(database) as connection:
        return connection.execute('SELECT * FROM review_events ORDER BY id').fetchall()


def media_events(page, kind=None):
    return page.evaluate('(kind)=>window.__mediaEvents.filter(e=>!kind||e.event===kind)', kind)


def wait_playing(page, minimum=1):
    page.wait_for_function(
        '(n)=>window.__mediaEvents.filter(e=>e.event==="playing").length>=n',
        arg=minimum, timeout=15000)


def wait_complete(page):
    page.wait_for_function(
        'document.querySelector(".playback-hint")?.textContent.includes("Воспроизведение завершено")',
        timeout=30000)


def clear_events(page):
    page.evaluate('window.__mediaEvents.length=0;window.__mockSpeechCalls.length=0')


def configure(page, *, repeats=None, pause_ms=None, rate=None):
    page.get_by_role('button', name='Открыть настройки', exact=True).click()
    if repeats is not None:
        page.get_by_role('group', name='Количество повторений').get_by_role(
            'button', name=f'{repeats}×', exact=True).click()
    if pause_ms is not None:
        page.get_by_label('Пауза между повторами', exact=True).select_option(str(pause_ms))
    if rate is not None:
        speed = page.get_by_label('Скорость воспроизведения', exact=True)
        speed.focus()
        speed.press('Home')
        for _ in range(round((rate - 0.5) / 0.05)):
            speed.press('ArrowRight')
        assert abs(float(speed.input_value()) - rate) < 1e-9, speed.input_value()
    page.keyboard.press('Escape')


def new_page(browser, blocked, errors, no_speech=False):
    page = browser.new_page(viewport={'width': 1150, 'height': 780})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script(INIT + ('\n' + NO_SPEECH if no_speech else ''))
    def local_only(route):
        parsed = urlparse(route.request.url)
        if parsed.scheme in ('http', 'https') and parsed.netloc != f'127.0.0.1:{PORT}':
            blocked.append(route.request.url)
            route.abort()
        else:
            route.continue_()
    page.route('**/*', local_only)
    return page


with tempfile.TemporaryDirectory(prefix='mywords-browser-') as temp:
    database = Path(temp) / 'synthetic-test.sqlite3'
    process = serve(database)
    try:
        with sync_playwright() as playwright:
            executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
            browser = playwright.chromium.launch(headless=True,
                **({'executable_path': executable} if executable else {}))
            blocked, errors = [], []
            page = new_page(browser, blocked, errors)
            page.goto(URL)
            package = page.evaluate(
                "async () => (await fetch('/api/audio-pack')).json()")
            assert package['ready'] is True and package['status'] == 'ready', package
            assert package['available'] == package['expected'] == 144, package
            assert package['pack_id'] == 'pt-PT-kokoro-v1', package
            page.get_by_role('heading', name='Языковые острова').wait_for()
            page.locator('.target-language-select').select_option('pt-PT')
            pack = page.locator('.starter-card').filter(has=page.get_by_role(
                'heading', name='Сёрфинг и океан'))
            pack.get_by_role('button', name='+ Добавить в мои острова').click()
            pack.get_by_role('button', name='▶ Открыть остров').wait_for()
            pack.get_by_role('button', name='▶ Открыть остров').click()
            page.locator('.focus-phrase').wait_for()
            assert page.locator('.focus-phrase').inner_text() == 'Estou a aprender a fazer surf.'
            assert page.locator('.voice-warning-top').count() == 0, 'Public starter recording missing'
            before_listening = review_rows(database)

            # Real MP3, two completed repetitions, requested speed/pitch and gap.
            page.locator('.speaker-circle').click()
            wait_complete(page)
            playing, ended = media_events(page, 'playing'), media_events(page, 'ended')
            assert len(playing) == len(ended) == 2, media_events(page)
            assert all(e['duration'] > 0.4 and e['rate'] == 1.5 for e in playing), playing
            assert all(e['preservesPitch'] for e in playing), playing
            assert playing[1]['at'] - ended[0]['at'] >= 450, (playing, ended)
            assert '/web/audio/pt-PT-kokoro-v1/' in playing[0]['src'], playing
            assert page.evaluate('window.__mockSpeechCalls') == [], 'pt-PT must not use system TTS'
            assert review_rows(database) == before_listening
            print('PASS real HTTP MP3: two repetitions, speed/pitch, inter-repeat pause, zero review writes')

            # Pause/resume holds native media position rather than restarting it.
            configure(page, repeats=1, pause_ms=0, rate=0.85)
            clear_events(page)
            page.locator('.speaker-circle').click()
            wait_playing(page)
            page.get_by_role('button', name='Ⅱ Пауза', exact=True).click()
            paused_at = page.evaluate('window.__mediaElements.at(-1).currentTime')
            page.wait_for_timeout(350)
            held_at = page.evaluate('window.__mediaElements.at(-1).currentTime')
            assert abs(held_at - paused_at) < 0.1, (paused_at, held_at)
            page.get_by_role('button', name='▶ Продолжить', exact=True).click()
            wait_complete(page)
            assert len(media_events(page, 'ended')) == 1
            assert len(media_events(page, 'playing')) == 2

            # Next cancels the active recording and stale completion cannot move cards.
            configure(page, repeats=3, pause_ms=500, rate=1.5)
            clear_events(page)
            page.locator('.speaker-circle').click()
            wait_playing(page)
            page.get_by_role('button', name='Следующее предложение', exact=True).click()
            next_text = page.locator('.focus-phrase').inner_text()
            assert next_text != 'Estou a aprender a fazer surf.'
            play_count = len(media_events(page, 'playing'))
            page.wait_for_timeout(1200)
            assert page.locator('.focus-phrase').inner_text() == next_text
            assert len(media_events(page, 'playing')) == play_count
            assert page.get_by_role('button', name='Остановить воспроизведение', exact=True).count() == 0
            page.get_by_role('button', name='Предыдущее предложение', exact=True).click()

            # Whole-island mode advances to a different actual recording, then Stop.
            configure(page, repeats=1, pause_ms=0)
            clear_events(page)
            page.get_by_role('button', name='Слушать до конца острова').click()
            wait_playing(page, 2)
            assert page.locator('.focus-phrase').inner_text() != 'Estou a aprender a fazer surf.'
            island_events = media_events(page, 'playing')
            assert island_events[0]['src'] != island_events[1]['src'], island_events
            page.get_by_role('button', name='Остановить воспроизведение', exact=True).click()
            stopped_count = len(media_events(page, 'playing'))
            page.wait_for_timeout(1000)
            assert len(media_events(page, 'playing')) == stopped_count
            page.get_by_role('button', name='Предыдущее предложение', exact=True).click()

            # Recall still hides Portuguese, but plays the same real recording.
            page.get_by_role('button', name='Вспомнить', exact=True).click()
            russian_text = page.locator('.focus-phrase').inner_text()
            assert russian_text != 'Estou a aprender a fazer surf.'
            clear_events(page)
            page.locator('.speaker-circle').click()
            wait_complete(page)
            assert len(media_events(page, 'ended')) == 1
            page.locator('.reveal-link').click()
            assert page.locator('.focus-translation').inner_text() == 'Estou a aprender a fazer surf.'
            page.get_by_role('button', name='Фокус', exact=True).click()

            # Optional Russian pre-reading remains TTS; target stays native audio.
            clear_events(page)
            page.get_by_role('button', name='Двойное аудио').click()
            page.locator('.speaker-circle').click()
            wait_complete(page)
            spoken = page.evaluate('window.__mockSpeechCalls')
            assert len(spoken) == 1 and spoken[0]['lang'] == 'ru-RU', spoken
            assert media_events(page, 'playing')[0]['at'] >= spoken[0]['at'] + 450
            page.get_by_role('button', name='Двойное аудио').click()
            assert review_rows(database) == before_listening
            print('PASS Focus/Recall, native Pause/Resume, Stop/Next, island advance, optional Russian TTS')

            # Ratings stay language-specific; English browser TTS is unchanged.
            page.locator('.rating-medium').click()
            page.wait_for_function("document.querySelector('.evaluation-heading').textContent.includes('проверок: 1')")
            page.locator('.target-language-select').select_option('en-US')
            page.wait_for_function("document.querySelector('.focus-phrase')?.textContent.includes('just learning to surf')")
            assert 'Ещё не оценено' in page.locator('.evaluation-heading').inner_text()
            clear_events(page)
            page.locator('.speaker-circle').click()
            wait_complete(page)
            english = page.evaluate('window.__mockSpeechCalls')
            assert len(english) == 1 and english[0]['lang'] == 'en-US' and english[0]['voice'] == 'voice-en', english
            assert not media_events(page, 'playing')
            page.locator('.rating-good').click()
            page.wait_for_function("document.querySelector('.evaluation-heading').textContent.includes('проверок: 1')")
            page.locator('.target-language-select').select_option('pt-PT')
            page.wait_for_function("document.querySelector('.focus-phrase')?.textContent.includes('Estou a aprender')")
            assert 'Нужно повторить' in page.locator('.evaluation-heading').inner_text()
            page.reload()
            page.wait_for_function("document.querySelector('.focus-phrase')?.textContent.includes('Estou a aprender')")
            assert 'проверок: 1' in page.locator('.evaluation-heading').inner_text()
            assert len(review_rows(database)) == 2

            # A browser with no Web Speech API at all can play the installed pack.
            absent = new_page(browser, blocked, errors, no_speech=True)
            absent.goto(URL)
            # A new browser context has no selected island; explicitly open
            # the already imported lesson rather than relying on page state.
            try:
                absent.get_by_role('heading', name='Языковые острова').wait_for(timeout=8000)
            except Exception:
                print('NO_SPEECH_DEBUG', {
                    'page_url': absent.url,
                    'page_text': absent.locator('body').inner_text(timeout=3000)[:1000],
                    'page_errors': errors[-15:],
                    'network_blocked': blocked[-15:],
                    'ready_state': absent.evaluate('document.readyState'),
                }, flush=True)
                raise
            absent.locator('.target-language-select').select_option('pt-PT')
            absent.get_by_role('navigation', name='Мои острова', exact=True).get_by_role(
                'button', name='Сёрфинг и океан', exact=True).click()
            absent.locator('.focus-phrase').wait_for()
            absent.locator('.speaker-circle').click()
            wait_complete(absent)
            assert len(media_events(absent, 'ended')) == 2
            assert absent.evaluate('typeof window.speechSynthesis') == 'undefined'
            absent.close()

            # A synthetic private phrase is never sent to TTS/network and remains usable as text.
            private = page.evaluate("""async () => {
              const island = await (await fetch('/api/islands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'Synthetic private island'})})).json();
              const phrase = await (await fetch(`/api/islands/${island.id}/phrases`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ru:'Это выдуманная личная фраза.',target:'Esta é uma frase privada fictícia.',language:'pt-PT'})})).json();
              return {island,phrase};
            }""")
            page.reload()
            page.get_by_role('navigation', name='Мои острова', exact=True).get_by_role(
                'button', name='Synthetic private island', exact=True).click()
            page.wait_for_function("document.querySelector('.focus-phrase')?.textContent.includes('privada fictícia')")
            page.locator('.voice-warning-top').wait_for()
            clear_events(page)
            page.locator('.speaker-circle').click()
            page.locator('.error-banner').wait_for()
            assert 'Kokoro' in page.locator('.error-banner').inner_text()
            assert not media_events(page, 'playing')
            assert page.evaluate('window.__mockSpeechCalls') == []
            page.get_by_role('button', name='Вспомнить', exact=True).click()
            page.locator('.reveal-link').click()
            assert page.locator('.focus-translation').inner_text() == private['phrase']['target']
            assert len(review_rows(database)) == 2
            assert not errors, errors
            assert not blocked, f'App attempted external requests: {blocked}'
            browser.close()
            print('PASS independent persisted scores, English TTS, absent Web Speech, explicit private missing audio, internet-free localhost')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()
