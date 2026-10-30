"""Chromium checks ZIP preview/install and voice selection against real Flask.

Synthetic ID3 fixtures are NOT playable speech; actual MP3 decoding is covered
by tests/playwright_multilingual_smoke.py for the existing pt-PT pack.
No personal database or installed voicepack directory is accessed.
"""
from pathlib import Path
from subprocess import DEVNULL, Popen
from urllib.request import urlopen, Request
from urllib.parse import urlparse
import json
import os
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_voice_library import synthetic_zip

PORT = int(os.environ.get("MYWORDS_VOICE_SMOKE_PORT", "18880"))
URL = f"http://127.0.0.1:{PORT}"

with tempfile.TemporaryDirectory(prefix="mywords-voice-browser-") as temp:
    env = dict(os.environ)
    env.update(PORT=str(PORT),
               MYWORDS_TEST_DB=str(Path(temp) / "study.sqlite3"),
               MYWORDS_TEST_VOICE_ROOT=str(Path(temp) / "voicepacks"))
    server = Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                   stdout=DEVNULL, stderr=DEVNULL)
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Flask terminated during browser setup")
            try:
                with urlopen(URL + "/api/health", timeout=1) as resp:
                    if json.load(resp)["vue_ready"]:
                        break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Flask test server did not become ready")

        request = Request(URL + "/api/starter-islands/surfing/import",
                          data=b"", method="POST")
        with urlopen(request) as response:
            assert response.status in (200, 201)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1000, "height": 780})
            blocked = []
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))

            def local_only(route):
                parsed = urlparse(route.request.url)
                if parsed.scheme in ("http", "https") and parsed.netloc != f"127.0.0.1:{PORT}":
                    blocked.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", local_only)
            page.goto(URL)
            page.locator(".focus-phrase").wait_for()
            page.locator(".toolbar-settings").click()
            page.get_by_text("Дополнительно: ручной импорт других проверенных ZIP").click()

            file_input = page.get_by_label("Выбрать ZIP с голосом")
            file_input.set_input_files({
                "name": "bad-voice.zip", "mimeType": "application/zip",
                "buffer": synthetic_zip(corrupt=True),
            })
            page.get_by_role("button", name="Проверить ZIP", exact=True).click()
            page.locator(".error-banner").wait_for()
            assert not (Path(temp) / "voicepacks").exists()
            print("PASS browser ZIP corruption rejected before installing", flush=True)

            file_input.set_input_files({
                "name": "kokoro-af_heart.zip", "mimeType": "application/zip",
                "buffer": synthetic_zip(),
            })
            page.get_by_role("button", name="Проверить ZIP", exact=True).click()
            page.get_by_text("Проверен полный пакет af_heart: 144 записей.").wait_for()
            page.get_by_role("button", name="Установить проверенный пакет").click()
            page.get_by_text("Голос установлен: af_heart").wait_for()
            page.get_by_label("Голос Kokoro для английского").select_option("af_heart")

            recorded = page.evaluate("""async () => {
              const pref = JSON.parse(localStorage.getItem('mywords.local.kokoro.v1') || '{}');
              const list = await (await fetch('/api/voice-packs')).json();
              const islands = await (await fetch('/api/starter-islands')).json();
              const surf = islands.find(x => x.id === 'surfing');
              const url = '/api/islands/' + surf.island_id +
                '/phrases?language=en-US&voice=af_heart';
              const phrases = await (await fetch(url)).json();
              return {
                pref, installed: list.voices.find(v => v.id === 'af_heart').installed,
                url: phrases[0].audio?.url,
                reviews: phrases[0].review_count
              };
            }""")
            assert recorded["pref"]["en"] == "af_heart", recorded
            assert recorded["installed"] is True, recorded
            assert recorded["url"].startswith("/api/voice-media/af_heart/"), recorded
            assert recorded["reviews"] == 0, recorded
            assert not errors, errors
            assert not blocked, blocked
            page.reload()
            page.locator(".focus-phrase").wait_for()
            assert json.loads(page.evaluate(
                "localStorage.getItem('mywords.local.kokoro.v1')"))["en"] == "af_heart"
            print("PASS browser ZIP preview, install, voice selection and persistence", flush=True)
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()
            server.wait()
