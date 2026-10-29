"""Diagnose a PUBLIC starter phrase failing strict Kokoro audio normalization.

Never imports local study data; models download only on an explicitly run job.
"""
from pathlib import Path
import argparse
import json
import numpy as np
import soundfile as sf
from tools.build_kokoro_voicepacks import catalog, voice_by_id, synth_for_voice, public_rows, encode_voice_audio
from tools.generate_ptpt_audio import loudness, audio_qa

parser = argparse.ArgumentParser()
parser.add_argument("--voice", required=True)
parser.add_argument("--phrase-id", required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
conf = catalog()
voice = voice_by_id(conf, args.voice)
phrase = next(p for p in public_rows(voice["locale"]) if p["phrase_id"] == args.phrase_id)
speak, model_hashes = synth_for_voice(voice, conf["models"][voice["model"]])
audio = speak(phrase["source_text"])
raw = args.out / "raw.wav"
sf.write(raw, audio, 24000, subtype="PCM_24")
metadata = {
    "voice": args.voice, "phrase_id": phrase["phrase_id"],
    "source_text": phrase["source_text"],
    "peak": float(np.max(np.abs(audio))),
    "rms": float(np.sqrt(np.mean(np.square(audio)))),
    "duration": float(len(audio) / 24000),
    "raw_loudness": loudness(raw),
    "model_files_sha256": model_hashes,
}
try:
    metadata["preprocess"] = encode_voice_audio(raw, args.out / "normalized.mp3")
    metadata["output_qa"] = audio_qa(args.out / "normalized.mp3")
except Exception as error:
    metadata["normalization_error"] = type(error).__name__ + ": " + str(error)
(args.out / "diagnostic.json").write_text(
    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(metadata, ensure_ascii=False, indent=2))
