/**
 * @typedef {{url: string, duration_seconds?: number, sha256?: string, text_sha256?: string, pack_id?: string}} PhraseAudio
 * @typedef {{id: string, ru: string, en?: string, target?: string | null, audio?: PhraseAudio | null, ru_audio?: PhraseAudio | null}} Phrase
 * @typedef {{kind: "pause", ms: number} | {kind: "speech" | "audio", url?: string, text: string, lang: string, index: number, phraseId: string, repetition: number, repeats: number}} PlaybackStep
 * @typedef {{speak: (utterance: SpeechUtterance) => void, cancel?: () => void, pause?: () => void, resume?: () => void, speaking?: boolean, pending?: boolean}} SpeechSynthesisPort
 * @typedef {{text: string, lang: string, rate: number, voice?: SpeechSynthesisVoice, onstart?: () => void, onend?: () => void, onerror?: (event: {error: string}) => void}} SpeechUtterance
 * @typedef {{src: string, currentTime: number, playbackRate: number, preservesPitch: boolean, preload: string, ended: boolean, error: {code?: number} | null, load: () => void, play: () => Promise<void> | void, pause: () => void, onended: (() => void) | null, onerror: (() => void) | null}} AudioPort
 * @typedef {{audio?: AudioPort, synthesis?: SpeechSynthesisPort, Utterance?: new (text: string) => SpeechUtterance, schedule?: (callback: () => void, ms: number) => number, unschedule?: (timer: number) => void, onProgress?: (step: PlaybackStep) => void, onState?: (active: boolean) => void, onPause?: (paused: boolean) => void, onFinish?: () => void, onError?: (error: string) => void, onRecovery?: () => void, watchdogIntervalMs?: number}} SpeechSequenceOptions
 */
/**
 * Deterministic local-media / browser-speech playlist for MyWords.
 * No API calls or study-memory writes occur here.
 */
/**
 * @param {Phrase[]} phrases
 * @param {{startIndex?: number, scope?: "phrase" | "island", order?: "en" | "ru-en", repeats?: number, pauseMs?: number, languagePauseMs?: number, language?: "en-US" | "pt-PT", audioRequired?: boolean, ruAudioRequired?: boolean}} [options]
 * @returns {PlaybackStep[]}
 */
export function buildPlaybackSteps(phrases, {
  startIndex = 0, scope = 'phrase', order = 'en', repeats = 2,
  pauseMs = 1000, languagePauseMs = 500, language = 'en-US',
  audioRequired = false, ruAudioRequired = false,
} = {}) {
  if (!Array.isArray(phrases) || !phrases.length) return [];
  if (!Number.isInteger(startIndex) || startIndex < 0 || startIndex >= phrases.length) return [];
  if (!['en-US', 'pt-PT'].includes(language)) throw new RangeError('Unsupported language');
  if (!['phrase', 'island'].includes(scope)) throw new RangeError('Unsupported playlist scope');
  if (!['en', 'ru-en'].includes(order)) throw new RangeError('Unsupported language order');
  if (!Number.isInteger(repeats) || repeats < 1 || repeats > 5) throw new RangeError('Invalid repeats');
  for (const duration of [pauseMs, languagePauseMs]) {
    if (!Number.isInteger(duration) || duration < 0 || duration > 5000) throw new RangeError('Invalid pause');
  }
  const lastIndex = scope === 'island' ? phrases.length - 1 : startIndex;
  /** @type {PlaybackStep[]} */
  const result = [];
  for (let index = startIndex; index <= lastIndex; index++) {
    const phrase = phrases[index];
    const target = phrase?.target === undefined
      ? (language === 'en-US' ? phrase?.en : null)
      : phrase.target;
    // Never play English as an implicit fallback for untranslated Portuguese.
    if (typeof target !== 'string' || !target.trim()) continue;
    for (let repetition = 1; repetition <= repeats; repetition++) {
      if (order === 'ru-en' && typeof phrase.ru === 'string' && phrase.ru.trim()) {
        if (phrase.ru_audio?.url || ruAudioRequired) {
          result.push({ kind: 'audio', url: phrase.ru_audio?.url, text: phrase.ru,
            lang: 'ru-RU', index, phraseId: phrase.id, repetition, repeats });
        } else {
          result.push({ kind: 'speech', text: phrase.ru, lang: 'ru-RU', index, phraseId: phrase.id, repetition, repeats });
        }
        if (languagePauseMs) result.push({ kind: 'pause', ms: languagePauseMs });
      }
      if (language === 'pt-PT' || phrase.audio?.url || audioRequired) {
        result.push({ kind: 'audio', url: phrase.audio?.url, text: target, lang: language, index, phraseId: phrase.id, repetition, repeats });
      } else {
        result.push({ kind: 'speech', text: target, lang: language, index, phraseId: phrase.id, repetition, repeats });
      }
      if ((repetition < repeats || index < lastIndex) && pauseMs) {
        result.push({ kind: 'pause', ms: pauseMs });
      }
    }
  }
  return result;
}

