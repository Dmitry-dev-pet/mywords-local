"""Generate the public, versioned Kokoro pt-PT starter pack (never reads SQLite).

Generation is opt-in/offline after downloading the explicitly pinned model. The
application/Android only serves the resulting MP3s and never imports this module.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from starter_packs import load_starter_packs, starter_phrase_id, starter_island_id

PACK_ID = "pt-PT-kokoro-v1"
OUT = ROOT / "web" / "audio" / PACK_ID
SOURCE = ROOT / "data" / "starter-islands.json"
MODEL = "logus2k/kokoro_tts_eu_pt"
REVISION = "dcf0404a6552e0cc2485446724091b4cd9b4cbae"
MODEL_FILES = {
    "tuga_kokoro.pth": "d6a3e6d445b4721c8deb11618699f958bb1a17ae27dbd5aa36565286d155769f",
    "tuga_voicepack.pt": "a2decde8e4396d813cf63a77d2df879c84a5db60c80df1449de469e2da904fda",
}
VERSIONS = {
    "torch": "2.7.1+cpu", "tts_eu_pt": "0.1.1", "tugaphone": "1.4.1a2",
    "transformers": "4.57.6", "huggingface-hub": "0.36.2", "numpy": "2.4.6",
    "soundfile": "0.14.0", "num2words": "0.5.14",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def public_phrases():
    entries = []
    for pack in load_starter_packs():
        for phrase in pack["phrases"]:
            text = phrase["pt-PT"]
            if text != text.strip() or not text:
                raise ValueError("Public source must contain exact, nonempty pt-PT text")
            entries.append({
                "phrase_id": starter_phrase_id(pack["id"], phrase["en"]),
                "island_id": starter_island_id(pack["id"]),
                "source_pack": pack["id"], "source_text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "lang": "pt-PT",
            })
    if len(entries) != 144 or len({e["phrase_id"] for e in entries}) != 144:
        raise ValueError("Expected exactly 144 distinct public starter phrases")
    return entries


def run(command):
    if command[0] == "ffmpeg":
        command = command[:1] + ["-threads", "1", "-filter_threads", "1"] + command[1:]
    return subprocess.run(command, capture_output=True, text=True, check=True)


def loudness(path):
    result = run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
                  "-af", "loudnorm=I=-18:TP=-2:LRA=7:print_format=json", "-f", "null", "-"])
    data, _ = json.JSONDecoder().raw_decode(result.stderr[result.stderr.rfind("{"):])
    return {k: float(v) for k, v in data.items() if k != "normalization_type"}


def encode_audio(wav, mp3):
    # Conservative boundary trim only: retain quiet consonants, never trim within speech.
    trimmed = wav.with_name("trimmed.wav")
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(wav), "-af",
         "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-60dB:start_silence=0.06,"
         "areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-60dB:start_silence=0.10,areverse",
         "-ar", "24000", "-ac", "1", str(trimmed)])
    initial = loudness(trimmed)
    # Very short/high-crest speech can hit the true-peak ceiling before reaching
    # target LUFS. Do not silently accept quiet clips: try bounded, documented
    # compression only when the encoded result needs it, keeping the same source.
    compression = None
    candidate = trimmed
    for attempt in range(4):
        if attempt:
            threshold_db = initial["input_i"] + 1 - 6 * (attempt - 1)
            threshold = max(0.001, min(1, 10 ** (threshold_db / 20)))
            candidate = wav.with_name("compressed.wav")
            run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(trimmed), "-af",
                 f"acompressor=threshold={threshold}:ratio=3:attack=5:release=80:makeup=1",
                 "-ar", "24000", "-ac", "1", str(candidate)])
            compression = {"threshold_dbfs": round(threshold_db, 4), "ratio": 3,
                           "attack_ms": 5, "release_ms": 80, "attempt": attempt}
        measured = loudness(candidate)
        filt = ("loudnorm=I=-18:TP=-2:LRA=7:linear=true:"
                f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}")
        run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(candidate), "-af", filt, "-ar", "24000", "-ac", "1",
             "-map_metadata", "-1", "-codec:a", "libmp3lame", "-b:a", "64k", str(mp3)])
        result = loudness(mp3)
        if -20 <= result["input_i"] <= -16 and result["input_tp"] <= -1:
            return compression
    raise ValueError(f"Cannot level-match within bounded compression: {mp3.name}")


def audio_qa(path):
    import numpy as np
    probe = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                           "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
                           "-of", "json", str(path)]).stdout)
    stream = probe["streams"][0]
    duration = float(probe["format"]["duration"])
    if (stream["codec_name"], int(stream["sample_rate"]), stream["channels"]) != ("mp3", 24000, 1):
        raise ValueError(f"Unexpected codec: {path.name}")
    decoded = subprocess.run(["ffmpeg", "-threads", "1", "-nostdin", "-v", "error", "-i", str(path),
                              "-f", "f32le", "-acodec", "pcm_f32le", "-"],
                             capture_output=True, check=True).stdout
    samples = np.frombuffer(decoded, dtype="<f4")
    if not samples.size or not np.isfinite(samples).all() or not 0.4 <= duration <= 30:
        raise ValueError(f"Invalid/empty audio: {path.name}")
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples * samples)))
    if peak >= 0.99 or rms < 0.001:
        raise ValueError(f"Clipped/silent audio: {path.name}")
    # Boundary silence excludes quiet consonants at this deliberately low -60 dB threshold.
    active = np.flatnonzero(np.abs(samples) > 0.001)
    leading = float(active[0] / 24000)
    trailing = float((samples.size - active[-1] - 1) / 24000)
    measured = loudness(path)
    if not -20 <= measured["input_i"] <= -16 or measured["input_tp"] > -1:
        raise ValueError(f"Loudness/true-peak outside bounds: {path.name}: {measured}")
    if max(leading, trailing) > 0.6:
        raise ValueError(f"Excess boundary silence: {path.name}")
    return {"duration_seconds": round(duration, 6), "codec": "mp3", "sample_rate_hz": 24000,
            "channels": 1, "qa": {"decoded_samples": int(samples.size), "peak_dbfs": round(20 * math.log10(peak), 3),
            "rms_dbfs": round(20 * math.log10(rms), 3), "integrated_lufs": measured["input_i"],
            "true_peak_dbtp": measured["input_tp"], "leading_silence_seconds": round(leading, 6),
            "trailing_silence_seconds": round(trailing, 6), "clipped_samples": 0}}


def load_voice(model_dir):
    import torch
    from tts_eu_pt import TTS, g2p
    actual_versions = {name: importlib.metadata.version(name) for name in VERSIONS}
    if actual_versions != VERSIONS:
        raise ValueError(f"Unpinned dependencies: {actual_versions}")
    from huggingface_hub import hf_hub_download
    paths = {}
    for filename, expected in MODEL_FILES.items():
        path = model_dir / filename if model_dir else Path(hf_hub_download(
            repo_id=MODEL, filename=filename, revision=REVISION))
        if sha256(path) != expected:
            raise ValueError(f"Pinned model checksum mismatch: {filename}")
        paths[filename] = path
    torch.set_num_threads(2)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    g2p.assert_lect_support()
    if g2p.LECT != "pt-PT-x-lisbon":
        raise ValueError("Unexpected dialect")
    voice = TTS(device="cpu", model_path=str(paths["tuga_kokoro.pth"]),
                voicepack_path=str(paths["tuga_voicepack.pt"]), repo_id=MODEL)
    # The upstream compatibility loader has a strict=False fallback. Reload every
    # complete module strictly, stripping ONLY a verified module. prefix; this
    # proves no random/default parameters remain after loading this checkpoint.
    checkpoint = torch.load(paths["tuga_kokoro.pth"], map_location="cpu", weights_only=True)
    expected_modules = {"bert", "bert_encoder", "predictor", "text_encoder", "decoder"}
    if set(checkpoint) != expected_modules:
        raise ValueError("Unexpected checkpoint modules")
    tensor_count = 0
    identity_affine = []
    for module_name, state in checkpoint.items():
        normalized = {key.removeprefix("module."): value for key, value in state.items()}
        if len(normalized) != len(state):
            raise ValueError("Checkpoint normalization collision")
        module = getattr(voice.km, module_name)
        initial = module.state_dict()
        missing = set(initial) - set(normalized)
        # Upstream AdaIN1d enables affine solely for old ONNX export; the
        # fine-tuned checkpoint was trained with affine=False. Identity affine
        # is mathematically the same operation (and matches the pilot loader).
        allowed = {}
        for name, layer in module.named_modules():
            if isinstance(layer, torch.nn.InstanceNorm1d) and layer.affine:
                allowed[name + ".weight"] = 1
                allowed[name + ".bias"] = 0
        if missing - set(allowed):
            raise ValueError(f"Missing trained checkpoint parameters: {module_name}: {sorted(missing - set(allowed))}")
        for name in sorted(missing):
            identity = torch.full_like(initial[name], allowed[name])
            if not torch.equal(initial[name], identity):
                raise ValueError("Nonidentity default normalization parameter")
            normalized[name] = identity
            identity_affine.append({"parameter": module_name + "." + name,
                                    "value": allowed[name], "elements": identity.numel()})
        module.load_state_dict(normalized, strict=True)
        loaded = module.state_dict()
        if any(not torch.equal(loaded[key].cpu(), value.cpu()) for key, value in normalized.items()):
            raise ValueError("Loaded tensor differs from pinned checkpoint")
        tensor_count += len(normalized)
    return voice, tensor_count, identity_affine


def generate(args):
    from loguru import logger
    logger.disable("tts_eu_pt")
    from tts_eu_pt import _sentences, g2p
    import numpy as np
    import soundfile as sf
    output = args.out
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists() and not args.replace:
        raise ValueError("Pack already exists; choose a new version or explicitly --replace")
    voice, tensors, identity_affine = load_voice(args.model_dir)
    entries = public_phrases()
    for entry in entries:
        # Exact same sentence boundary semantics as the selected pilot runtime.
        chunks = _sentences(entry["source_text"])
        for chunk in chunks:
            ps, tokens = g2p.text_to_input_ids(chunk)
            if not ps.strip() or len(tokens) > 512:
                raise ValueError("Empty/overlong phoneme sequence")
        entry["phonemes_sha256"] = hashlib.sha256("\n".join(g2p.phonemize(c) for c in chunks).encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="mywords-public-tts-") as temp:
        wav = Path(temp) / "source.wav"
        for index, entry in enumerate(entries, 1):
            file = entry["phrase_id"] + ".mp3"
            audio = voice.say(entry["source_text"], speed=1.0)
            if not np.isfinite(audio).all() or audio.size == 0 or np.abs(audio).max() >= 1:
                raise ValueError(f"Invalid raw model output: {entry['phrase_id']}")
            sf.write(wav, audio, 24000, subtype="PCM_24")
            entry["peak_compression"] = encode_audio(wav, output / file)
            entry.update(audio_qa(output / file))
            entry.update(file=file, sha256=sha256(output / file), bytes=(output / file).stat().st_size)
            print(f"{index}/144 {entry['phrase_id']} {entry['duration_seconds']:.3f}s", flush=True)
    if len({entry["sha256"] for entry in entries}) != 144:
        raise ValueError("Duplicate audio content")
    manifest = {
        "schema_version": 1, "pack_id": PACK_ID, "lang": "pt-PT", "language": "pt-PT", "synthetic_audio": True,
        "source": "data/starter-islands.json", "source_sha256": sha256(SOURCE),
        "model": MODEL, "model_revision": REVISION, "revision": REVISION, "voice": "tuga_voicepack",
        "provenance": {"model": MODEL, "revision": REVISION, "voice": "tuga_voicepack",
            "model_files_sha256": MODEL_FILES, "license": "Apache-2.0", "lect": "pt-PT-x-lisbon",
            "dependencies": VERSIONS, "python": platform.python_version(),
            "ffmpeg": run(["ffmpeg", "-version"]).stdout.splitlines()[0],
            "strict_checkpoint_tensor_count": tensors, "identity_instance_norm_affine": identity_affine, "seed": 0, "synthesis_speed": 1.0,
            "generator": "tools/generate_ptpt_audio.py", "generator_sha256": sha256(__file__),
            "postprocess": "boundary-only -60dB trim; bounded 3:1 peak compression only for peak-limited clips (per-entry parameters); two-pass loudnorm I=-18 TP=-2 LRA=7; mono MP3 64kbps 24000Hz",
            "listener_review": "User selected this Kokoro voice from PR #3 A/B; full 144 pronunciation review pending"},
        "entries": entries,
        "summary": {"files": len(entries), "bytes": sum(e["bytes"] for e in entries),
                    "duration_seconds": round(sum(e["duration_seconds"] for e in entries), 6)},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["summary"], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--model-dir", type=Path, help="Directory with the two verified pinned model files")
    parser.add_argument("--replace", action="store_true", help="Explicitly regenerate an existing pack")
    generate(parser.parse_args())


if __name__ == "__main__":
    main()
