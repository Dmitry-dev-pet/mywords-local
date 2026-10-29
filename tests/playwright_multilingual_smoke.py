"""Real Flask/Vue/Chromium smoke: shared island, language switch, review isolation.

The browser voices are mocked; this cannot certify physical Android TTS.
Each run creates a disposable SQLite database in a temporary directory.
"""
from pathlib import Path
from subprocess import DEVNULL, Popen
import json
import os
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 18879
URL = f"http://127.0.0.1:{PORT}"
MOCK_SPEECH = r"""(() => {
  const calls = [];
  const voices = [
    {name:'English test voice',lang:'en-US',voiceURI:'voice-en'},
    {name:'Português Portugal test voice',lang:'pt-PT',voiceURI:'voice-pt'}
  ];
  Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{
    getVoices(){return voices;}, cancel(){}, pending:false, speaking:false,
    speak(u){calls.push({text:u.text,lang:u.lang,voice:u.voice?.voiceURI});
      setTimeout(()=>{u.onstart?.();setTimeout(()=>u.onend?.(),20)},1)}
  }});
  Object.defineProperty(window,'SpeechSynthesisUtterance',{configurable:true,value:
    class {constructor(text){this.text=text;}}});
  window.__mockSpeechCalls=calls;
})();"""


def serve(database):
    env = os.environ.copy()
    env['MYWORDS_TEST_DB'] = str(database)
    env['PORT'] = str(PORT)
    process = Popen([sys.executable, 'server.py'], cwd=ROOT, env=env,
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
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError('Flask/Vue runtime did not start')


with tempfile.TemporaryDirectory() as temp:
    process = serve(Path(temp) / 'private-test.sqlite3')
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1150, 'height': 780})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.add_init_script(MOCK_SPEECH)
            page.goto(URL)
            page.get_by_role('heading', name='Языковые острова').wait_for()
            page.locator('.target-language-select').select_option('pt-PT')
            pack = page.locator('.starter-card').filter(has=page.get_by_role(
                'heading', name='Сёрфинг и океан'))
            pack.get_by_role('button', name='+ Добавить в мои острова').click()
            pack.get_by_role('button', name='▶ Открыть остров').wait_for()
            pack.get_by_role('button', name='▶ Открыть остров').click()
            page.locator('.focus-phrase').wait_for()
            assert page.locator('.focus-phrase').inner_text() == 'Estou a aprender a fazer surf.'
            page.locator('.speaker-circle').click()
            page.wait_for_function('window.__mockSpeechCalls.length >= 1')
            actual = page.evaluate('window.__mockSpeechCalls[0]')
            assert actual['lang'] == 'pt-PT' and actual['voice'] == 'voice-pt', actual
            page.locator('.rating-medium').click()
            page.wait_for_function("document.querySelector('.evaluation-heading').textContent.includes('проверок: 1')")
            page.locator('.target-language-select').select_option('en-US')
            page.wait_for_function("document.querySelector('.focus-phrase')?.textContent.includes('just learning to surf')")
            assert 'Ещё не оценено' in page.locator('.evaluation-heading').inner_text()
            page.locator('.rating-good').click()
            page.wait_for_function("document.querySelector('.evaluation-heading').textContent.includes('проверок: 1')")
            page.locator('.target-language-select').select_option('pt-PT')
            page.locator('.focus-phrase').get_attribute('class')  # render completed
            page.wait_for_function("document.querySelector('.focus-phrase')?.textContent.includes('Estou a aprender')")
            assert 'Нужно повторить' in page.locator('.evaluation-heading').inner_text()
            page.reload()
            page.wait_for_function("document.querySelector('.focus-phrase')?.textContent.includes('Estou a aprender')")
            assert 'проверок: 1' in page.locator('.evaluation-heading').inner_text()
            assert not errors, errors

            # A pt-BR voice must NOT silently be used for Portuguese of Portugal.
            missing = browser.new_page(viewport={'width': 1150, 'height': 780})
            missing.add_init_script(r"""(() => {
              const calls = [];
              Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{
                getVoices:()=>[{name:'Brazilian voice',lang:'pt-BR',voiceURI:'br'}],
                cancel(){},speak(u){calls.push(u.text)}
              }});
              Object.defineProperty(window,'SpeechSynthesisUtterance',{configurable:true,value:
                class {constructor(text){this.text=text}}});
              window.__unexpectedSpeech=calls;
            })()""")
            missing.goto(URL)
            missing.locator('.target-language-select').select_option('pt-PT')
            missing.locator('.focus-phrase').wait_for()
            missing.locator('.speaker-circle').click()
            missing.locator('.error-banner').wait_for()
            assert 'pt-PT' in missing.locator('.error-banner').inner_text()
            assert missing.evaluate('window.__unexpectedSpeech.length') == 0
            missing.close()
            browser.close()
            print('PASS multilingual UI: same island, pt-PT speech, independent scores, and pt-BR refusal')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()