/** Serial local MP3 and speech playback with cancellation across every step.
 * The one reusable audio element retains browser user-gesture authorization.
 * pt-PT never reaches Web Speech. Russian and English retain existing TTS.
 * Speech withstands Android/Chromium dropping end events.
 * A watchdog only recovers after observing a genuine speech start or active
 * synthesis. It never invents a successful review, nor skips unseen audio.
 */
export class SpeechSequence {
  /** @param {SpeechSequenceOptions} [options] */
  constructor({ synthesis, Utterance, audio, schedule = (callback, ms) => setTimeout(callback, ms),
                unschedule = (timer) => clearTimeout(timer),
                onProgress = () => {}, onState = () => {}, onPause = () => {}, onFinish = () => {},
                onError = () => {}, onRecovery = () => {},
                watchdogIntervalMs = 350 } = {}) {
    this.synthesis = synthesis;
    this.audio = audio;
    this.playAttempt = 0;
    this.onPause = onPause;
    this.paused = false;
    this.pauseStartedAt = 0;
    this.totalPausedMs = 0;
    this.timerDue = 0;
    /** @type {number | null} */
    this.timerRemaining = null;
    this.pendingAdvance = false;
    /** @type {"speech" | "audio" | "pause" | null} */
    this.currentKind = null;
    this.Utterance = Utterance;
    this.schedule = schedule;
    this.unschedule = unschedule;
    this.onProgress = onProgress;
    this.onState = onState;
    this.onFinish = onFinish;
    this.onError = onError;
    this.onRecovery = onRecovery;
    this.watchdogIntervalMs = watchdogIntervalMs;
    this.token = 0;
    this.timer = null;
    this.watchdogTimer = null;
    this.active = false;
    /** @type {PlaybackStep[]} */
    this.steps = [];
    this.position = 0;
    this.rate = 0.85;
    /** @type {SpeechSynthesisVoice | null} */
    this.voice = null;
  }

  _clearWatchdog() {
    if (this.watchdogTimer !== null) {
      this.unschedule(this.watchdogTimer);
      this.watchdogTimer = null;
    }
  }

  stop() {
    this.token++;
    if (this.timer !== null) {
      this.unschedule(this.timer);
      this.timer = null;
    }
    this._clearWatchdog();
    if (this.audio) {
      this.audio.onended = null;
      this.audio.onerror = null;
      try { this.audio.pause(); this.audio.currentTime = 0; } catch { /* no media loaded */ }
    }
    this.paused = false;
    this.onPause(false);
    this.timerRemaining = null;
    this.pendingAdvance = false;
    this.currentKind = null;
    this.steps = [];
    this.position = 0;
    const wasActive = this.active;
    this.active = false;
    try { this.synthesis?.cancel?.(); } catch { /* speech engine may already be closed */ }
    if (wasActive) this.onState(false);
  }

