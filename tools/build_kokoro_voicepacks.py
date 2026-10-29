"""Plan, synthesize, and verify per-voice Kokoro packs for PUBLIC starter phrases.

No private SQLite, user text, app runtime dependency, or outbound telemetry.
Models and voicepacks are downloaded only by an EXPLICIT --generate request.
The existing 144 pt-PT files remain at their original, verified path.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from starter_packs import load_starter_packs, starter_phrase_id

CATALOG = ROOT / "data" / "kokoro-voices.json"
SOURCE = ROOT / "data" / "starter-islands.json"
OUTPUT = ROOT / "web" / "audio" / "kokoro-voicepacks-v1"
LOCALES = {"en-US", "en-GB", "ru-RU", "pt-PT"}
VOICE_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(1024 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def catalog(path: Path = CATALOG) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("voices"), list):
        raise ValueError("Unsupported voice catalog")
    models = data.get("models", {})
    names = set()
    languages = Counter()
    for voice in data["voices"]:
        if not isinstance(voice, dict):
            raise ValueError("Malformed voice")
        name, locale = voice.get("id"), voice.get("locale")
        if not isinstance(name, str) or not VOICE_ID.fullmatch(name) or name in names:
            raise ValueError("Duplicate/unsafe voice id")
        if locale not in LOCALES:
            raise ValueError("Unsupported voice locale")
        if locale == "en-GB" and not name.startswith(("bf_", "bm_")):
            raise ValueError("British voice/locale mismatch")
        if locale == "en-US" and not name.startswith(("af_", "am_")):
            raise ValueError("American voice/locale mismatch")
        model = voice.get("model")
        if model not in models or not isinstance(models[model].get("repository"), str):
            raise ValueError("Unknown model")
        if not REVISION.fullmatch(models[model].get("revision", "")):
            raise ValueError("Model is not pinned to an immutable commit")
        expected = {"english": {"en-US", "en-GB"},
                    "russian": {"ru-RU"}, "portuguese": {"pt-PT"}}
        if locale not in expected[model]:
            raise ValueError("Model/locale mismatch")
        names.add(name)
        languages["en" if locale.startswith("en-") else locale] += 1
    if languages["en"] > 3 or languages["ru-RU"] > 3 or languages["pt-PT"] > 3:
        raise ValueError("Maximum three voices per language")
    if not {"en-US", "en-GB"}.issubset({v["locale"] for v in data["voices"]}):
        raise ValueError("Both English accents are required")
    return data


def public_rows(locale: str) -> list[dict]:
    field = "ru" if locale == "ru-RU" else ("pt-PT" if locale == "pt-PT" else "en")
    rows = []
    for pack in load_starter_packs():
        for phrase in pack["phrases"]:
            text = phrase[field]
            if not text or text.strip() != text:
                raise ValueError("Invalid public phrase text")
            rows.append({
                "phrase_id": starter_phrase_id(pack["id"], phrase["en"]),
                "source_pack": pack["id"],
                "source_text": text,
                "text_sha256": text_digest(text),
                "locale": locale,
            })
    if len(rows) != 144 or len({p["phrase_id"] for p in rows}) != 144:
        raise ValueError("Expected 144 distinct public phrases")
    return rows


def voice_by_id(data: dict, name: str) -> dict:
    for voice in data["voices"]:
        if voice["id"] == name:
            return voice
    raise ValueError(f"Voice not in approved catalog: {name}")


def pack_id(name: str) -> str:
    return f"kokoro-starter-v1-{name}"


def verify(directory: Path, *, require_complete: bool = True) -> dict:
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Symlink package root")
    manifest_file = directory / "manifest.json"
    if manifest_file.is_symlink() or not manifest_file.is_file():
        raise ValueError("Manifest is missing/unsafe")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    name = manifest.get("voice_id")
    config = catalog()
    voice = voice_by_id(config, name)
    if name == "tuga_voicepack":
        raise ValueError("The existing pt-PT pack uses its original v1 verifier")
    if manifest.get("schema_version") != 1 or manifest.get("pack_id") != pack_id(name):
        raise ValueError("Manifest identity mismatch")
    if manifest.get("locale") != voice["locale"]:
        raise ValueError("Wrong voice locale")
    if manifest.get("model") != config["models"][voice["model"]]["repository"]:
        raise ValueError("Wrong model")
    if manifest.get("revision") != config["models"][voice["model"]]["revision"]:
        raise ValueError("Wrong model revision")
    if manifest.get("source_sha256") != digest(SOURCE):
        raise ValueError("Public source changed")
    if manifest.get("catalog_sha256") != digest(CATALOG):
        raise ValueError("Voice catalog changed")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Manifest entries missing")
    if require_complete and len(entries) != 144:
        raise ValueError("Incomplete voice pack")
    expected = {row["phrase_id"]: row for row in public_rows(voice["locale"])}
    seen, files, audio_hashes, total_bytes = set(), set(), set(), 0
    for item in entries:
        phrase = item.get("phrase_id")
        if phrase not in expected or phrase in seen:
            raise ValueError("Unknown or duplicate phrase")
        seen.add(phrase)
        for key, value in expected[phrase].items():
            if item.get(key) != value:
                raise ValueError(f"Source mismatch: {phrase}:{key}")
        file = item.get("file")
        if file != phrase + ".mp3":
            raise ValueError("Unsafe audio filename")
        if file in files:
            raise ValueError("Duplicate audio file")
        files.add(file)
        audio = directory / file
        if audio.is_symlink() or not audio.is_file():
            raise ValueError("Missing/unsafe MP3")
        size = audio.stat().st_size
        if not 1800 <= size <= 3_000_000 or item.get("bytes") != size:
            raise ValueError("Audio size mismatch")
        hashed = digest(audio)
        if item.get("sha256") != hashed or hashed in audio_hashes:
            raise ValueError("Bad/duplicate audio hash")
        audio_hashes.add(hashed)
        duration = item.get("duration_seconds")
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or not 0.4 <= duration <= 45):
            raise ValueError("Bad audio duration")
        if (item.get("codec"), item.get("sample_rate_hz"), item.get("channels")) != ("mp3", 24000, 1):
            raise ValueError("Bad audio format")
        total_bytes += size
    if require_complete and set(expected) != seen:
        raise ValueError("Missing starter phrases")
    actual_files = {p.name for p in directory.iterdir() if p.suffix == ".mp3"}
    if actual_files != files:
        raise ValueError("Unlisted MP3 files")
    if manifest.get("summary") != {"files": len(entries), "bytes": total_bytes}:
        raise ValueError("Wrong manifest totals")
    return {"voice_id": name, "files": len(entries), "bytes": total_bytes, "verified": True}


def synth_for_voice(voice: dict, model_info: dict):
    """Construct a pinned Kokoro synthesizer. Optional deps only at generation time."""
    import numpy as np
    import torch
    from huggingface_hub import hf_hub_download
    from kokoro import KModel, KPipeline

    repo, rev = model_info["repository"], model_info["revision"]
    torch.set_num_threads(2)
    torch.manual_seed(0)
    files = {}
    def pinned(filename: str) -> Path:
        path = Path(hf_hub_download(repo_id=repo, revision=rev, filename=filename))
        files[filename] = digest(path)
        return path

    if voice["model"] == "english":
        checkpoint = pinned(model_info["checkpoint"])
        # Verify the official Kokoro-82M weight SHA-256.
        if files[model_info["checkpoint"]] != "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4":
            raise ValueError("Unexpected English model weight checksum")
        voice_file = pinned(voice["voice_file"])
        km = KModel(repo_id=repo, model=str(checkpoint)).eval()
        pipe = KPipeline(lang_code="a" if voice["locale"] == "en-US" else "b",
                         repo_id=repo, model=km, device="cpu")

        def speak(text):
            with torch.no_grad():
                pieces = [np.asarray(result.audio, dtype="float32").reshape(-1)
                          for result in pipe(text, voice=str(voice_file), speed=1.0)]
            if not pieces or any(not p.size for p in pieces):
                raise ValueError("Empty English synthesis")
            spacer = np.zeros(2400, dtype="float32")
            return np.concatenate([item for i, p in enumerate(pieces)
                                   for item in ((spacer, p) if i else (p,))])
        return speak, files

    if voice["model"] == "russian":
        checkpoint = pinned(voice["checkpoint"])
        voice_file = pinned(voice["voice_file"])
        g2p_file = pinned("ru_g2p.py")
        # This is pinned third-party code. Review its dependencies and licensing
        # before running it in an isolated generation environment.
        spec = importlib.util.spec_from_file_location("mywords_pinned_ru_g2p", g2p_file)
        if spec is None or spec.loader is None:
            raise ValueError("Cannot load pinned Russian phonemizer")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        g2p = module.RuG2P()
        km = KModel(repo_id=repo, model=str(checkpoint)).eval()
        # Weight-only loading: never unpickle arbitrary Python objects from a voicepack.
        pack = torch.load(voice_file, map_location="cpu", weights_only=True)

        def speak(text):
            phonemes, oov = g2p(text)
            if oov or not phonemes or len(phonemes) > 510:
                raise ValueError(f"Unsupported Russian phonemes: {oov}")
            with torch.no_grad():
                result = km(phonemes, pack[len(phonemes) - 1], 1.0,
                            return_output=True).audio
            return np.asarray(result.cpu().numpy(), dtype="float32").reshape(-1)
        return speak, files

    raise ValueError("pt-PT reuses the existing 144 recordings")


def generate(name: str, *, output: Path = OUTPUT, sample: int = 0) -> dict:
    voice_data = catalog()
    voice = voice_by_id(voice_data, name)
    if name == "tuga_voicepack":
        raise ValueError("pt-PT is already generated: use tools/verify_ptpt_audio.py")
    if sample < 0 or sample > 144:
        raise ValueError("Invalid sample size")
    # Samples are explicitly NOT complete installable packs.
    rows = public_rows(voice["locale"])
    if sample:
        rows = rows[:sample]
    destination = Path(output) / name
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing voice pack: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    from tools.generate_ptpt_audio import audio_qa, encode_audio
    import numpy as np
    import soundfile as sf

    speak, model_hashes = synth_for_voice(voice, voice_data["models"][voice["model"]])
    with tempfile.TemporaryDirectory(prefix="mywords-voice-", dir=destination.parent) as tmp:
        stage = Path(tmp)
        with tempfile.TemporaryDirectory(prefix="kokoro-wav-") as wav_tmp:
            wav = Path(wav_tmp) / "source.wav"
            entries = []
            for index, row in enumerate(rows, 1):
                output_file = stage / (row["phrase_id"] + ".mp3")
                audio = speak(row["source_text"])
                if (not audio.size or not np.isfinite(audio).all()
                        or np.max(np.abs(audio)) >= 1 or np.max(np.abs(audio)) < 0.001):
                    raise ValueError("Invalid model audio")
                sf.write(wav, audio, 24000, subtype="PCM_24")
                encode_audio(wav, output_file)
                qa = audio_qa(output_file)
                entries.append({**row, **qa, "file": output_file.name,
                                "sha256": digest(output_file), "bytes": output_file.stat().st_size})
                print(f"{name}: {index}/{len(rows)}", flush=True)
        manifest = {
            "schema_version": 1, "pack_id": pack_id(name), "voice_id": name,
            "locale": voice["locale"],
            "review_language": "en-US" if voice["locale"] in ("en-US", "en-GB") else voice["locale"],
            "model": voice_data["models"][voice["model"]]["repository"],
            "revision": voice_data["models"][voice["model"]]["revision"],
            "model_files_sha256": model_hashes,
            "model_license": voice_data["models"][voice["model"]]["license"],
            "license_review_required": voice["model"] == "russian",
            "synthetic_audio": True,
            "source": "data/starter-islands.json", "source_sha256": digest(SOURCE),
            "catalog_sha256": digest(CATALOG),
            "complete": not bool(sample),
            "entries": entries,
            "summary": {"files": len(entries), "bytes": sum(e["bytes"] for e in entries)},
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verify(stage, require_complete=not sample)
        # Atomic directory rename on the same filesystem; a failed run never
        # replaces previously installed voices or corrupts the local database.
        stage.rename(destination)
    return {"voice": name, "files": len(rows), "destination": str(destination),
            "complete": not bool(sample)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    actions = ap.add_mutually_exclusive_group()
    actions.add_argument("--generate", metavar="VOICE_ID")
    actions.add_argument("--verify", metavar="PACK_DIR", type=Path)
    ap.add_argument("--out", type=Path, default=OUTPUT)
    ap.add_argument("--sample", type=int, default=0,
                    help="generate an incomplete, noninstallable sample (0=all 144)")
    args = ap.parse_args()
    if args.verify:
        result = verify(args.verify)
    elif args.generate:
        result = generate(args.generate, output=args.out, sample=args.sample)
    else:
        data = catalog()
        result = {"voices": [
            {"id": v["id"], "locale": v["locale"],
             "existing": bool(v.get("existing_audio_pack")),
             "planned_phrases": len(public_rows(v["locale"]))}
            for v in data["voices"]]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
