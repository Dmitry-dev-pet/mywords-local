# Android / Termux audio smoke — owner verification

These checks require the actual tablet. Desktop Chromium, synthetic speech
callbacks and file checks do not establish that the tablet speaker works.
Do not publish the personal SQLite database, screenshots containing personal
islands, or private lesson text when reporting results.

## Before disconnecting

1. Use the owner-approved checkout containing `web/audio/pt-PT-kokoro-v1/`.
   Do not merge a draft PR or bypass `dev_auto.py`'s green `mywords-ci-gate`.
2. Run the usual `bash setup.sh --no-run` while online. No Torch, Kokoro or
   model weights belong on the tablet. The MP3 package is already in the
   checkout, not an expiring GitHub Actions artifact.
3. Start Flask normally and open `http://127.0.0.1:8791/`. In **Настройки →
   Звук**, choose Portuguese and confirm the local package reports 144/144.
   `/api/audio-pack` must return `ready: true` and `available: 144`.
4. Confirm that existing own islands, English/Portuguese scores and review
   counts are present. Do not reset or replace SQLite. Optionally import one
   public ready-made island using its normal import button; repeat import
   must not reset ratings or add duplicates.

## Internet-free listening (Flask stays local and running)

- Enable airplane mode / disable Wi-Fi and mobile data. Remove/disable the
  system Portuguese voice if convenient; it is not used by the new player.
- Keep Termux/Flask running; refresh the browser at the localhost URL. Opening
  the page, changing islands and listening must still work after the refresh.
- In Portuguese Focus, play at least one phrase from **each of the eight
  starter islands**. Confirm intelligible European Portuguese, correct text,
  complete beginnings/endings, comfortable volume, no clipping or long silence.
- Test one phrase with 1, 2 and 5 repeats; 0, 500 and 2000 ms repeat pauses;
  slow/normal/fast speed. Pitch should stay natural if the browser supports it.
- Pause midway, wait, resume; pause during the gap between repetitions; resume.
  Stop midway and during a gap. Nothing should restart later by itself.
- Play the remainder of an island, then press Next/Previous, change island or
  language. The old audio must stop and never overlap the new selection.
- Switch to Recall: listen, reveal, and rate. Listening/revealing alone must
  not create a review; an explicit rating updates only Portuguese progress.
- Enable Russian-first order with an installed Russian voice; hear Russian,
  the configured language pause, then Kokoro Portuguese. Disable Russian-first
  and confirm Portuguese still works without any Web Speech voices.
- Open a personal Portuguese phrase with no recording: show a clear missing
  recording message, no Brazilian or English substitution, no external request;
  text Recall and rating must remain usable.
- Switch to English and confirm the selected English system voice, previous
  progress, repeats and pauses still behave as before.

## Persistence and device limits

- Stop/restart Flask and refresh: package still reports 144/144, audio plays
  without internet, own islands and both languages' review counts remain.
- Lock/unlock the screen, background/restore Chromium and Termux. Record the
  observed Android behavior separately; battery/background suspension can stop
  audio or Flask and is not guaranteed by desktop tests. Stop/Next should remain
  recoverable after returning. Keep screen active for the initial acceptance.
- Report tablet model, Android version, Chromium version, date, pass/fail per
  group and any affected **public** phrase IDs. Human listening remains the
  final check of accent, pronunciation and fidelity; automated acoustic QA only
  catches technical failures.