  /** @param {PlaybackStep[]} steps
   * @param {number} [rate]
   * @param {SpeechSynthesisVoice | null} [voice]
   */
  start(steps, rate = 0.85, voice = null) {
    this.stop();
    if (!steps.length) return false;
    if (steps.some(step => (step.kind === 'audio' && !isLocalAudioUrl(step.url)) || (step.kind === 'speech' && step.lang === 'pt-PT'))) {
      this.onError('audio-missing');
      return false;
    }
    if (steps.some(step => step.kind === 'audio') && !this.audio) {
      this.onError('audio-unsupported');
      return false;
    }
    if (steps.some(step => step.kind === 'speech') && (!this.synthesis?.speak || !this.Utterance)) {
      this.onError('unsupported');
      return false;
    }
    this.steps = steps.slice();
    this.totalPausedMs = 0;
    this.rate = Number.isFinite(rate) ? Math.max(0.5, Math.min(1.5, rate)) : 0.85;
    this.voice = voice;
    this.active = true;
    this.onState(true);
    this._advance(this.token);
    return this.active;
  }

  /** @param {number} token */
  _advance(token) {
    if (token !== this.token || !this.active) return;
    if (this.paused) { this.pendingAdvance = true; return; }
    const step = this.steps[this.position++];
    if (!step) {
      this._clearWatchdog();
      this.steps = [];
      this.active = false;
      this.onState(false);
      this.onFinish();
      return;
    }
    this.currentKind = step.kind;
    if (step.kind === 'pause') {
      this.timerDue = Date.now() + step.ms;
      this.timer = this.schedule(() => {
        this.timer = null;
        this._advance(token);
      }, step.ms);
      return;
    }
    this.onProgress(step);
    if (token !== this.token || !this.active) return;
    if (step.kind === 'audio') { this._playAudio(step, token); return; }
    const Constructor = this.Utterance;
    if (!Constructor) { this.stop(); this.onError('unsupported'); return; }
    const utterance = new Constructor(step.text);
    utterance.lang = step.lang;
    utterance.rate = this.rate;
    if (this.voice && this.voice.lang.toLowerCase().replace('_', '-') === step.lang.toLowerCase()) {
      utterance.voice = this.voice;
    }
    let settled = false;
    let observedStart = false;
    let silentSamples = 0;
    const startedAt = Date.now();
    const pausedBeforeStart = this.totalPausedMs;
    // Conservative bound for a voice that never reports the end and sometimes
    // falsely remains "speaking" after audible output has finished.
    const maximumMs = Math.min(90000, Math.max(6500,
      Math.ceil((step.text.length / 8) * 1000 / Math.max(0.5, this.rate)) + 3000));

    const finish = (recovered = false) => {
      if (settled || token !== this.token || !this.active) return;
      settled = true;
      this._clearWatchdog();
      if (recovered) {
        // Chromium may internally keep the last utterance queued. Reset the
        // voice engine before the next queued phrase; ignore its late callbacks.
        try { this.synthesis?.cancel?.(); } catch { /* best effort */ }
        this.onRecovery();
        this.timerDue = Date.now() + 100;
        this.timer = this.schedule(() => {
          this.timer = null;
          this._advance(token);
        }, 100);
      } else {
        this._advance(token);
      }
    };

    utterance.onstart = () => { observedStart = true; };
    utterance.onend = () => finish();
    utterance.onerror = (event) => {
      if (settled || token !== this.token) return;
      this.stop();
      if (!['canceled', 'interrupted'].includes(event?.error)) this.onError('speech-failed');
    };

    const check = () => {
      this.watchdogTimer = null;
      if (settled || token !== this.token || !this.active) return;
      if (this.paused) {
        this.watchdogTimer = this.schedule(check, this.watchdogIntervalMs);
        return;
      }
      const speaking = this.synthesis?.speaking;
      if (speaking === true) observedStart = true;
      // Only infer completion once speech was confirmed, and after two checks
      // that Chromium no longer reports any active/pending speech.
      if (observedStart && speaking === false && this.synthesis?.pending !== true) {
        silentSamples++;
        if (silentSamples >= 2) { finish(true); return; }
      } else silentSamples = 0;
      if (Date.now() - startedAt - (this.totalPausedMs - pausedBeforeStart) >= maximumMs) {
        if (observedStart) finish(true);
        else {
          this.stop();
          this.onError('speech-stalled');
        }
        return;
      }
      this.watchdogTimer = this.schedule(check, this.watchdogIntervalMs);
    };
    this.watchdogTimer = this.schedule(check, this.watchdogIntervalMs);
    try {
      this.synthesis?.speak(utterance);
    } catch {
      this.stop();
      this.onError('speech-failed');
    }
  }

