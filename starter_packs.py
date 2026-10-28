"""Versioned, public, optional starter content for MyWords.

These packs are not user data. Reading the catalog never writes to SQLite.
IDs are stable so repeat imports do not create duplicates or reset reviews.
"""
from functools import lru_cache
import json
from pathlib import Path
import uuid

DATA_FILE = Path(__file__).resolve().parent / "data" / "starter-islands.json"
_NAMESPACE = "https://github.com/Dmitry-dev-pet/mywords-local/starter-islands/v1"


def starter_island_id(pack_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NAMESPACE}/island/{pack_id}"))


def starter_phrase_id(pack_id, english):
    # Content-derived IDs remain stable if a pack is reordered.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NAMESPACE}/phrase/{pack_id}/{english.strip().casefold()}"))


@lru_cache(maxsize=1)
def load_starter_packs():
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("packs"), list):
        raise ValueError("Invalid starter catalog version or shape")

    seen_packs = set()
    for pack in raw["packs"]:
        if not isinstance(pack, dict):
            raise ValueError("Invalid starter pack")
        key = pack.get("id")
        if not isinstance(key, str) or not key or not all(c.islower() or c.isdigit() or c == "-" for c in key):
            raise ValueError("Invalid starter pack key")
        if key in seen_packs:
            raise ValueError("Duplicate starter pack key")
        seen_packs.add(key)
        for field, max_len in (("title", 120), ("description", 500), ("level", 24)):
            val = pack.get(field)
            if not isinstance(val, str) or not 1 <= len(val.strip()) <= max_len:
                raise ValueError("Invalid starter metadata")
        items = pack.get("phrases")
        if not isinstance(items, list) or not items:
            raise ValueError("Empty starter pack")
        seen_english = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Invalid starter phrase")
            for field in ("ru", "en"):
                val = item.get(field)
                if not isinstance(val, str) or not 1 <= len(val.strip()) <= 2000:
                    raise ValueError("Invalid starter phrase text")
            phrase_key = item["en"].strip().casefold()
            if phrase_key in seen_english:
                raise ValueError("Duplicate English sentence in starter pack")
            seen_english.add(phrase_key)
    return tuple(raw["packs"])


def list_starter_packs():
    return [
        {**pack, "phrase_count": len(pack["phrases"]), "island_id": starter_island_id(pack["id"])}
        for pack in load_starter_packs()
    ]


def find_starter_pack(pack_id):
    return next((p for p in load_starter_packs() if p["id"] == pack_id), None)
