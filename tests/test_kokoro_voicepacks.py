"""No-network, no-model tests for the optional Kokoro voice package builder."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_kokoro_voicepacks as pack


class VoiceCatalogTests(unittest.TestCase):
    def test_three_english_both_accents_three_russian_one_portuguese(self):
        data = pack.catalog()
        selected = data["voices"]
        self.assertEqual(len(selected), 7)
        self.assertEqual(sum(v["locale"].startswith("en-") for v in selected), 3)
        self.assertEqual({v["locale"] for v in selected},
                         {"en-US", "en-GB", "ru-RU", "pt-PT"})
        self.assertEqual(sum(v["locale"] == "ru-RU" for v in selected), 3)
        self.assertEqual(sum(v["locale"] == "pt-PT" for v in selected), 1)

    def test_public_source_ids_stable_across_accents(self):
        american = pack.public_rows("en-US")
        british = pack.public_rows("en-GB")
        russian = pack.public_rows("ru-RU")
        portuguese = pack.public_rows("pt-PT")
        for rows in (american, british, russian, portuguese):
            self.assertEqual(len(rows), 144)
            self.assertEqual(len({r["phrase_id"] for r in rows}), 144)
        self.assertEqual([r["phrase_id"] for r in american],
                         [r["phrase_id"] for r in british])
        self.assertEqual([r["phrase_id"] for r in american],
                         [r["phrase_id"] for r in portuguese])
        self.assertEqual([r["phrase_id"] for r in american],
                         [r["phrase_id"] for r in russian])
        self.assertEqual([r["source_text"] for r in american],
                         [r["source_text"] for r in british])

    def _changed_catalog(self, update):
        doc = copy.deepcopy(pack.catalog())
        update(doc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            return self.assertRaises(ValueError, pack.catalog, path)

    def test_reject_more_than_three_english_voices(self):
        self._changed_catalog(lambda data: data["voices"].append({
            "id": "af_bella", "locale": "en-US",
            "model": "english", "voice_file": "voices/af_bella.pt"
        }))

    def test_reject_unpinned_model(self):
        self._changed_catalog(
            lambda data: data["models"]["russian"].update(revision="main"))

    def test_reject_voice_locale_mismatch(self):
        self._changed_catalog(
            lambda data: data["voices"][0].update(locale="en-GB"))

    def test_no_pt_regeneration(self):
        with self.assertRaisesRegex(ValueError, "already generated"):
            pack.generate("tuga_voicepack")

    def test_unknown_voice_rejected(self):
        with self.assertRaises(ValueError):
            pack.voice_by_id(pack.catalog(), "nonexistent")


class VoicePackIntegrityTests(unittest.TestCase):
    def _create_fixture(self, dest):
        voice = pack.voice_by_id(pack.catalog(), "af_heart")
        one = dict(pack.public_rows(voice["locale"])[0])
        mp3 = dest / (one["phrase_id"] + ".mp3")
        payload = b"\xff\xfb" + bytes(range(256)) * 12
        mp3.write_bytes(payload)
        one.update(file=mp3.name, sha256=pack.digest(mp3), bytes=len(payload),
                   duration_seconds=2.0, codec="mp3", sample_rate_hz=24000,
                   channels=1)
        data = pack.catalog()
        manifest = {
            "schema_version": 1, "pack_id": pack.pack_id(voice["id"]),
            "voice_id": voice["id"], "locale": voice["locale"],
            "model": data["models"][voice["model"]]["repository"],
            "revision": data["models"][voice["model"]]["revision"],
            "source_sha256": pack.digest(pack.SOURCE),
            "catalog_sha256": pack.digest(pack.CATALOG),
            "entries": [one],
            "summary": {"files": 1, "bytes": len(payload)},
        }
        (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest, mp3

    def test_partial_fixture_verifies_only_when_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self._create_fixture(path)
            self.assertTrue(pack.verify(path, require_complete=False)["verified"])
            with self.assertRaisesRegex(ValueError, "Incomplete voice pack"):
                pack.verify(path)

    def test_wrong_mp3_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _, mp3 = self._create_fixture(path)
            mp3.write_bytes(mp3.read_bytes()[:-1] + b"Z")
            with self.assertRaisesRegex(ValueError, "audio hash"):
                pack.verify(path, require_complete=False)

    def test_voice_pack_cannot_refer_to_wrong_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            manifest, _ = self._create_fixture(path)
            manifest["entries"][0]["source_text"] = "Different text"
            (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source mismatch"):
                pack.verify(path, require_complete=False)

    def test_symlink_audio_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            manifest, mp3 = self._create_fixture(path)
            original = path / "other.mp3"
            mp3.rename(original)
            mp3.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "Missing/unsafe"):
                pack.verify(path, require_complete=False)


if __name__ == "__main__":
    unittest.main()
