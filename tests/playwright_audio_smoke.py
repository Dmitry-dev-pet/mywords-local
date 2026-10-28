"""Manual Chromium/Playwright smoke test with deterministic Web Speech mocks.

Run on a workstation with installed Playwright and Chromium:
    python -m pip install playwright
    python -m playwright install chromium
    python tests/playwright_audio_smoke.py
This is deliberately not part of Termux's default unittest suite.
It tests browser event/timer behavior, not Android's actual speaker/voices.
"""
from pathlib import Path
import base64
import os
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'data:text/javascript;base64,' + base64.b64encode(
    (ROOT / 'web/audio-sequence.mjs').read_bytes()).decode()
INIT = r"""(() => {
 const fake = {
   speaking:false, pending:false, calls:[], cancelCount:0, mode:'normal',
   cancel(){this.speaking=false;this.cancelCount++},
   speak(u){
     this.speaking=true;this.calls.push({text:u.text,lang:u.lang});
     u.onstart?.();
     if(this.mode==='normal')setTimeout(()=>{this.speaking=false;u.onend?.()},60);
     if(this.mode==='lost-end')setTimeout(()=>{this.speaking=false},60);
   }
 };
 Object.defineProperty(window,'speechSynthesis',{configurable:true,value:fake});
 Object.defineProperty(window,'SpeechSynthesisUtterance',{
   configurable:true,value:class{constructor(text){this.text=text}}
 });
 window.__fake=fake;
})()"""
START = """async (url) => {
 const {SpeechSequence,buildPlaybackSteps}=await import(url);
 const player=new SpeechSequence({
   synthesis:window.speechSynthesis,Utterance:window.SpeechSynthesisUtterance,
   onState:b=>{document.getElementById('status').textContent=b?'playing':'idle'},
   onProgress:s=>window.__progress.push(s.repetition),
   onFinish:()=>window.__finished++,
   onError:e=>window.__errors.push(e),
   onRecovery:()=>window.__recovered++
 });
 window.__player=player;window.__progress=[];window.__finished=0;
 window.__errors=[];window.__recovered=0;
 const phrases=[{id:'x',ru:'Привет',en:'Hello'}];
 document.getElementById('start').onclick=()=>player.start(
   buildPlaybackSteps(phrases,{repeats:3,pauseMs:80}),1);
 document.getElementById('stop').onclick=()=>player.stop();
}"""


def state(page):
    return page.evaluate("""() => ({
      calls:window.__fake.calls.map(x=>x.text),
      progress:window.__progress,active:window.__player.active,
      finished:window.__finished,recovered:window.__recovered,
      errors:window.__errors
    })""")


def new_page(browser):
    page = browser.new_page(viewport={'width': 960, 'height': 720})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script(INIT)
    page.goto('about:blank')
    page.set_content('<button id="start">Play</button><button id="stop">Stop</button><span id="status">ready</span>')
    page.evaluate(START, MODULE)
    return page, errors


with sync_playwright() as playwright:
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    browser = playwright.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
    for mode in ('normal', 'lost-end'):
        page, errors = new_page(browser)
        page.evaluate('(mode) => { window.__fake.mode = mode }', mode)
        page.locator('#start').click()
        page.wait_for_function('window.__finished === 1', timeout=10000)
        result = state(page)
        assert result['calls'] == ['Hello'] * 3, result
        assert result['progress'] == [1, 2, 3], result
        assert not result['active'] and result['finished'] == 1, result
        assert result['errors'] == [] and not errors, (result, errors)
        assert result['recovered'] == (0 if mode == 'normal' else 3), result
        print('PASS', mode, result)
        page.close()
    page, errors = new_page(browser)
    page.locator('#start').click()
    page.wait_for_timeout(90)
    page.locator('#stop').click()
    page.wait_for_timeout(500)
    result = state(page)
    assert result['calls'] == ['Hello'] and not result['active'] and result['finished'] == 0, result
    assert not errors, errors
    print('PASS stop', result)
    page.close()
    browser.close()
