"""Read-only, local prerecorded audio lookup. Never touches study SQLite.

The versioned package ships with the checkout. Only exact starter UUID AND
source-text matches receive audio; a private/edited phrase never borrows an
unrelated recording or gets sent to a synthesizer.
"""
import hashlib
import json
import math
from pathlib import Path

from starter_packs import load_starter_packs, starter_phrase_id

PACK_ID = "pt-PT-kokoro-v1"
PACK_ROOT = Path(__file__).resolve().parent / "web" / "audio" / PACK_ID


def text_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def public_phrases():
    return {
        starter_phrase_id(pack["id"], item["en"]): (pack["id"], item["pt-PT"].strip())
        for pack in load_starter_packs()
        for item in pack["phrases"]
        if item.get("pt-PT")
    }


class AudioCatalog:
    """Fail closed on missing/corrupt media, without preventing text practice.

    Verify once per Flask start. No audio/model download, migration, or writes.
    Restart Flask after replacing the versioned files to recheck their hashes.
    """

    def __init__(self, root=PACK_ROOT):
        self.root = Path(root)
        self.entries = {}
        self.expected = len(public_phrases())
        self.reason = "missing-package"
        try:
            self._load()
        except (OSError, ValueError, TypeError, KeyError):
            self.entries = {}
            self.reason = "invalid-package"

    def _load(self):
        path = self.root / "manifest.json"
        if path.is_symlink():
            raise ValueError("Manifest must be a regular file")
        if not path.is_file():
            return
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict)
                or manifest.get("schema_version") != 1 or manifest.get("pack_id") != PACK_ID
                or manifest.get("language") != "pt-PT"):
            raise ValueError("Unexpected audio package")
        entries = manifest["entries"]
        expected = public_phrases()
        if not isinstance(entries, list) or len(entries) != self.expected:
            raise ValueError("Incomplete manifest")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid manifest entry")
            phrase_id = entry["phrase_id"]
            if phrase_id in seen or phrase_id not in expected:
                raise ValueError("Duplicate or unexpected phrase")
            seen.add(phrase_id)
            source_pack, source_text = expected[phrase_id]
            if (entry["source_pack"] != source_pack or entry["source_text"] != source_text
                    or entry["text_sha256"] != text_sha256(source_text)
                    or entry.get("lang") != "pt-PT"
                    or entry["file"] != phrase_id + ".mp3"):
                raise ValueError("Source identity mismatch")
            duration = entry["duration_seconds"]
            if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                    or not 0.4 <= duration <= 45 or not math.isfinite(duration)):
                raise ValueError("Invalid audio duration")
            audio_file = self.root / entry["file"]
            if audio_file.is_symlink() or not audio_file.is_file():
                continue
            try:
                payload = audio_file.read_bytes()
            except OSError:
                continue
            if len(payload) != entry["bytes"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                continue
            self.entries[phrase_id] = {
                "url": f"/web/audio/{PACK_ID}/{entry['file']}",
                "sha256": entry["sha256"],
                "text_sha256": entry["text_sha256"],
                "duration_seconds": duration,
                "pack_id": PACK_ID,
            }
        self.reason = "ready" if len(self.entries) == self.expected else "incomplete-package"

    def for_phrase(self, phrase_id, text, language):
        if language != "pt-PT" or not isinstance(text, str):
            return None
        entry = self.entries.get(phrase_id)
        if entry is None or text_sha256(text) != entry["text_sha256"]:
            return None
        return dict(entry)

    def status(self):
        return {"pack_id": PACK_ID, "language": "pt-PT", "available": len(self.entries),
                "expected": self.expected, "ready": self.reason == "ready", "status": self.reason}
