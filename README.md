# MyWords Local

Local-first personal English and European Portuguese practice with **Vue 3 + Flask + SQLite**. Features: language islands, Focus (listening and repeating), Recall (remembering a phrase in the selected language from Russian), pre-recorded Kokoro English (US/UK), Russian prompts and Portuguese (Portugal), configurable repeats/pauses, and manual ratings stored on device.

**This is a fresh public repository containing only the standalone application.** No personal database, earlier cloud app, private project history, research screenshots, login credentials, LLM service, or outbound user telemetry is included.

## Run on Android / Termux

```bash
pkg install python nodejs-lts git
git clone https://github.com/Dmitry-dev-pet/mywords-local.git
cd mywords-local
bash setup.sh
```

Open http://127.0.0.1:8791/ on the same device. Use Ctrl+C to stop the server. **Do not expose the Flask port to the internet or a shared LAN**: it deliberately has no authentication.

Words, language-specific scores, and review events remain in git-ignored `local.sqlite3`. The browser stores playback options in `localStorage`. **All seven supported Kokoro voices are bundled in the Git checkout:** 3 English (two US, one UK), 3 Russian and 1 European Portuguese. The six new voice packs contain 864 MP3s in about 14 MB; the existing 144 Portuguese MP3s remain in the original app package. No manual archive import, system voice, model weights or Internet is needed for playback after the normal Git checkout and dependencies have been downloaded. The Russian OpenRAIL license is available inside the app and requires acceptance before selecting these voices. Keep Flask running on the same device; screen-off/background audio still needs the Android check below.

## Voice delivery: no manual ZIP imports

The ordinary Git clone/update brings versioned `data/kokoro-voicepacks-v1/*.zip`
alongside application code. At Flask startup MyWords verifies each bundled
archive (exact 144 phrase IDs, texts, SHA-256s and license files) and plays
individual MP3s directly from the ZIP. **There is no separate download,
unzip, or import procedure** for the built-in voices. The manual ZIP importer
remains collapsed under advanced settings for optional recovery or future
custom packs. English US/UK voices share one English review history; Russian
is only a prerecorded source-language prompt. No LLM runs in the application.

Note: these new assets are in [Draft PR #8](https://github.com/Dmitry-dev-pet/mywords-local/pull/8)
until the owner explicitly approves merging; the current `main` build remains
unchanged until then.

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
individual lesson rows. It creates `local.sqlite3` exclusively with
`os.open(O_EXCL)` (compatible with Termux Python even without `os.link`),
then verifies the final file. It **never overwrites an existing destination**,
removes incomplete new copies after failures and leaves the original unchanged. It refuses to run while port 8791 is open. No data is sent to GitHub.
Keep the old checkout as an additional backup until you confirm all your islands
and review counts on the new app. Do not copy old Git history, secrets or logs.

## OPEN-2: shared islands in English and European Portuguese

An island contains one list of Russian source thoughts, not a separate collection
per target language. Use the language selector to switch between **English
(en-US)** and **European Portuguese (pt-PT)**. Focus/Recall only show sentences
with a translation available for that language; the editor displays all shared
Russian thoughts and lets you add a missing translation separately.

Every language has independent ratings and review events. Switching to
Portuguese cannot change English progress, and vice versa.

The existing `phrases` and English review rows are preserved by a one-time,
idempotent schema upgrade on Flask startup. Before upgrading a populated legacy
SQLite database, MyWords makes a *consistent private SQLite backup* next to
the original: `local.sqlite3.before-multilingual.sqlite3`. This backup is
git-ignored. The old English text and scores remain in legacy compatibility
columns; the new `phrase_translations` table contains language-specific
text/scores, and `review_events.language` tracks reviews separately.
**Do not delete the private backup until you've checked your data.**

European Portuguese uses **Kokoro recordings, not Web Speech**. The versioned
package `web/audio/pt-PT-kokoro-v1/` ships with the checkout, so no remote cache,
temporary Actions artifact, separate download service or model runtime is needed
on the tablet. Flask serves these local files even in airplane mode. It checks
the manifest, public phrase IDs, source-text hashes and each audio SHA-256 at
startup. `/api/audio-pack` reports the verified installed count.

Recordings apply only to the exact shared starter phrase ID **and** matching
Portuguese text. Personal phrases or changed translations without a recording
show a clear missing-audio state; text Recall still works. Their text is never
sent to a TTS service. There is **no pt-BR or system pt-PT fallback**. If a package
file is missing/corrupt, restore the versioned package from the checkout and
restart Flask. No SQLite reset or reimport is necessary.

Focus and Recall share one player: one phrase or the rest of an island,
Pause/Resume, Stop, Next, 1–5 repeats, 0.5–1.5× playback speed (pitch preserved
where supported), and existing pause settings. Optional Russian-first reading
still needs a Russian system voice; turn it off for Portuguese-only listening.
One master MP3 per phrase is reused at all speeds. Listening never creates a
review; ratings remain a separate, explicit action.

## Optional ready-made islands

The **Готовые острова** section in the catalog offers 8 shared conversation packs (144 Russian source thoughts, 144 English
and 144 European Portuguese versions). Open **Языковые острова**, preview the entire
pack, and choose **Добавить в мои острова**. Nothing is installed automatically.
A repeat import is idempotent: existing phrases, user-created islands, scores,
and review events are not overwritten. For islands imported before Portuguese was
available, press **Добавить недостающие переводы** in the catalog to attach
144 language-specific versions without resetting your existing progress. You can practice any imported pack in
the normal Focus/Recall screens in either target language. The packs are plain public JSON in
`data/starter-islands.json`, not generated or fetched by an LLM.

Levels are approximate learning labels, not certified CEFR assessments.
The language exercise pack uses a literal translation of each Russian thought:
it does not silently change references to English into Portuguese.
You can keep adding your own sentences alongside any imported pack. The catalog
endpoint is read-only; the local database changes only after an explicit
import button press. No study history leaves the device.

## Tests

```bash
python -m unittest discover -s tests -v
node --test tests/test_audio_sequence.mjs
node --check web/app.js
npm install --ignore-scripts --no-audit --no-fund
npm run typecheck
python tools/verify_ptpt_audio.py
python tests/http_audio_smoke.py
```

The existing CI gate covers Python API/SQLite/updater/audio-integrity fixtures,
Node player tests, strict JSDoc typechecking and Chromium Playwright tests.
`tests/playwright_multilingual_smoke.py` uses real HTTP MP3 decoding/playback
with internet requests blocked; only English/Russian speech callbacks are mocked.
`tests/playwright_audio_smoke.py` separately exercises the speech watchdog with
mocked callbacks. Black/Ruff/mypy report baseline issues without blocking.
Automated checks do not certify a physical Android speaker or pronunciation.

See [audio package provenance and regeneration](docs/audio-pack-provenance.md)
and the [Android smoke checklist](docs/android-audio-smoke.md). Generation tools
are maintainer-only; **do not install their dependencies on the tablet**.

Browser audio never records reviews. Only rating buttons add a review event. The Flask app neither sends lesson text nor posts diagnostics to GitHub.

Design uses original MyWords components inspired by layout references, without external screenshot assets or third-party logos. No open-source license has been selected yet.
