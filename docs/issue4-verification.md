# Issue #4 verification record — 2026-10-29

This is a draft implementation, not an Android acceptance or merge approval.
Canonical task and progress journal: [Issue #4](https://github.com/Dmitry-dev-pet/mywords-local/issues/4).

## Package evidence

- 144 real Kokoro MP3 files, 144 stable shared phrase IDs, 144 distinct exact
  Portuguese source texts and 144 distinct audio SHA-256 values.
- Existing catalog Git blob: `31fbcba876c24bf8297da007137d117cd4a8f496`.
- Catalog SHA-256: `f993a6f54e8556c1084f50d00b73760bed546863092ed6aa349b2367c41fd721`.
- Manifest SHA-256: `355172ab2c0b80ad1e254673716967d932136c86cb71f56d3473aa9c7115b842`.
- MP3 bytes: **2,764,800** (2.64 MiB), total duration **341.352 seconds**;
  individual clips **1.224–4.32 seconds**. Mono, 24 kHz, 64 kbps.
- Measured integrated loudness: **−19.99 to −18.40 LUFS**; maximum true peak:
  **−2.18 dBTP**. Per-file signal measurements are in the manifest.
- Versioned files ship in Git with the app; no model weights, private SQLite,
  public release, external service, temporary-artifact dependency or tablet TTS
  runtime is included.

## Executed checks

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | **47 passed**: API, synthetic SQLite/migration/updater, all-file hash/ID checks, corruption/missing-file handling, independent progress |
| `npm test` | **32 passed**: English/Russian TTS, Portuguese media, repeats/delays, pause/resume, stop/next, stale callbacks/events/promises, missing/private audio, no pt-BR fallback |
| `npm run typecheck` | **Passed**, strict JSDoc player check |
| JS syntax, Python compileall, Vue template compilation, `git diff --check` | **Passed** |
| `python tools/verify_ptpt_audio.py` | **Passed**, all 144 files and provenance/source/model hashes |
| `python tools/verify_ptpt_audio.py --decode` | **Passed**, independent full decode and acoustic measurements of all 144 files |
| Fresh offline generation process, first three public phrases | **Passed**, byte-identical MP3 hashes; see [machine-readable report](audio-pack-validation.json) |
| `python tests/http_audio_smoke.py` (temporary synthetic database only) | **Passed**: 144 real loopback HTTP MP3 responses, MIME and SHA-256; byte-range response **206**, correct 32-byte payload |

The catalog, Store/schema, migration, `dev_auto.py` and CI workflow were not
changed. Existing updater tests still require an exact successful
`mywords-ci-gate`; it has not been weakened or replaced with a local assertion.

## Not yet established

- **Chromium E2E: not run to completion.** This cloud shell's Chromium could
  not create a required socket. One permitted escalation attempt failed before
  execution due to a read-only runtime mount. An independent existing cloud
  browser could not reach the shell's localhost (`ERR_CONNECTION_REFUSED`).
  No sandbox disabling, public tunnel or extra service was used.
- The updated `tests/playwright_multilingual_smoke.py` is ready for a permitted
  runtime. It decodes/plays actual HTTP MP3s with external network blocked and
  no system Portuguese voice; only English/Russian speech is mocked. Its syntax
  passed, but that is **not** a browser execution pass.
- **Remote CI: pending.** The owner's current execution policy prohibits
  GitHub-hosted Actions, including free runners. Publication uses `[skip ci]`
  rather than silently triggering the existing hosted workflow. The gate must
  become green through an explicitly authorized execution route before merge or
  automatic update. No workflow or runner infrastructure was changed.
- **Physical Android and full pronunciation review: pending.** Follow
  [the tablet checklist](android-audio-smoke.md), including offline refresh,
  all eight islands, real speaker, controls, English/Russian behavior, personal
  phrase fallback, preserved history and restart/background behavior.

Published model licensing and upstream training-rights limitations are described
in [the package notice](../web/audio/pt-PT-kokoro-v1/README.md). Automated signal
QA does not constitute a human intelligibility/accent review.
