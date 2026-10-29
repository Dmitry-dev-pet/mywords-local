"""End-to-end local ZIP voice package tests with synthetic public fixtures.

No models, external network, or user database are accessed.
"""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from tools.build_kokoro_voicepacks import CATALOG, SOURCE, catalog, digest, public_rows, pack_id
from voice_library import VoicePackLibrary, InvalidVoicePack


def synthetic_zip(voice_id="af_heart", *, corrupt=False, change_text=False,
                  unsafe_name=False, symlink=False):
    config = catalog()
    voice = next(v for v in config["voices"] if v["id"] == voice_id)
    rows = public_rows(voice["locale"])
    content = {}
    entries = []
    for n, row in enumerate(rows):
        # Only a fake audio signature for testing hash/package logic, NOT
        # a valid speech file; no decoding/audio quality claim is made.
        mp3 = b"ID3" + bytes([n]) * 2100 + str(n).encode("ascii")
        name = row["phrase_id"] + ".mp3"
        content[name] = mp3
        entries.append({
            **row, "file": name, "sha256": hashlib.sha256(mp3).hexdigest(),
            "bytes": len(mp3), "duration_seconds": 2.0,
            "codec": "mp3", "sample_rate_hz": 24000, "channels": 1,
        })
    if corrupt:
        content[entries[0]["file"]] += b"corrupt"
    if change_text:
        entries[0]["source_text"] = "Changed sample text"
    manifest = {
        "schema_version": 1, "pack_id": pack_id(voice_id),
        "voice_id": voice_id, "locale": voice["locale"],
        "review_language": "en-US" if voice["locale"].startswith("en-") else voice["locale"],
        "model": config["models"][voice["model"]]["repository"],
        "revision": config["models"][voice["model"]]["revision"],
        "synthetic_audio": True, "complete": True,
        "source": "data/starter-islands.json", "source_sha256": digest(SOURCE),
        "catalog_sha256": digest(CATALOG),
        "entries": entries,
        "summary": {"files": len(entries), "bytes": sum(e["bytes"] for e in entries)},
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
        for name, mp3 in content.items():
            if unsafe_name and name == entries[0]["file"]:
                name = "../" + name
            if symlink and name == entries[0]["file"]:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, mp3)
            else:
                z.writestr(name, mp3)
    return output.getvalue()


class VoicePackZipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "installed"
        self.manager = VoicePackLibrary(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_preview_install_restart_and_idempotent_reimport(self):
        archive = synthetic_zip()
        preview = self.manager.preview(archive)
        self.assertEqual(preview["state"], "ready-to-install")
        self.assertEqual(preview["files"], 144)
        self.assertFalse(self.root.exists(), "Preview must not install data")

        installed = self.manager.install(archive)
        self.assertTrue(installed["installed"])
        self.assertTrue(installed["changed"])
        self.assertEqual(self.manager.preview(archive)["state"], "already-installed")
        self.assertFalse(self.manager.install(archive)["changed"])
        restarted = VoicePackLibrary(self.root)
        self.assertTrue(next(v for v in restarted.voices() if v["id"] == "af_heart")["installed"])
        first = public_rows("en-US")[0]
        playable = restarted.for_phrase(first["phrase_id"], first["source_text"], "en-US", "af_heart")
        self.assertIsNotNone(playable)
        self.assertEqual(playable["voice_id"], "af_heart")
        self.assertTrue(restarted.media("af_heart", first["phrase_id"]).startswith(b"ID3"))
        self.assertIsNone(restarted.for_phrase(first["phrase_id"], "A different sentence", "en-US", "af_heart"))
        self.assertIsNone(restarted.for_phrase(first["phrase_id"], first["source_text"], "pt-PT", "af_heart"))
        self.assertIsNone(restarted.media("af_heart", "../local.sqlite3"))

    def test_rejected_corruption_never_installs_files(self):
        for args in ({"corrupt": True}, {"change_text": True},
                     {"unsafe_name": True}, {"symlink": True}):
            with self.subTest(args=args):
                with self.assertRaises(InvalidVoicePack):
                    self.manager.install(synthetic_zip(**args))
                self.assertFalse(self.root.exists())

    def test_truncated_and_oversized_archive_rejected(self):
        for blob in (b"", b"not a zip", b"x" * (32 * 1024 * 1024 + 1)):
            with self.subTest(size=len(blob)):
                with self.assertRaises(InvalidVoicePack):
                    self.manager.preview(blob)

    def test_no_fallback_when_local_audio_corrupted(self):
        archive = synthetic_zip()
        self.manager.install(archive)
        first = public_rows("en-US")[0]
        target = self.root / "af_heart" / (first["phrase_id"] + ".mp3")
        target.write_bytes(b"BAD" * 710)
        self.assertIsNone(self.manager.media("af_heart", first["phrase_id"]))
        self.assertNotIn("af_heart", VoicePackLibrary(self.root).installed)

    def test_english_variants_use_one_study_phrase_identity(self):
        american = public_rows("en-US")
        british = public_rows("en-GB")
        self.assertEqual([x["phrase_id"] for x in american],
                         [x["phrase_id"] for x in british])
        self.assertEqual([x["source_text"] for x in american],
                         [x["source_text"] for x in british])


try:
    from server import create_app
except ModuleNotFoundError as error:
    if error.name != "flask":
        raise
    create_app = None


@unittest.skipIf(create_app is None, "Flask unavailable")
class VoicePackHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.client = create_app(root / "study.sqlite3", voice_root=root / "voices").test_client()

    def tearDown(self):
        self.temp.cleanup()

    def post_zip(self, path, data):
        return self.client.post(path, data={"pack": (BytesIO(data), "voice.zip")},
                                content_type="multipart/form-data")

    def test_preview_install_play_and_preserve_english_reviews(self):
        archive = synthetic_zip()
        status = self.client.get("/api/voice-packs").json["voices"]
        self.assertFalse(next(v for v in status if v["id"] == "af_heart")["installed"])
        assert self.client.post("/api/starter-islands/surfing/import").status_code in (200, 201)
        starter = self.client.get("/api/starter-islands").json
        island = next(p for p in starter if p["id"] == "surfing")
        identifier = island["island_id"]
        before = self.client.get(f"/api/islands/{identifier}/phrases?language=en-US").json
        phrase_id = before[0]["id"]
        assert self.client.patch(f"/api/phrases/{phrase_id}/review",
                                 json={"language": "en-US", "mastery": 2}).status_code == 200
        self.assertEqual(self.post_zip("/api/voice-packs/preview", archive).status_code, 200)
        self.assertEqual(self.post_zip("/api/voice-packs/install", archive).status_code, 200)
        fetched = self.client.get(f"/api/islands/{identifier}/phrases?language=en-US&voice=af_heart").json
        self.assertEqual(fetched[0]["review_count"], 1)
        self.assertEqual(fetched[0]["mastery"], 2)
        self.assertIsNotNone(fetched[0]["audio"])
        link = fetched[0]["audio"]["url"]
        delivered = self.client.get(link)
        self.assertEqual(delivered.status_code, 200)
        self.assertEqual(delivered.mimetype, "audio/mpeg")
        self.assertTrue(delivered.data.startswith(b"ID3"))
        self.assertIsNone(self.client.get(
            f"/api/islands/{identifier}/phrases?language=en-US&voice=bf_emma").json[0]["audio"])
        self.assertEqual(self.post_zip("/api/voice-packs/install", archive).json["changed"], False)
        after = self.client.get(f"/api/islands/{identifier}/phrases?language=en-US&voice=af_heart").json
        self.assertEqual(after[0]["mastery"], 2)
        self.assertEqual(after[0]["review_count"], 1)

    def test_malformed_zip_returns_client_error_not_server_error(self):
        result = self.post_zip("/api/voice-packs/preview", b"not ZIP")
        self.assertEqual(result.status_code, 400)
        self.assertIn("error", result.json)


if __name__ == "__main__":
    unittest.main()
