# MyWords public Kokoro European Portuguese audio pack v1

These are **synthetic** recordings, not recordings of a live speaker. The 144
phrases are taken verbatim from `data/starter-islands.json`. Each MP3 is keyed by
the existing shared starter phrase UUID; no private learner data is included.

## Provenance and licensing

- Model and voice: [`logus2k/kokoro_tts_eu_pt`](https://huggingface.co/logus2k/kokoro_tts_eu_pt),
  immutable revision `dcf0404a6552e0cc2485446724091b4cd9b4cbae`.
- Runtime [`tts_eu_pt` 0.1.1](https://pypi.org/project/tts-eu-pt/0.1.1/),
  `tuga_kokoro.pth`, `tuga_voicepack.pt`, Lisbon EU-PT phonemization.
- The model author's card identifies the weights/voicepack as Apache-2.0; the
  runtime ships Apache-2.0 `LICENSE` and `NOTICE`. Copies are included here.
  Kokoro derives from StyleTTS2 (MIT) and uses TugaPhone (Apache-2.0), as noted
  in the upstream NOTICE. No model weights or runtime code are distributed in
  this audio directory.
- No output-specific prohibition was found in those published model/runtime
  terms. This distribution relies on that published permission. It is **not**
  an independent verification of the training corpus, speaker identity, or
  speaker consent, which the model card does not document. The upstream
  [training-data question](https://huggingface.co/logus2k/kokoro_tts_eu_pt/discussions/1)
  was unanswered when checked on 2026-10-29.
- This notice does not relicense the rest of MyWords or the source lesson text.

`manifest.json` records source/model/audio SHA-256 hashes, exact phrase text,
UUIDs, dependency versions, codec, measured duration, and audio QA for every
file. `tools/generate_ptpt_audio.py` reproduces the public-data-only generation;
`tools/verify_ptpt_audio.py --decode` verifies the committed files without a
model download. See `docs/audio-pack-provenance.md` for commands and limitations.

The user chose this Kokoro voice in the ten-phrase A/B experiment (PR #3).
Automated checks of all 144 files establish integrity, decodability, signal
levels, boundary silence and absence of clipping — **not** a native-speaker
pronunciation verdict or a real Android device test.
