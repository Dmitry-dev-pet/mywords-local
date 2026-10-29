"""Verify the committed public Kokoro audio package, optionally decoding every MP3.

The default metadata/hash pass requires Python's standard library only; --decode
adds FFmpeg/NumPy measurements and is intended for generation/CI QA, not Android.
No SQLite, private phrases, system TTS or network are read or used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.generate_ptpt_audio import PACK_ID, MODEL, REVISION, MODEL_FILES, OUT, SOURCE, public_phrases, sha256


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(directory=OUT, decode=False):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["schema_version"] == 1, "Manifest schema")
    require(manifest["pack_id"] == PACK_ID, "Pack ID")
    require(manifest["language"] == "pt-PT" and manifest["lang"] == "pt-PT", "Pack language")
    require(manifest["synthetic_audio"] is True, "Synthetic disclosure")
    require(manifest["source_sha256"] == sha256(SOURCE), "Changed source catalog")
    require(manifest["model"] == MODEL and manifest["revision"] == REVISION, "Model pin")
    require(manifest["voice"] == "tuga_voicepack", "Voice pin")
    require(manifest["provenance"]["model_files_sha256"] == MODEL_FILES, "Model hashes")
    require(manifest["provenance"]["strict_checkpoint_tensor_count"] > 0, "Strict model verification")
    require(manifest["provenance"]["generator_sha256"] == sha256(ROOT / "tools/generate_ptpt_audio.py"), "Changed generator")
    expected = {e["phrase_id"]: e for e in public_phrases()}
    entries = manifest["entries"]
    require(len(entries) == 144, "Audio count")
    require(len({e["phrase_id"] for e in entries}) == 144, "Duplicate IDs")
    require(len({e["sha256"] for e in entries}) == 144, "Duplicate audio bytes")
    require({e["phrase_id"] for e in entries} == set(expected), "Mismatched source IDs")
    require({p.name for p in directory.glob("*.mp3")} == {e["file"] for e in entries}, "Missing/extra MP3")
    for entry in entries:
        reference = expected[entry["phrase_id"]]
        for key, value in reference.items():
            require(entry[key] == value, f"Changed phrase metadata {entry['phrase_id']}:{key}")
        require(entry["file"] == entry["phrase_id"] + ".mp3", "Unsafe file path")
        file = directory / entry["file"]
        require(not file.is_symlink() and file.is_file(), "Audio must be regular file")
        require(file.stat().st_size == entry["bytes"] > 1800, "Byte count")
        require(sha256(file) == entry["sha256"], "Audio SHA256")
        require(0.4 <= entry["duration_seconds"] <= 30, "Audio duration")
        require((entry["codec"], entry["sample_rate_hz"], entry["channels"]) == ("mp3", 24000, 1), "Encoding")
        require(entry["qa"]["clipped_samples"] == 0, "Clipping")
        if decode:
            from tools.generate_ptpt_audio import audio_qa
            actual = audio_qa(file)
            require(abs(actual["duration_seconds"] - entry["duration_seconds"]) < 0.00001, "Measured duration")
            require(actual["qa"]["decoded_samples"] == entry["qa"]["decoded_samples"], "Decoded sample count")
            for key in ("peak_dbfs", "rms_dbfs", "integrated_lufs", "true_peak_dbtp"):
                require(abs(actual["qa"][key] - entry["qa"][key]) <= 0.11, f"Measured {key}")
    summary = {"files": 144, "bytes": sum(e["bytes"] for e in entries),
               "duration_seconds": round(sum(e["duration_seconds"] for e in entries), 6)}
    require(summary == manifest["summary"], "Summary totals")
    for name in ("LICENSE-tts_eu_pt.txt", "LICENSE-kokoro.txt", "NOTICE-upstream.txt", "README.md"):
        require((directory / name).is_file(), f"Missing attribution {name}")
    return {"status": "PASS", "mode": "decoded-all-files" if decode else "metadata-and-sha256",
            "manifest_sha256": sha256(directory / "manifest.json"), **summary,
            "duration_range_seconds": [min(e["duration_seconds"] for e in entries), max(e["duration_seconds"] for e in entries)],
            "integrated_lufs_range": [min(e["qa"]["integrated_lufs"] for e in entries), max(e["qa"]["integrated_lufs"] for e in entries)],
            "maximum_true_peak_dbtp": max(e["qa"]["true_peak_dbtp"] for e in entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=OUT)
    parser.add_argument("--decode", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.pack, args.decode), indent=2))


if __name__ == "__main__":
    main()
