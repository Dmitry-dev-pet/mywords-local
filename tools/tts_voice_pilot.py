"""Generate an opt-in, public-data-only pt-PT TTS voice comparison.

Reuses the exact translations in data/starter-islands.json, never user SQLite.
Run on an isolated GitHub Actions runner. Weights downloaded to runner cache,
but only small comparison MP3s and provenance metadata enter the artifact.

Usage:
  python tools/tts_voice_pilot.py --engine piper --out pilot/piper
  python tools/tts_voice_pilot.py --engine kokoro --out pilot/kokoro
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "starter-islands.json"
# (stable public pack ID, zero-based phrase index).
SELECTION = (
    ("small-talk", 0),
    ("small-talk", 5),
    ("daily-life", 1),
    ("clarifying", 0),
    ("travel", 5),
    ("travel", 7),
    ("surfing", 8),
    ("technology", 0),
    ("teaching", 6),
    ("learning-english", 2),
)
PIPER_MODEL = "rhasspy/piper-voices"
PIPER_BASE = "pt/pt_PT/tugão/medium/pt_PT-tugão-medium.onnx"
KOKORO_MODEL = "logus2k/kokoro_tts_eu_pt"


def samples():
    catalog = json.loads(SOURCE.read_text(encoding="utf-8"))
    packs = {p["id"]: p for p in catalog["packs"]}
    result = []
    for i, (pack_id, index) in enumerate(SELECTION, 1):
        phrase = packs[pack_id]["phrases"][index]
        sentence = phrase["pt-PT"].strip()
        if not sentence or len(sentence) > 2000:
            raise ValueError("Missing or invalid European Portuguese sentence")
        result.append({
            "number": i,
            "source_pack": pack_id,
            "source_index": index,
            "ru": phrase["ru"],
            "pt-PT": sentence,
            "en": phrase["en"],
            "basename": f"{i:02d}-{pack_id}-{index + 1:02d}",
        })
    if len(result) != 10 or len({x["basename"] for x in result}) != 10:
        raise ValueError("Pilot must contain ten unique sentences")
    return result


def synth_piper(pairs, tempdir, output_dir):
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice

    # Download only the voice and matching config; do not commit model weights.
    model = hf_hub_download(repo_id=PIPER_MODEL, filename=PIPER_BASE)
    config = hf_hub_download(repo_id=PIPER_MODEL, filename=PIPER_BASE + ".json")
    voice = PiperVoice.load(str(model), config_path=str(config))
    for sentence in pairs:
        name = sentence["basename"] + ".wav"
        with wave.open(str(tempdir / name), "wb") as wav:
            voice.synthesize_wav(sentence["pt-PT"], wav)
        encode_audio(tempdir / name, output_dir / (sentence["basename"] + ".mp3"))
    return {"model": PIPER_MODEL, "voice": "pt_PT-tugão-medium",
            "model_file": PIPER_BASE, "sample_rate_hz": 22050}


def synth_kokoro(pairs, tempdir, output_dir):
    from tts_eu_pt import TTS

    voice = TTS()
    for sentence in pairs:
        name = sentence["basename"] + ".wav"
        voice.save(str(tempdir / name), sentence["pt-PT"])
        encode_audio(tempdir / name, output_dir / (sentence["basename"] + ".mp3"))
    return {"model": KOKORO_MODEL, "voice": "tuga_voicepack",
            "model_file": "tuga_kokoro.pth", "sample_rate_hz": 24000}


def encode_audio(wav_path, mp3_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required for the pilot")

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "format=duration", "-of", "default=nk=1:nw=1",
        str(wav_path),
    ], capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())
    if not 0.4 <= duration <= 45:
        raise RuntimeError(f"Unexpected audio duration for {wav_path.name}: {duration}")
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(wav_path), "-vn", "-ac", "1",
        # Level-match independent voices before human A/B listening.
        # Avoid choosing Piper simply because Kokoro's original output is ~12 dB quieter.
        "-af", "loudnorm=I=-18:TP=-2:LRA=7",
        "-codec:a", "libmp3lame", "-b:a", "64k", str(mp3_path),
    ], check=True)
    if mp3_path.stat().st_size < 1800:
        raise RuntimeError(f"Empty or corrupt audio file: {mp3_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("piper", "kokoro"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    import tempfile
    phrases = samples()
    with tempfile.TemporaryDirectory(prefix="mywords-ptpt-tts-") as temp:
        source_dir = Path(temp)
        if args.engine == "piper":
            provenance = synth_piper(phrases, source_dir, args.out)
        else:
            provenance = synth_kokoro(phrases, source_dir, args.out)
    entries = []
    for s in phrases:
        name = s["basename"] + ".mp3"
        file = args.out / name
        entries.append({
            **s,
            "file": name,
            "bytes": file.stat().st_size,
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        })
    (args.out / "manifest.json").write_text(
        json.dumps({
            "engine": args.engine,
            "language": "pt-PT",
            "synthetic_audio": True,
            "audio_postprocess": "ffmpeg loudnorm I=-18 TP=-2 LRA=7; mono MP3 64kbps",
            "provenance": provenance,
            "source": "data/starter-islands.json",
            "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "samples": entries,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"PASS {args.engine}: {len(entries)} authentic synthesized pt-PT audio files",
          f"total_bytes={sum(x['bytes'] for x in entries)}", flush=True)


if __name__ == "__main__":
    main()
