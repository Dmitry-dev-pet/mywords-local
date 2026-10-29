# Kokoro voice packs (three choices per language)

**Status, 2026-10-29: implementation branch, not released.** All Kokoro
synthesis happens **before** installing a pack; no LLM, TTS model, or network
synthesis in MyWords on Android.

## Confirmed voice catalog

| Audio locale | Voice | Model |
| --- | --- | --- |
| en-US | af_heart (female), am_michael (male) | hexgrad/Kokoro-82M |
| en-GB | bf_emma (female) | hexgrad/Kokoro-82M |
| ru-RU | sveta (female), masha (female), dima (male) | zaakirio/kokoro-ru |
| pt-PT | tuga_voicepack (single speaker) | logus2k/kokoro_tts_eu_pt |

**English is three total**, spanning British and American pronunciation.
The official European Portuguese model presently offers **one verified
speaker**, not three. Brazilian Portuguese must never be used as a silent
substitute. Changing English accent or voice never creates a second English
phrase, score, or review history.

## Package construction

The versioned catalog is `data/kokoro-voices.json`. The optional generator
`tools/build_kokoro_voicepacks.py` uses the **public 144 starter phrases**
only. The existing Kokoro Portuguese pack under
`web/audio/pt-PT-kokoro-v1/` contains 144 ready files and is reused as-is.

Six additional voice packs × 144 phrases = **864 new recordings planned**.
Those recordings are **not present** in this work branch yet. For each new
voice, the generator creates:

```text
web/audio/kokoro-voicepacks-v1/
  af_heart/
    manifest.json
    <stable-existing-phrase-UUID>.mp3
  am_michael/
    ...
  bf_emma/
    ...
```

The manifest records phrase UUID, exact source text, text hash, locale,
review language, immutable model revision, artifact hashes, MP3 SHA-256,
duration, encoding QA and license. The English US/GB audio uses identical
English source sentences and the same stored English progress.

The current `starter_phrase_id(pack_id, english)` retains the existing 144
UUIDs; it must **not** be reused to derive IDs in the generic imported-pack
format (#6). New packs need explicit, immutable IDs.

Generation stages files in a private temporary directory, verifies, atomically
renames the finished directory, and never overwrites an existing pack or
touches `local.sqlite3`.

## Safe local usage

The planner/validator needs no TTS model or network access:

```bash
python tools/build_kokoro_voicepacks.py
python -m unittest tests.test_kokoro_voicepacks -v
python tools/verify_ptpt_audio.py
```

Generation is **opt-in** in an isolated CPU generation environment with
compatible `torch`, `kokoro`, `huggingface-hub`, `soundfile`, `numpy` and
FFmpeg/FFprobe. It downloads the **pinned** model/voice files on first use,
checks their hashes, and reuses the existing two-pass normalization and signal
QA in `tools/generate_ptpt_audio.py`.

```bash
# Noninstallable three-phrase sample:
python tools/build_kokoro_voicepacks.py --generate af_heart \
  --sample 3 --out /tmp/mywords-kokoro-samples

# Full pack:
python tools/build_kokoro_voicepacks.py --generate af_heart \
  --out /tmp/mywords-kokoro-complete

# Verify complete 144-file pack:
python tools/build_kokoro_voicepacks.py --verify \
  /tmp/mywords-kokoro-complete/af_heart
```

The Russian generator additionally uses the pinned third-party `ru_g2p.py`
module with Russian stress handling; it and its dependencies require a review
before they are run. Do not execute model/frontend code with personal secrets.
Russian checkpoint/voice SHA-256s are stored during generation.

A sample is marked `complete=false` and is **not** an installable package.
This branch does **not** enable new voices in the Android player yet.

## Release gates

- Validate actual synthesis of 864 files and listen to pronunciation on the
  physical tablet. Python hashes and signal tests are not a listening test.
- Verify **OpenRAIL** restrictions for publicly sharing Russian generated
  audio; do not upload personal text/audio to public GitHub.
- Implement secure ZIP install and per-voice local playback in #6, with no
  silent system-TTS fallback; leave all learning progress intact.
- Verify Android airplane-mode, screen lock, and background playback
  separately. No automatic merge or deployment.

Sources: https://huggingface.co/hexgrad/Kokoro-82M ,
https://huggingface.co/zaakirio/kokoro-ru ,
https://huggingface.co/logus2k/kokoro_tts_eu_pt .
