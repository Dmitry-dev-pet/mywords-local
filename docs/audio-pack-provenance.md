# Kokoro pt-PT: reproducible public audio pack

## Data and identity

The sole synthesis input is the existing `pt-PT` field in
`data/starter-islands.json`: 8 public starter islands, 144 phrases. English is
used only by the established `starter_phrase_id(pack_id, english)` identity
function; it is never translated or spoken for this package. Russian, private
SQLite, ratings and review history are never generation inputs.

The versioned MP3s and manifest live under `web/audio/pt-PT-kokoro-v1/` and ship
with the application checkout. This is durable source-controlled storage, not
an expiring Actions artifact or external runtime service. Android needs neither
PyTorch nor a Portuguese system TTS voice: Flask serves the local static files.
Once installed with the app, they remain available after a Flask restart and
without Internet access. No model weights belong in this repository.

## Pinned generation

Model: `logus2k/kokoro_tts_eu_pt`, revision
`dcf0404a6552e0cc2485446724091b4cd9b4cbae`; selected voice `tuga_voicepack`.

| Model file | SHA-256 |
| --- | --- |
| `tuga_kokoro.pth` | `d6a3e6d445b4721c8deb11618699f958bb1a17ae27dbd5aa36565286d155769f` |
| `tuga_voicepack.pt` | `a2decde8e4396d813cf63a77d2df879c84a5db60c80df1449de469e2da904fda` |

The `tts_eu_pt` 0.1.1 wheel used for generation has SHA-256
`38c32722134d3072f32681f2fd3a638305124e6ed4350f06dcc7262ed30c6d84`.
Model checksums are enforced before loading. The primary runtime and G2P
versions match the selected PR #3 experiment, and all resolved transitive
packages are frozen in `tools/requirements-ptpt-audio-lock.txt`.

Use an **authorized local CPU environment**, not a hosted Actions shortcut:

```bash
python3.12 -m venv /tmp/mywords-tts-venv
/tmp/mywords-tts-venv/bin/pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
/tmp/mywords-tts-venv/bin/pip install -r tools/requirements-ptpt-audio-lock.txt
# Install ffmpeg + ffprobe through your operating system package manager.
# The initial call downloads only the two immutable pinned files to HF_HOME.
XDG_CACHE_HOME=/tmp/mywords-tts-cache HF_HOME=/tmp/mywords-hf \
  /tmp/mywords-tts-venv/bin/python tools/generate_ptpt_audio.py \
  --out /tmp/mywords-pt-PT-kokoro-v1
```

For an already downloaded/verified directory containing both files, use
`--model-dir /path/to/models` with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`.
The checked-in pack was generated locally using that offline mode. Copy the
four attribution/README files alongside a newly generated pack for verification.
Existing manifests require explicit `--replace`; prefer a new pack version for
an intentional model/text/postprocessing change.

Generation uses CPU, two threads, deterministic PyTorch algorithms, seed 0 and
original synthesis speed 1.0. Playback changes speed from that single recording.
Bit-for-bit equality across different PyTorch/FFmpeg/CPU versions is not claimed;
the manifest includes the actual Python and FFmpeg versions and file hashes.

## Fail-closed model loading

The upstream compatibility loader can fall back to `strict=False`. The generator
therefore independently verifies the complete five-module checkpoint, normalizes
only the `module.` prefix, reloads with `strict=True`, and compares every loaded
tensor to the pinned checkpoint.

There is one documented architecture compatibility case: upstream `AdaIN1d`
sets `InstanceNorm1d(affine=True)` for an old ONNX exporter although training used
`affine=False`. The checkpoint lacks those extra affine tensors. The generator
permits **only** missing tensors belonging to actual `InstanceNorm1d` layers,
verifies their existing values are exactly weight=1/bias=0, explicitly supplies
those identity tensors, then strictly loads everything. Identity affine is
mathematically equivalent to the trained non-affine operation and matches the
selected pilot runtime. Every such parameter is enumerated in the manifest.
No arbitrary missing trained parameter or unexpected tensor is accepted.

The generator probes sub-regional lect support and verifies every sentence's
phonemes/tokens before inference. It rejects empty output, unmapped symbols and
over-510-token truncation rather than accepting the runtime's silent fallback.
The dialect remains `pt-PT-x-lisbon`, never Brazilian Portuguese.

## Encoding and all-file QA

Boundary-only silence removal uses a conservative −60 dB threshold, retaining
60 ms at the beginning/100 ms at the end; no internal speech is trimmed. Each
clip is normalized with measured two-pass FFmpeg loudness normalization
(I=−18 LUFS, TP=−2 dBTP, LRA=7), then encoded mono MP3, 24 kHz, 64 kbps.
If a short, high-crest clip reaches its true-peak ceiling before −20 LUFS,
the generator applies bounded 3:1 compression (5 ms attack, 80 ms release)
with a threshold relative to its measured input loudness, then remeasures and
normalizes. It tries at most three thresholds, each 6 dB lower. Already compliant
clips are not compressed. Each entry records whether compression was required
and its exact parameters. This fixes quiet peak-limited speech without relaxing
the output −20…−16 LUFS / ≤−1 dBTP validation limits. Human listening still needs
to check for pronunciation or audible processing artifacts.

```bash
python tools/verify_ptpt_audio.py
# Full decoder/signal QA also needs NumPy and FFmpeg, but not TTS/model weights:
/tmp/mywords-tts-venv/bin/python tools/verify_ptpt_audio.py --decode
```

Verification covers 144 distinct shared phrase IDs, exact text SHA-256,
source/model pins, safe filenames, exact file inventory, audio SHA-256/size,
nonzero durations, codec/sample-rate/channels, decoded sample counts, boundary
silence, level measurements and clipping. A changed source text cannot silently
reuse old audio. These checks do not prove pronunciation quality; listen on the
actual tablet and ask a fluent European Portuguese speaker about uncertain
phrases. See the package README for license attribution and training-rights
verification limits.

## Recorded verification (2026-10-29)

`docs/audio-pack-validation.json` records the independently rerun validation:
**144/144** files decoded, 2,764,800 audio bytes, 341.352 seconds total;
individual clips 1.224–4.320 seconds. Measured loudness is −19.99…−18.40 LUFS
and the highest true peak is −2.18 dBTP. All clips pass clipping/silence checks.
45 peak-limited clips needed the first compression setting; none needed a
stronger retry. The other 99 clips were not compressed.

A fresh offline process regenerated the first three phrases and produced
**bit-identical MP3 SHA-256 hashes**. This is a sampled reproducibility check,
not a claim that all 144 were independently regenerated a second time.
The strict model check covered 688 loaded state tensors: 548 pretrained
checkpoint tensors plus 140 explicitly verified identity-affine tensors.

The full package's manifest SHA-256 is
`355172ab2c0b80ad1e254673716967d932136c86cb71f56d3473aa9c7115b842`.
Pronunciation review and a real Android smoke remain separate manual checks.
