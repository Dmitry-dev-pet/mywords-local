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
