"""Real Chromium/HTTP smoke: all Kokoro voices arrive with the app checkout.

No ZIP upload, no system TTS, no LLM, no personal SQLite and no outbound network.
Uses actual committed 144-phrase MP3s rather than synthetic audio headers.
"""
from pathlib import Path
from subprocess import DEVNULL, Popen
import json
import os
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("MYWORDS_BUNDLED_SMOKE_PORT", "18882"))
URL = f"http://127.0.0.1:{PORT}"
BUNDLES = ROOT / "data" / "kokoro-voicepacks-v1"

INIT = """(() => {
  Object.defineProperty(window, 'speechSynthesis', {configurable: true, value: undefined});
  Object.defineProperty(window, 'SpeechSynthesisUtterance', {configurable: true, value: undefined});
  localStorage.setItem('mywords.local.practice.v1', JSON.stringify({
    rate: 1, repeats: 1, pauseMs: 0, order: 'en', languagePauseMs: 0
  }));
  window.__mediaEvents = [];
  const originalPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function(...args) {
    this.addEventListener('ended', () => window.__mediaEvents.push({
      kind: 'ended', src: this.currentSrc
    }), {once: true});
    return originalPlay.apply(this, args);
  };
})();"""


def start_server(db, voice_root):
    env = os.environ.copy()
    env.update(PORT=str(PORT), MYWORDS_TEST_DB=str(db),
               MYWORDS_TEST_VOICE_ROOT=str(voice_root),
               MYWORDS_TEST_BUNDLE_ROOT=str(BUNDLES))
    p = Popen([sys.executable, "server.py"], env=env, cwd=ROOT,
              stdout=DEVNULL, stderr=DEVNULL)
    for _ in range(150):
        if p.poll() is not None:
            raise RuntimeError("Flask exited")
        try:
            with urlopen(URL + "/api/health", timeout=1) as r:
                if json.load(r)["vue_ready"]:
                    return p
        except OSError:
            pass
        time.sleep(.1)
    p.terminate()
    raise RuntimeError("Bundled Flask did not start")


