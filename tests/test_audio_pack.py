"""Audio integrity, exact identity lookup and read-only HTTP regressions.

Only temporary synthetic SQLite fixtures are used. Unit fault-injection uses
tiny byte fixtures; the integration checks require all real committed MP3s.
"""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_pack import AudioCatalog, PACK_ID, PACK_ROOT, public_phrases, text_sha256
from starter_packs import load_starter_packs, starter_phrase_id

try:
    from server import create_app
except ModuleNotFoundError as error:
    if error.name != "flask":
        raise
    create_app = None


class AudioCatalogFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.public = {"fixture-one": ("fixture", "Olá."), "fixture-two": ("fixture", "Adeus.")}
        self.entries = []
        for phrase_id, (source_pack, text) in self.public.items():
            content = b"UNIT-TEST-BYTES-NOT-AUDIO-" + phrase_id.encode()
            file = phrase_id + ".mp3"
            (self.root / file).write_bytes(content)
            self.entries.append({"phrase_id": phrase_id, "source_pack": source_pack,
                                 "source_text": text, "text_sha256": text_sha256(text),
                                 "lang": "pt-PT", "file": file,
                                 "sha256": hashlib.sha256(content).hexdigest(),
                                 "bytes": len(content), "duration_seconds": 1.2})
        self.manifest = {"schema_version": 1, "pack_id": PACK_ID,
                         "language": "pt-PT", "entries": self.entries}
        self.write_manifest()
        self.mock_public = patch("audio_pack.public_phrases", return_value=self.public)
        self.mock_public.start()

    def tearDown(self):
        self.mock_public.stop()
        self.temp.cleanup()

    def write_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_exact_id_text_language_required(self):
        catalog = AudioCatalog(self.root)
        self.assertTrue(catalog.status()["ready"])
        audio = catalog.for_phrase("fixture-one", "Olá.", "pt-PT")
        self.assertEqual(audio["url"], f"/web/audio/{PACK_ID}/fixture-one.mp3")
        for phrase_id, text, language in (("private-id", "Olá.", "pt-PT"),
                                          ("fixture-one", "Edited", "pt-PT"),
                                          ("fixture-one", "Olá.", "pt-BR"),
                                          ("fixture-one", "Olá.", "en-US"),
                                          ("fixture-one", None, "pt-PT")):
            self.assertIsNone(catalog.for_phrase(phrase_id, text, language))
        audio["url"] = "changed"
        self.assertNotEqual(catalog.for_phrase("fixture-one", "Olá.", "pt-PT")["url"], "changed")

    def test_corrupt_or_missing_file_never_gets_an_audio_url(self):
        (self.root / "fixture-one.mp3").write_bytes(b"CORRUPTED")
        catalog = AudioCatalog(self.root)
        self.assertEqual(catalog.status()["available"], 1)
        self.assertEqual(catalog.status()["status"], "incomplete-package")
        self.assertIsNone(catalog.for_phrase("fixture-one", "Olá.", "pt-PT"))
        (self.root / "fixture-two.mp3").unlink()
        self.assertEqual(AudioCatalog(self.root).status()["available"], 0)
        # Even byte-identical symlink targets are not accepted/read as media.
        target = self.root / "external-fixture.bin"
        target.write_bytes(b"UNIT-TEST-BYTES-NOT-AUDIO-fixture-two")
        (self.root / "fixture-two.mp3").symlink_to(target)
        self.assertEqual(AudioCatalog(self.root).status()["available"], 0)

    def test_bad_manifest_fails_closed_without_crashing_app(self):
        original = copy.deepcopy(self.manifest)
        mutations = (
            lambda m: m.update(language="pt-BR"),
            lambda m: m["entries"].pop(),
            lambda m: m["entries"][1].update(phrase_id="fixture-one"),
            lambda m: m["entries"][1].update(file="../outside.mp3"),
            lambda m: m["entries"][1].update(text_sha256="0" * 64),
            lambda m: m["entries"][1].update(duration_seconds=float("nan")),
            lambda m: m["entries"][1].update(duration_seconds=10 ** 1000),
            lambda m: m["entries"][1].update(duration_seconds=True),
            lambda m: m["entries"][1].update(source_text="Different text"),
        )
        for change in mutations:
            self.manifest = copy.deepcopy(original)
            change(self.manifest)
            self.write_manifest()
            with self.subTest(manifest=self.manifest):
                self.assertEqual(AudioCatalog(self.root).status()["status"], "invalid-package")
                self.assertEqual(AudioCatalog(self.root).entries, {})
        (self.root / "manifest.json").write_text("NOT JSON", encoding="utf-8")
        self.assertEqual(AudioCatalog(self.root).status()["status"], "invalid-package")

    def test_missing_package_is_explicit(self):
        (self.root / "manifest.json").unlink()
        self.assertEqual(AudioCatalog(self.root).status()["status"], "missing-package")


