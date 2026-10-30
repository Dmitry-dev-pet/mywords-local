"""Real committed Kokoro bundle smoke: zero ZIP interaction, no user files.

Each voice ZIP ships with the app, and its integrity is checked by the
production read-only bundle loader before any MP3 is exposed via localhost.
"""
from pathlib import Path
import hashlib
import tempfile
import unittest

from voice_library import VoicePackLibrary, BUNDLED_ROOT
from tools.build_kokoro_voicepacks import public_rows

ROOT = Path(__file__).resolve().parents[1]
VOICES = ("af_heart", "am_michael", "bf_emma", "sveta", "masha", "dima")

try:
    from server import create_app
except ModuleNotFoundError as error:
    if error.name != "flask":
        raise
    create_app = None


class CommittedKokoroBundleTests(unittest.TestCase):
    def test_six_checked_in_voices_automatically_available_and_sha_verified(self):
        for voice in VOICES:
            self.assertTrue((BUNDLED_ROOT / (voice + ".zip")).is_file())
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "empty"
            manager = VoicePackLibrary(root=local, bundled_root=BUNDLED_ROOT)
            self.assertFalse(local.exists(), "Auto-discovery must not extract private files")
            listed = {v["id"]: v for v in manager.voices()}
            for voice in VOICES:
                self.assertTrue(listed[voice]["installed"], voice)
                entries = manager.installed[voice]["entries"]
                self.assertEqual(len(entries), 144)
                locale = "ru-RU" if voice in ("sveta", "masha", "dima") else "en-US"
                phrase = public_rows(locale)[0]
                found = manager.for_phrase(phrase["phrase_id"], phrase["source_text"], locale, voice)
                self.assertIsNotNone(found, voice)
                audio = manager.media(voice, phrase["phrase_id"])
                self.assertIsNotNone(audio, voice)
                self.assertEqual(hashlib.sha256(audio).hexdigest(), entries[phrase["phrase_id"]]["sha256"])
            self.assertEqual(sum(len(x["entries"]) for x in manager.installed.values()), 864)
            self.assertFalse(local.exists())

    def test_corruption_is_not_played_when_bundled_archives_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            bundle.mkdir()
            (bundle / "af_heart.zip").write_bytes(b"not ZIP")
            manager = VoicePackLibrary(root=Path(tmp) / "manual", bundled_root=bundle)
            self.assertFalse(any(v["id"] == "af_heart" and v["installed"]
                                 for v in manager.voices()))


@unittest.skipIf(create_app is None, "Flask unavailable")
class BundledKokoroHttpTests(unittest.TestCase):
    def test_real_prerecorded_english_plays_from_bundle_without_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = create_app(
                database=root / "study.sqlite3",
                voice_root=root / "local_audio",
                bundle_root=BUNDLED_ROOT,
            )
            client = app.test_client()
            voices = {v["id"]: v for v in client.get("/api/voice-packs").json["voices"]}
            self.assertTrue(all(voices[voice]["installed"] for voice in VOICES))
            self.assertFalse((root / "local_audio").exists())
            client.post("/api/starter-islands/surfing/import")
            islands = client.get("/api/starter-islands").json
            island_id = next(p["island_id"] for p in islands if p["id"] == "surfing")
            first = client.get(
                f"/api/islands/{island_id}/phrases?language=en-US&voice=bf_emma"
            ).json[0]
            self.assertEqual(first["review_count"], 0)
            self.assertTrue(first["audio"]["url"].startswith("/api/voice-media/bf_emma/"))
            resp = client.get(first["audio"]["url"])
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.mimetype, "audio/mpeg")
            self.assertGreater(len(resp.data), 1800)
            self.assertEqual(hashlib.sha256(resp.data).hexdigest(), first["audio"]["sha256"])
            self.assertFalse((root / "local_audio").exists())
            client.patch(
                f"/api/phrases/{first['id']}/review",
                json={"language": "en-US", "mastery": 2},
            )
            revised = client.get(
                f"/api/islands/{island_id}/phrases?language=en-US&voice=af_heart"
            ).json[0]
            self.assertEqual(revised["mastery"], 2)
            self.assertEqual(revised["review_count"], 1)
            self.assertTrue(revised["audio"]["url"].startswith("/api/voice-media/af_heart/"))


if __name__ == "__main__":
    unittest.main()
