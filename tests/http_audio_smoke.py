"""Real loopback HTTP check of all packaged MP3s; no browser or private DB.

Run explicitly with the app's Python: python tests/http_audio_smoke.py
This supplements, but never replaces, the real Chromium and Android checks.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werkzeug.serving import make_server, WSGIRequestHandler
from audio_pack import PACK_ROOT
from server import create_app


class QuietRequests(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def main():
    with tempfile.TemporaryDirectory(prefix="mywords-public-http-") as directory:
        app = create_app(Path(directory) / "synthetic-test.sqlite3")
        server = make_server("127.0.0.1", 0, app, request_handler=QuietRequests)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/audio-pack", timeout=5) as response:
                status = json.load(response)
            assert status["ready"] and status["available"] == status["expected"] == 144, status
            manifest = json.loads((PACK_ROOT / "manifest.json").read_text(encoding="utf-8"))
            assert len(manifest["entries"]) == 144
            for entry in manifest["entries"]:
                url = base + f"/web/audio/{manifest['pack_id']}/{entry['file']}"
                with urlopen(url, timeout=5) as response:
                    assert response.status == 200
                    assert response.headers.get_content_type() == "audio/mpeg"
                    assert hashlib.sha256(response.read()).hexdigest() == entry["sha256"]
            with urlopen(Request(url, headers={"Range": "bytes=0-31"}), timeout=5) as response:
                assert response.status == 206 and len(response.read()) == 32
            print(json.dumps({"result": "PASS", "real_loopback_http_files": 144,
                              "sha256_verified": 144, "content_type": "audio/mpeg",
                              "range_status": 206, "temporary_db_only": True}))
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    main()
