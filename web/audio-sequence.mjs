/**
 * @typedef {{id: string, ru: string, en: string}} Phrase
 * @typedef {{kind: "pause", ms: number} | {kind: "speech", text: string, lang: string, index: number, phraseId: string, repetition: number, repeats: number}} PlaybackStep
 * @typedef {{speak: (utterance: SpeechUtterance) => void, cancel?: () => void, speaking?: boolean, pending?: boolean}} SpeechSynthesisPort
 * @typedef {{text: string, lang: string, rate: number, onstart?: () => void, onend?: () => void, onerror?: (event: {error: string}) => void}} SpeechUtterance
 * @typedef {{synthesis?: SpeechSynthesisPort, Utterance?: new (text: string) => SpeechUtterance, schedule?: (callback: () => void, ms: number) => number, unschedule?: (timer: number) => void, onProgress?: (step: PlaybackStep) => void, onState?: (active: boolean) => void, onFinish?: () => void, onError?: (error: string) => void, onRecovery?: () => void, watchdogIntervalMs?: number}} SpeechSequenceOptions
 */
/**
 * Deterministic browser speech playlist for the local MyWords trainer.
 * No API calls or study-memory writes occur here.
 */
/**
 * @param {Phrase[]} phrases
 * @param {{startIndex?: number, scope?: "phrase" | "island", order?: "en" | "ru-en", repeats?: number, pauseMs?: number, languagePauseMs?: number}} [options]
 * @returns {PlaybackStep[]}
 */
export function buildPlaybackSteps(phrases, {
  startIndex = 0, scope = 'phrase', order = 'en', repeats = 2,
  pauseMs = 1000, languagePauseMs = 500,
} = {}) {
  if (!Array.isArray(phrases) || !phrases.length) return [];
  if (!Number.isInteger(startIndex) || startIndex < 0 || startIndex >= phrases.length) return [];
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
    if (typeof phrase?.en !== 'string' || !phrase.en.trim()) continue;
    for (let repetition = 1; repetition <= repeats; repetition++) {
      if (order === 'ru-en' && typeof phrase.ru === 'string' && phrase.ru.trim()) {
        result.push({ kind: 'speech', text: phrase.ru, lang: 'ru-RU', index, phraseId: phrase.id, repetition, repeats });
        if (languagePauseMs) result.push({ kind: 'pause', ms: languagePauseMs });
      }
      result.push({ kind: 'speech', text: phrase.en, lang: 'en-US', index, phraseId: phrase.id, repetition, repeats });
      if ((repetition < repeats || index < lastIndex) && pauseMs) {
        result.push({ kind: 'pause', ms: pauseMs });
      }
    }
  }
  return result;
}

/** Serial speech playback; withstands Android/Chromium dropping end events.
 * A watchdog only recovers after observing a genuine speech start or active
 * synthesis. It never invents a successful review, nor skips unseen audio.
 */
export class SpeechSequence {
  /** @param {SpeechSequenceOptions} [options] */
  constructor({ synthesis, Utterance, schedule = (callback, ms) => setTimeout(callback, ms),
                unschedule = (timer) => clearTimeout(timer),
                onProgress = () => {}, onState = () => {}, onFinish = () => {},
                onError = () => {}, onRecovery = () => {},
                watchdogIntervalMs = 350 } = {}) {
    this.synthesis = synthesis;
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
    this.steps = [];
    this.position = 0;
    const wasActive = this.active;
    this.active = false;
    try { this.synthesis?.cancel?.(); } catch { /* speech engine may already be closed */ }
    if (wasActive) this.onState(false);
  }

  /** @param {PlaybackStep[]} steps
   * @param {number} [rate]
   */
  start(steps, rate = 0.85) {
    this.stop();
    if (!steps.length) return false;
    if (!this.synthesis?.speak || !this.Utterance) {
      this.onError('unsupported');
      return false;
    }
    this.steps = steps.slice();
    this.rate = rate;
    this.active = true;
    this.onState(true);
    this._advance(this.token);
    return this.active;
  }

  /** @param {number} token */
  _advance(token) {
    if (token !== this.token || !this.active) return;
    const step = this.steps[this.position++];
    if (!step) {
      this._clearWatchdog();
      this.steps = [];
      this.active = false;
      this.onState(false);
      this.onFinish();
      return;
    }
    if (step.kind === 'pause') {
      this.timer = this.schedule(() => {
        this.timer = null;
        this._advance(token);
      }, step.ms);
      return;
    }
    this.onProgress(step);
    if (token !== this.token || !this.active) return;
    const Constructor = this.Utterance;
    if (!Constructor) { this.stop(); this.onError('unsupported'); return; }
    const utterance = new Constructor(step.text);
    utterance.lang = step.lang;
    utterance.rate = this.rate;
    let settled = false;
    let observedStart = false;
    let silentSamples = 0;
    const startedAt = Date.now();
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
      const speaking = this.synthesis?.speaking;
      if (speaking === true) observedStart = true;
      // Only infer completion once speech was confirmed, and after two checks
      // that Chromium no longer reports any active/pending speech.
      if (observedStart && speaking === false && this.synthesis?.pending !== true) {
        silentSamples++;
        if (silentSamples >= 2) { finish(true); return; }
      } else silentSamples = 0;
      if (Date.now() - startedAt >= maximumMs) {
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
}
