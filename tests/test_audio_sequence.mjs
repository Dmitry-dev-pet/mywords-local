import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPlaybackSteps, SpeechSequence } from '../web/audio-sequence.mjs';

const PHRASES = [
  { id: 'a', ru: 'Привет', en: 'Hello' },
  { id: 'b', ru: 'Я учу английский', en: 'I am learning English' },
  { id: 'c', ru: 'До встречи', en: 'See you' },
];

function harness() {
  const speech = [];
  const timers = new Map();
  let timerId = 0;
  const states = [], progress = [], errors = [], completed = [];
  const synth = { speak(u) { speech.push(u); }, cancel() {} };
  class Utterance { constructor(text) { this.text = text; } }
  const player = new SpeechSequence({
    synthesis: synth, Utterance,
    schedule(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
    unschedule(id) { timers.delete(id); },
    onState: value => states.push(value),
    onProgress: step => progress.push(step),
    onError: err => errors.push(err),
    onFinish: () => completed.push(true),
  });
  return { player, speech, timers, states, progress, errors, completed,
           tick() { const [id, task] = timers.entries().next().value; timers.delete(id); task.fn(); return task.ms; } };
}

test('one English phrase repeats with pause and no trailing pause', () => {
  const steps = buildPlaybackSteps(PHRASES, { startIndex: 1, repeats: 2, pauseMs: 1200 });
  assert.deepEqual(steps.map(s => s.kind), ['speech', 'pause', 'speech']);
  assert.deepEqual(steps.filter(s => s.kind === 'speech').map(s => [s.lang, s.text, s.index]),
    [['en-US', 'I am learning English', 1], ['en-US', 'I am learning English', 1]]);
  assert.equal(steps[1].ms, 1200);
});

test('island mode starts from selected card and plays Russian then English', () => {
  const steps = buildPlaybackSteps(PHRASES, {
    startIndex: 1, scope: 'island', order: 'ru-en', repeats: 1,
    languagePauseMs: 500, pauseMs: 2000,
  });
  assert.deepEqual(steps.map(s => s.kind), ['speech', 'pause', 'speech', 'pause', 'speech', 'pause', 'speech']);
  assert.deepEqual(steps.filter(s => s.kind === 'speech').map(s => [s.index, s.lang]),
    [[1, 'ru-RU'], [1, 'en-US'], [2, 'ru-RU'], [2, 'en-US']]);
  assert.deepEqual(steps.filter(s => s.kind === 'pause').map(s => s.ms), [500, 2000, 500]);
});

test('player advances once per utterance and completes', () => {
  const h = harness();
  const steps = buildPlaybackSteps(PHRASES, { repeats: 2, pauseMs: 900 });
  assert.equal(h.player.start(steps, 0.65), true);
  assert.equal(h.speech.length, 1);
  assert.equal(h.speech[0].rate, 0.65);
  h.speech[0].onend();
  assert.equal(h.timers.size, 1);
  assert.equal(h.tick(), 900);
  assert.equal(h.speech.length, 2);
  h.speech[1].onend();
  assert.equal(h.player.active, false);
  assert.deepEqual(h.states, [true, false]);
  assert.equal(h.completed.length, 1);
  assert.equal(h.errors.length, 0);
});

test('stop during pause cancels pending work and stale callbacks', () => {
  const h = harness();
  h.player.start(buildPlaybackSteps(PHRASES, { repeats: 2 }));
  const old = h.speech[0];
  old.onend();
  assert.equal(h.timers.size, 1);
  h.player.stop();
  assert.equal(h.timers.size, 0);
  old.onend();
  assert.equal(h.speech.length, 1);
  assert.equal(h.completed.length, 0);
});

test('a newly started session ignores old callbacks', () => {
  const h = harness();
  h.player.start(buildPlaybackSteps(PHRASES, { repeats: 2 }));
  const old = h.speech[0];
  h.player.start(buildPlaybackSteps(PHRASES, { startIndex: 2, repeats: 1 }));
  old.onend();
  assert.equal(h.speech.length, 2);
  assert.equal(h.speech[1].text, 'See you');
  h.speech[1].onend();
  assert.equal(h.completed.length, 1);
});

test('speech errors stop without advancing', () => {
  const h = harness();
  h.player.start(buildPlaybackSteps(PHRASES, { repeats: 2 }));
  h.speech[0].onerror({ error: 'network' });
  assert.equal(h.player.active, false);
  assert.deepEqual(h.errors, ['speech-failed']);
  assert.equal(h.speech.length, 1);
});

test('playlist builder does not change phrase data or ratings', () => {
  const snapshot = JSON.stringify(PHRASES);
  assert.deepEqual(buildPlaybackSteps([], {}), []);
  assert.deepEqual(buildPlaybackSteps(PHRASES, { startIndex: 20 }), []);
  assert.throws(() => buildPlaybackSteps(PHRASES, { repeats: 9 }), RangeError);
  buildPlaybackSteps(PHRASES, { scope: 'island', order: 'ru-en', repeats: 5 });
  assert.equal(JSON.stringify(PHRASES), snapshot);
});

test('progress callback may stop without speaking', () => {
  const synth = { calls: 0, speak() { this.calls++; }, cancel() {} };
  class Utterance { constructor(text) { this.text = text; } }
  let player;
  player = new SpeechSequence({ synthesis: synth, Utterance, onProgress: () => player.stop() });
  player.start(buildPlaybackSteps(PHRASES, { repeats: 1 }));
  assert.equal(synth.calls, 0);
});


test('missing onend recovers only after the engine reports completed speech', () => {
  const timers = new Map(); let nextId = 0; const calls = []; let recovered = 0;
  const synthesis = {
    speaking: false, pending: false, cancel() { this.speaking = false; },
    speak(u) { this.speaking = true; calls.push(u); u.onstart(); },
  };
  class Utterance { constructor(text) { this.text = text; } }
  const player = new SpeechSequence({ synthesis, Utterance,
    schedule(fn, ms) { const id = ++nextId; timers.set(id, fn); return id; },
    unschedule(id) { timers.delete(id); },
    onRecovery() { recovered++; },
  });
  function tick() { const [id, fn] = timers.entries().next().value; timers.delete(id); fn(); }
  player.start(buildPlaybackSteps(PHRASES,{repeats:2,pauseMs:0}),1);
  assert.equal(calls.length,1);
  synthesis.speaking=false;
  tick();
  assert.equal(calls.length,1);
  tick();
  assert.equal(recovered,1);
  calls[0].onend();
  tick();
  assert.equal(calls.length,2);
  synthesis.speaking=false;
  tick(); tick(); tick();
  assert.equal(player.active,false);
  assert.equal(recovered,2);
});

test('watchdog does not skip an utterance that never started', () => {
  const timers = new Map(); let nextId = 0; const calls = [];
  const synthesis={ speaking:false,pending:false,cancel(){},speak(u){calls.push(u)} };
  class Utterance {constructor(text){this.text=text}}
  const player=new SpeechSequence({synthesis,Utterance,
    schedule(fn){const n=++nextId;timers.set(n,fn);return n},
    unschedule(n){timers.delete(n)},
  });
  player.start(buildPlaybackSteps(PHRASES,{repeats:2,pauseMs:0}));
  for(let i=0;i<3;i++) {const [id,fn]=timers.entries().next().value;timers.delete(id);fn();}
  assert.equal(calls.length,1);
  assert.equal(player.active,true);
  player.stop();
  assert.equal(timers.size,0);
});

test('watchdog resets stuck speaking flag after generous timeout', () => {
  const previous=Date.now;
  let current=100000;
  Date.now=()=>current;
  try {
    const timers=new Map();let idx=0;const calls=[];let recovered=0;
    const synthesis={speaking:true,pending:false,cancel(){this.speaking=false},speak(u){this.speaking=true;calls.push(u);u.onstart()}};
    class Utterance{constructor(text){this.text=text}}
    const player=new SpeechSequence({synthesis,Utterance,
      schedule(fn,ms){const i=++idx;timers.set(i,fn);return i},
      unschedule(i){timers.delete(i)},
      onRecovery(){recovered++},
    });
    const tick=()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);fn()};
    player.start(buildPlaybackSteps(PHRASES,{repeats:1,pauseMs:0}));
    current+=8000;
    tick();
    assert.equal(recovered,1);
    tick();
    assert.equal(player.active,false);
    assert.equal(calls.length,1);
  } finally {Date.now=previous;}
});