with tempfile.TemporaryDirectory(prefix="mywords-bundled-browser-") as tmp:
    private = Path(tmp)
    voice_root = private / "manual-voices"
    server = start_server(private / "study.sqlite3", voice_root)
    try:
        req = Request(URL + "/api/starter-islands/surfing/import",
                      data=b"", method="POST")
        with urlopen(req) as r:
            assert r.status in (200, 201)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            page.add_init_script(INIT)
            errors, external = [], []
            page.on("pageerror", lambda err: errors.append(str(err)))

            def local_only(route):
                url = urlparse(route.request.url)
                if url.scheme in ("http", "https") and url.netloc != f"127.0.0.1:{PORT}":
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", local_only)
            page.goto(URL)
            page.locator(".focus-phrase").wait_for()
            response = page.evaluate("""async () =>
              (await (await fetch('/api/voice-packs')).json()).voices""")
            assert len(response) == 7 and all(v["installed"] for v in response), response
            page.wait_for_function("""() => {
              const pref = JSON.parse(localStorage.getItem('mywords.local.kokoro.v1') || '{}');
              return pref.en === 'af_heart';
            }""")
            page.locator(".speaker-circle").click()
            page.wait_for_function("window.__mediaEvents.some(e => e.kind === 'ended')", timeout=25000)
            assert "/api/voice-media/af_heart/" in page.evaluate("window.__mediaEvents[0].src")
            print("PASS automatic bundled US voice, real HTTP playback, zero ZIP uploads", flush=True)

            page.locator(".toolbar-settings").click()
            page.get_by_label("Голос Kokoro для английского").select_option("bf_emma")
            page.get_by_role("button", name="Закрыть настройки").click()
            page.wait_for_function("""() => {
              const pref = JSON.parse(localStorage.getItem('mywords.local.kokoro.v1') || '{}');
              return pref.en === 'bf_emma';
            }""")
            page.evaluate("window.__mediaEvents.length=0")
            page.locator(".speaker-circle").click()
            page.wait_for_function("window.__mediaEvents.length>=1", timeout=25000)
            assert "/api/voice-media/bf_emma/" in page.evaluate("window.__mediaEvents[0].src")
            print("PASS British voice switch with the same English island", flush=True)

            page.locator(".toolbar-settings").click()
            page.get_by_role("button", name="Показать условия OpenRAIL").click()
            page.get_by_text("Полный текст лицензии").wait_for()
            page.get_by_label("Я прочитал условия OpenRAIL и принимаю ограничения использования").check()
            page.get_by_label("Голос Kokoro для русского").select_option("masha")
            page.get_by_role("button", name="Закрыть настройки").click()
            page.get_by_role("button", name="Двойное аудио").click()
            page.evaluate("window.__mediaEvents.length=0")
            page.locator(".speaker-circle").click()
            page.wait_for_function("window.__mediaEvents.length>=2", timeout=30000)
            sources = page.evaluate("window.__mediaEvents.map(e => e.src)")
            assert any("/api/voice-media/masha/" in x for x in sources), sources
            assert any("/api/voice-media/bf_emma/" in x for x in sources), sources
            print("PASS Russian license acceptance, RU-GB double-audio with real offline MP3s", flush=True)


            # Mobile UX: keep one-phrase study and bottom buttons entirely inside
            # the visual viewport, including a short landscape phone.
            phone = browser.new_page(viewport={"width": 360, "height": 640})
            phone.add_init_script(INIT)
            phone.on("pageerror", lambda err: errors.append(str(err)))
            phone.route("**/*", local_only)
            phone.goto(URL)
            phone.locator(".focus-phrase").wait_for()
            phone.locator(".app-layout.mobile-practice").wait_for()

            def mobile_layout_metrics():
                return phone.evaluate("""() => {
                  const box = css => {
                    const element = document.querySelector(css);
                    const r = element?.getBoundingClientRect();
                    return r && {top:r.top,bottom:r.bottom,height:r.height};
                  };
                  return {
                    viewport: window.innerHeight,
                    documentHeight: document.documentElement.scrollHeight,
                    phrase: box('.focus-stage'),
                    dock: box('.mobile-study-dock'),
                    ratings: box('.evaluation'),
                    answer: box('.mobile-recall-action'),
                    transport: box('.transport'),
                    root: box('.app-layout.mobile-practice')
                  };
                }""")

            for width, height in ((390, 844), (360, 640), (320, 568), (667, 375)):
                phone.set_viewport_size({"width": width, "height": height})
                geometry = mobile_layout_metrics()
                assert geometry["documentHeight"] <= height + 1, (width, height, geometry)
                assert geometry["root"]["bottom"] <= height + 1, geometry
                assert geometry["dock"]["bottom"] <= height + 1, geometry
                assert geometry["ratings"]["bottom"] <= height + 1, geometry
                assert geometry["ratings"]["top"] >= geometry["phrase"]["bottom"] - 1, geometry
            print("PASS no-page-scroll mobile portrait, 320x568 and short landscape; ratings docked", flush=True)

            phone.set_viewport_size({"width": 360, "height": 640})
            phone.get_by_role("button", name="Вспомнить", exact=True).click()
            phone.get_by_role("button", name="Показать ответ", exact=True).wait_for()
            assert not phone.locator(".evaluation").is_visible(), "Recall ratings before reveal"
            hidden = mobile_layout_metrics()
            assert hidden["answer"]["bottom"] <= hidden["viewport"] + 1, hidden
            phone.get_by_role("button", name="Показать ответ", exact=True).click()
            assert phone.locator(".evaluation").is_visible()
            revealed_geometry = mobile_layout_metrics()
            assert revealed_geometry["ratings"]["bottom"] <= revealed_geometry["viewport"] + 1

            before_phrase = phone.locator(".focus-phrase").inner_text()
            phone.locator(".rating-hard").click()
            phone.wait_for_function(
                "(old) => document.querySelector('.focus-phrase')?.textContent !== old",
                arg=before_phrase
            )
            assert not phone.get_by_role("button", name="Показать ответ", exact=True).is_hidden()
            assert phone.locator(".session-subhead span:last-child").inner_text() == "2 / 18"
            print("PASS mobile Recall: reveal → save rating → advance, no forced scrolling", flush=True)

            # Long phrases may scroll inside the center card, not the page or dock.
            phone.set_viewport_size({"width": 320, "height": 568})
            phone.locator(".focus-phrase").evaluate(
                "(element) => element.textContent = ('Длинное предложение для проверки. ').repeat(28)"
            )
            geometry = mobile_layout_metrics()
            scroll = phone.locator(".focus-stage").evaluate(
                "(element) => ({client:element.clientHeight,full:element.scrollHeight})"
            )
            assert scroll["full"] > scroll["client"], scroll
            assert geometry["documentHeight"] <= geometry["viewport"] + 1, geometry
            assert geometry["answer"]["bottom"] <= geometry["viewport"] + 1, geometry
            phone.locator(".focus-stage").evaluate("(element) => element.scrollTop = 80")
            assert phone.locator(".focus-stage").evaluate("(element) => element.scrollTop") > 0
            print("PASS long sentence scrolls inside phrase card only", flush=True)

            # Reload returns real text and leaves previously saved reviews intact.
            phone.reload()
            phone.locator(".focus-phrase").wait_for()
            for _ in range(16):
                phone.get_by_role("button", name="Следующее предложение").click()
            assert phone.locator(".session-subhead span:last-child").inner_text() == "18 / 18"
            phone.get_by_role("button", name="Вспомнить", exact=True).click()
            phone.get_by_role("button", name="Показать ответ", exact=True).click()
            phone.locator(".rating-good").click()
            phone.locator(".mobile-session-complete").wait_for()
            assert phone.get_by_text("Остров пройден!").is_visible()
            phone.get_by_role("button", name="Повторить", exact=True).click()
            assert phone.locator(".session-subhead span:last-child").inner_text() == "1 / 18"
            assert not phone.locator(".mobile-session-complete").is_visible()
            print("PASS last phrase shows completion, repeat restarts at first card", flush=True)
            phone.close()

            assert not voice_root.exists(), "Automatic playback must never extract into local voice root"
            assert not external, external
            assert not errors, errors
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()
            server.wait()
