#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mode='run'
if [[ $# -gt 0 ]]; then mode="$1"; fi
if [[ "$mode" != run && "$mode" != --no-run ]]; then echo "Usage: bash setup.sh [--no-run]" >&2; exit 2; fi
command -v python >/dev/null || { echo "Install Python (Termux: pkg install python)" >&2; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js (Termux: pkg install nodejs-lts)" >&2; exit 1; }
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
npm install --omit=dev --ignore-scripts --no-audit --no-fund
mkdir -p web/vendor
cp node_modules/vue/dist/vue.esm-browser.prod.js web/vendor/vue.esm-browser.prod.js
python -m unittest discover -s tests -v
node --test tests/test_audio_sequence.mjs
python -m py_compile server.py store.py dev_auto.py
echo "MyWords: http://127.0.0.1:8791/"
if [[ "$mode" == run ]]; then exec python server.py; fi