class CommittedAudioPackTests(unittest.TestCase):
    def test_reproducible_manifest_provenance_and_attribution(self):
        from tools.verify_ptpt_audio import verify
        self.assertEqual(verify()["files"], 144)

    def test_real_package_has_all_144_identical_public_phrase_ids_and_hashes(self):
        self.assertEqual(len(public_phrases()), 144)
        catalog = AudioCatalog()
        self.assertEqual(catalog.status(), {"pack_id": PACK_ID, "language": "pt-PT",
                         "available": 144, "expected": 144, "ready": True, "status": "ready"})
        manifest = json.loads((PACK_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(catalog.entries), set(public_phrases()))
        self.assertEqual(len(list(PACK_ROOT.glob("*.mp3"))), 144)
        self.assertEqual(len({x["sha256"] for x in manifest["entries"]}), 144)
        for phrase_id, (_, text) in public_phrases().items():
            self.assertIsNotNone(catalog.for_phrase(phrase_id, text, "pt-PT"))


@unittest.skipIf(create_app is None, "Flask is unavailable")
class AudioHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "synthetic-study.sqlite3"
        self.client = create_app(self.database).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_all_real_audio_paths_and_restart_preserve_shared_progress(self):
        self.assertTrue(self.client.get("/api/audio-pack").get_json()["ready"])
        all_rows = []
        for pack in load_starter_packs():
            island = self.client.post(f"/api/starter-islands/{pack['id']}/import").get_json()
            all_rows.extend(self.client.get(
                f"/api/islands/{island['island_id']}/phrases?language=pt-PT").get_json())
        self.assertEqual(len(all_rows), 144)
        first = all_rows[0]
        for lang, score in (("en-US", 2), ("pt-PT", 1)):
            self.client.patch(f"/api/phrases/{first['id']}/review", json={"language": lang, "mastery": score})
        with sqlite3.connect(self.database) as db:
            before = db.execute("SELECT * FROM review_events ORDER BY id").fetchall()
        for row in all_rows:
            audio = row["audio"]
            self.assertIsNotNone(audio)
            response = self.client.get(audio["url"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "audio/mpeg")
            self.assertEqual(hashlib.sha256(response.data).hexdigest(), audio["sha256"])
            response.close()
        ranged = self.client.get(first["audio"]["url"], headers={"Range": "bytes=0-31"})
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(len(ranged.data), 32)
        ranged.close()
        reopened = create_app(self.database).test_client()
        self.assertTrue(reopened.get("/api/audio-pack").get_json()["ready"])
        for lang, score in (("en-US", 2), ("pt-PT", 1)):
            rows = reopened.get(f"/api/islands/{first['island_id']}/phrases?language={lang}").get_json()
            same = next(r for r in rows if r["id"] == first["id"])
            self.assertEqual((same["mastery"], same["review_count"]), (score, 1))
            self.assertEqual(same["audio"] is not None, lang == "pt-PT")
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT * FROM review_events ORDER BY id").fetchall(), before)

    def test_private_or_modified_translation_does_not_borrow_starter_audio(self):
        pack = load_starter_packs()[0]
        text = pack["phrases"][0]["pt-PT"]
        own = self.client.post("/api/islands", json={"title": "Synthetic private island"}).get_json()
        self.client.post(f"/api/islands/{own['id']}/phrases", json={
            "ru": "Synthetic thought", "target": text, "language": "pt-PT"})
        own_row = self.client.get(f"/api/islands/{own['id']}/phrases?language=pt-PT").get_json()[0]
        self.assertIsNone(own_row["audio"])
        imported = self.client.post(f"/api/starter-islands/{pack['id']}/import").get_json()
        phrase_id = starter_phrase_id(pack["id"], pack["phrases"][0]["en"])
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE phrase_translations SET text=? WHERE phrase_id=? AND language='pt-PT'",
                       ("Synthetic edited translation", phrase_id))
        rows = self.client.get(f"/api/islands/{imported['island_id']}/phrases?language=pt-PT").get_json()
        self.assertIsNone(next(r for r in rows if r["id"] == phrase_id)["audio"])
        self.assertEqual(self.client.get("/api/islands").get_json()[0]["id"], own["id"])


if __name__ == "__main__":
    unittest.main()
