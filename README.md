# MyWords Local

Local-first personal English practice with **Vue 3 + Flask + SQLite**. Features: language islands, Focus (listening and repeating), Recall (remembering an English phrase from Russian), customizable browser speech and pauses, and manual ratings stored on device.

**This is a fresh public repository containing only the standalone application.** No personal database, earlier cloud app, private project history, research screenshots, login credentials, LLM service, or outbound user telemetry is included.

## Run on Android / Termux

```bash
pkg install python nodejs-lts git
git clone https://github.com/Dmitry-dev-pet/mywords-local.git
cd mywords-local
bash setup.sh
```

Open http://127.0.0.1:8791/ on the same device. Use Ctrl+C to stop the server. **Do not expose the Flask port to the internet or a shared LAN**: it deliberately has no authentication.

Words, scores, and review events remain in git-ignored `local.sqlite3`. The browser stores playback options in `localStorage`. Real Android speech depends on installed system voices and the screen remaining active.

## Develop with the GitHub CI gate

```bash
bash setup.sh --no-run
. .venv/bin/activate
python dev_auto.py
```

This foreground-only updater fetches the public `main` branch and fast-forwards only after the exact commit passes the `mywords-ci-gate` GitHub Actions check. A GitHub CLI (`gh`) login is needed for its check-run query; without it simply run `python server.py`. The updater never resets tracked local edits or erases SQLite.

## Move existing study data from another local checkout

Stop the previous Flask supervisor with Ctrl+C before starting the new app.
Run `bash setup.sh --no-run` in the new checkout, then import the old database:

```bash
python migrate_db.py "/absolute/path/to/previous/local.sqlite3"
. .venv/bin/activate && python dev_auto.py
```

The migration uses SQLite's consistent backup API and verifies the database and
individual lesson rows. It creates `local.sqlite3` exclusively (mode 0600):
**never overwrites an existing destination** and leaves the original file
untouched. It refuses to run while port 8791 is open. No data is sent to GitHub.
Keep the old checkout as an additional backup until you confirm all your islands
and review counts on the new app. Do not copy old Git history, secrets or logs.

## Tests

```bash
python -m unittest discover -s tests -v
node --test tests/test_audio_sequence.mjs
node --check web/app.js
npm install --ignore-scripts --no-audit --no-fund
npm run typecheck
```

Public GitHub Actions runs Python API/SQLite/updater fixtures, Node audio tests, strict JSDoc typechecking and real Chromium Playwright tests with **mocked** speech callbacks. Black/Ruff/mypy initially report baseline issues without blocking. Real Android TTS still needs on-device testing.

Browser audio never records reviews. Only rating buttons add a review event. The Flask app neither sends lesson text nor posts diagnostics to GitHub.

Design uses original MyWords components inspired by layout references, without external screenshot assets or third-party logos. No open-source license has been selected yet.