  pause() {
    if (!this.active || this.paused) return false;
    if (this.currentKind === 'speech' && !this.synthesis?.pause) return false;
    this.paused = true;
    this.pauseStartedAt = Date.now();
    if (this.timer !== null) {
      this.timerRemaining = Math.max(0, this.timerDue - Date.now());
      this.unschedule(this.timer);
      this.timer = null;
    }
    if (this.currentKind === 'audio') this.audio?.pause();
    else if (this.currentKind === 'speech') this.synthesis?.pause?.();
    this.onPause(true);
    return true;
  }

  resume() {
    if (!this.active || !this.paused) return false;
    this.totalPausedMs += Date.now() - this.pauseStartedAt;
    this.paused = false;
    this.onPause(false);
    const token = this.token;
    if (this.pendingAdvance) {
      this.pendingAdvance = false;
      this._advance(token);
    } else if (this.timerRemaining !== null) {
      const ms = this.timerRemaining;
      this.timerRemaining = null;
      this.timerDue = Date.now() + ms;
      this.timer = this.schedule(() => { this.timer = null; this._advance(token); }, ms);
    } else if (this.currentKind === 'audio') this._resumeAudio(token);
    else if (this.currentKind === 'speech') this.synthesis?.resume?.();
    return true;
  }

  /** @param {number} token */
  _resumeAudio(token) {
    const attempt = ++this.playAttempt;
    try {
      const promise = this.audio?.play();
      promise?.catch(() => {
        if (token !== this.token || attempt !== this.playAttempt || !this.active || this.paused) return;
        this.stop(); this.onError('audio-failed');
      });
    } catch {
      if (token === this.token) { this.stop(); this.onError('audio-failed'); }
    }
  }

  /** @param {Exclude<PlaybackStep, {kind: "pause"}>} step
   * @param {number} token
   */
  _playAudio(step, token) {
    const audio = this.audio;
    if (!audio || !isLocalAudioUrl(step.url)) {
      this.stop(); this.onError('audio-missing'); return;
    }
    let settled = false;
    let lastTime = -1;
    let silentMs = 0;
    const fail = () => {
      if (settled || token !== this.token || !this.active) return;
      settled = true; this.stop(); this.onError('audio-failed');
    };
    // A queued event for the previous source dispatches to the element's NEW
    // listener. Tokens alone do not identify that event; check current state.
    audio.onended = () => {
      if (settled || token !== this.token || !this.active || !audio.ended) return;
      settled = true;
      audio.onended = null;
      audio.onerror = null;
      this._clearWatchdog();
      this._advance(token);
    };
    audio.onerror = () => { if (audio.error) fail(); };
    try {
      audio.preload = 'auto';
      audio.src = step.url || '';
      // Explicitly abort the previous resource and reset ended/error before
      // play. The same element still retains its user-gesture authorization.
      audio.load();
      audio.playbackRate = this.rate;
      audio.preservesPitch = true;
    } catch { fail(); return; }
    // A broken/missing local file must not hang or silently skip a phrase.
    const check = () => {
      this.watchdogTimer = null;
      if (settled || token !== this.token || !this.active) return;
      if (!this.paused) {
        if (audio.ended) { audio.onended?.(); return; }
        silentMs = audio.currentTime === lastTime ? silentMs + this.watchdogIntervalMs : 0;
        lastTime = audio.currentTime;
        if (silentMs >= 15000) { fail(); return; }
      }
      this.watchdogTimer = this.schedule(check, this.watchdogIntervalMs);
    };
    this.watchdogTimer = this.schedule(check, this.watchdogIntervalMs);
    this._resumeAudio(token);
  }

}


/** Only packaged same-origin files: never send private lesson text to a TTS API.
 * @param {string | undefined} url
 */
export function isLocalAudioUrl(url) {
  return typeof url === 'string' && (/^\/web\/audio\/[A-Za-z0-9_-]+\/[a-f0-9-]+\.mp3$/.test(url)
    || /^\/api\/voice-media\/[a-z][a-z0-9_]{1,40}\/[a-f0-9-]{36}\.mp3$/.test(url));
}
