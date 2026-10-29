# MyWords · six offline Kokoro voice packs — generation receipt

**Date:** 2026-10-29. **Source:** the 144 **public** starter thoughts in `data/starter-islands.json`; SHA-256 `f993a6f54e8556c1084f50d00b73760bed546863092ed6aa349b2367c41fd721`. No private SQLite, LLM, app TTS model or user's personal learning data was used.

## Result

**864/864 new real MP3s generated**, representing 6 voices × 144 phrases. Together with the pre-existing **144/144 pt-PT Kokoro** files, MyWords's starter corpus has **1,008 prerecordable audio variants** across English US, English GB, Russian prompts and European Portuguese.

| Locale | Kokoro voice | Files | ZIP SHA-256 (offline pack) |
| --- | --- | ---: | --- |
| en-US | `af_heart` | 144 | `8ffccce51ba6ce3cc1425f4590bb7e9536889eb84ce76791b78c6bf32062d3e9` |
| en-US | `am_michael` | 144 | `f74b1b55020aa9eb313b83ac6a0c570b35bd61552c9635bd13b8e1c17cc1908a` |
| en-GB | `bf_emma` | 144 | `236166ddd5c68b1ff475fb36f4bdad25ffc51ac20c5eb89b9fc98892b0a2ca82` |
| ru-RU | `sveta` | 144 | `e53e747e1031d018e022087bd4916b9dd0bdab31e559f52e3309805f3747cf38` |
| ru-RU | `masha` | 144 | `d1349a16c2340427d4843bc221f4fc3c340b505e08ab88879bf31a41868793ad` |
| ru-RU | `dima` | 144 | `a6088bab132530d46e2ea8ec1f4c2cb151ffd00253eec4fab41eeb860f7dfcb5` |

**Auditable GitHub Actions receipts:** [English `am_michael` + `bf_emma` (run 40970225453)](https://github.com/Dmitry-dev-pet/mywords-local/actions/runs/40970225453); [English `af_heart` (run 40972310239)](https://github.com/Dmitry-dev-pet/mywords-local/actions/runs/40972310239); [Russian `sveta`, `masha`, `dima` (run 40970682882)](https://github.com/Dmitry-dev-pet/mywords-local/actions/runs/40970682882). Standard public-repository GitHub-hosted runners were used. Actions ZIP artifacts retain files for **7 days**; they are not an authoritative permanent host.

## Verification

All 864 manifest entries were checked against the exact public source text and stable existing phrase UUID, all SHA-256 bytes in the downloaded ZIPs were independently recalculated, and 864/864 MP3s have generation-side FFmpeg decoder/codec and signal QA. They use mono 24 kHz 64 kbps MP3, loudness within **−20 … −16 LUFS**, true-peak at most **−1 dBTP**, valid durations, and no clipped/silent audio. Independent decoder smoke of **three representative MP3s per voice** also passed. These checks **do not prove correct pronunciation or pleasant audio quality**.

Processing exceptions requiring extra human listening:
- `af_heart`: 134 standard, 8 moderate compression, 1 stronger compression, and 1 oversampled soft-clip (phrase “I know the word, but I can't remember it.”). The soft-clipped output passed unchanged QA limits, not independent listening.
- `bf_emma`: 143 standard, 1 moderate compression.
- `am_michael`, `sveta`, `masha`, `dima`: all 144 standard.

Six-ZIP umbrella bundle was independently assembled from the exact downloaded artifacts, total **14,138,532 bytes**, SHA-256 `cb30106f203eac6ef8b2b661e56ef5c06a665582babb2e3eb44eee3a3a40a781`, with a local `bundle-validation.json` and instructions. Outer bundle is **not** directly accepted by the single-voice ZIP importer; extract it before importing a voice.

## License and release boundary

All three Russian archives carry the pinned upstream Dialogs OpenRAIL license text `LICENSE-dialogs-openrail.md` with a matching SHA-256; the installer presents the terms and requires explicit acceptance. No Russian voice model weights ship to Android. The English Kokoro-82M voice model is tagged Apache-2.0; prior Portuguese pack retains its existing attribution.

**No merge to main, app deployment, personal DB read/change, or Dot.** [Draft PR #8](https://github.com/Dmitry-dev-pet/mywords-local/pull/8) includes the audio-only ZIP import and voice selector, but the **general language-content ZIP importer** for new islands/diagrams is not yet implemented (#6/#7). Real Android/Termux offline/background playback and subjective pronunciation QA must still be done before releasing PR #8.
