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

Six additional voice packs × 144 phrases = **864 real recordings generated and verified**.
These MP3 files are **not committed to the app source tree**; they were exported as
individual downloadable ZIP artifacts. See [the 2026-10-29 completion and SHA-256 receipt](kokoro-six-voice-receipt-2026-10-29.md).
Original Portuguese 144 MP3 remain unchanged in the checkout. For each new
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

A sample is marked `complete=false` and is **not** an installable package. Full 144-file ZIPs have been generated and verified separately.

## Automatic voice delivery with the application

**No user ZIP upload is necessary.** All six generated voice archives are
committed under `data/kokoro-voicepacks-v1/<voice-id>.zip` in the **draft PR
branch**, with fixed SHA-256s in
[`kokoro-six-voice-receipt-2026-10-29.md`](kokoro-six-voice-receipt-2026-10-29.md).
This is durable Git content, **not an expiring Actions artifact**.

When the PR is approved/merged and the ordinary `dev_auto.py` gate passes,
the same Git checkout update delivers the six archives with the MyWords code.
Flask automatically recognizes and fully validates each ZIP **at startup**.
It serves individual MP3s directly from the compressed package on
`/api/voice-media/<voice>/<phrase-id>.mp3`; it **does not download, unpack,
install to `local_voicepacks/`, or modify `local.sqlite3`**. Every local
MP3 is bound to its exact source phrase UUID, text hash, manifest model
revision, and audio SHA-256. If a package is missing/corrupt, its voice stays
unavailable rather than silently speaking with the wrong system voice.

In **Settings → Sound**, English users simply choose among the three
available voices (two US and one UK). The English study progress stays shared
across accents. Portuguese uses its existing `tuga_voicepack` (144 MP3s)
from `web/audio/pt-PT-kokoro-v1/`. For the three bundled Russian voices,
the user views and accepts the included **OpenRAIL license once** before
choosing a Russian voice for optional double-audio playback. License text
is served from the validated local archive, not an external website.

The former ZIP file picker remains in the collapsed
**Дополнительно: ручной импорт других проверенных ZIP** section solely for
advanced recovery/experiments. Its integrity checks, staging, idempotent
installation and independent local storage remain intact. It is **not**
part of ordinary app setup and must never be required to activate these
seven prebundled voices.

The `main` branch and the owner's installed Android app do **not**
automatically change merely because a draft PR contains files. This
delivery mechanism is implemented and unit-tested in the PR, but final
physical Android offline/lock-screen/pronunciation QA and owner approval
for merge are separate gates. Flask still must be running in Termux.

The ZIP importer remains an **audio-only importer for the existing
144 starter thoughts**. Importing new course islands/diaries/dialogues
from arbitrary user content is still open in #6/#7.

## Release gates

- Actual synthesis and SHA/codec/loudness QA for all 864 recordings **passed**.
  Human pronunciation and audio-artifact review on the physical tablet remains required,
  particularly for the ten selectively compressed `af_heart` recordings.
- All three Russian voice ZIPs bundle the pinned Dialogs **OpenRAIL** terms and
  the UI requests explicit acceptance before selecting their voices. License compliance in actual use
  remains the recipient's responsibility. Do not upload personal texts/audio.
- The first voice-only ZIP installer and per-voice playback are implemented;
  the general lesson content ZIP format/import remains pending in #6.
- Verify Android airplane-mode, screen lock, and background playback
  separately. No automatic merge or deployment.

Sources: https://huggingface.co/hexgrad/Kokoro-82M ,
https://huggingface.co/zaakirio/kokoro-ru ,
https://huggingface.co/logus2k/kokoro_tts_eu_pt .
