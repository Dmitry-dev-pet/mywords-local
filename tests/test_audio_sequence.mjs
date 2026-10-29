import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPlaybackSteps, SpeechSequence, isLocalAudioUrl } from '../web/audio-sequence.mjs';

const PHRASES = [
  { id: 'a', ru: 'Привет', en: 'Hello' },
  { id: 'b', ru: 'Я учу английский', en: 'I am learning English' },
  { id: 'c', ru: 'До встречи', en: 'See you' },
];

function harness({ audio, noSpeech = false } = {}) {
  const speech = [];
  const timers = new Map();
  let timerId = 0;
  const states = [], progress = [], errors = [], completed = [];
  const synth = { speak(u) { speech.push(u); }, cancel() {} };
  class Utterance { constructor(text) { this.text = text; } }
  const player = new SpeechSequence({
    audio, synthesis: noSpeech ? undefined : synth, Utterance: noSpeech ? undefined : Utterance,
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

test('Portuguese uses pt-PT recordings and does not borrow English text', () => {
  const source = [
    {id:'one',ru:'Я хочу поймать волну.',en:'I want to catch a wave.',target:'Quero apanhar uma onda.'},
    {id:'two',ru:'Привет',en:'Hello',target:null}
  ];
  const steps=buildPlaybackSteps(source,{language:'pt-PT',scope:'island',repeats:2});
  assert.deepEqual(steps.filter(s=>s.kind==='audio').map(s=>[s.lang,s.text]),[
    ['pt-PT','Quero apanhar uma onda.'],['pt-PT','Quero apanhar uma onda.']
  ]);
  assert.deepEqual(buildPlaybackSteps([{id:'x',ru:'Привет',en:'Hello'}],{language:'pt-PT'}),[]);
  assert.throws(()=>buildPlaybackSteps(source,{language:'pt-BR'}), RangeError);
});
function fakeAudio() {
  return { src: '', currentTime: 0, playbackRate: 1, preservesPitch: false,
    preload: '', ended: false, error: null, onended: null, onerror: null, calls: [], pauses: 0,
    load() { this.currentTime = 0; this.ended = false; this.error = null; },
    play() { this.calls.push(this.src); return Promise.resolve(); },
    pause() { this.pauses++; },
  };
}
function endAudio(audio) { audio.ended = true; audio.onended?.(); }
function errorAudio(audio) { audio.error = {code: 4}; audio.onerror?.(); }
const PT = [
  {id:'a',ru:'Привет',target:'Olá',audio:{url:'/web/audio/pt-PT-kokoro-v1/a.mp3'}},
  {id:'b',ru:'До встречи',target:'Até logo',audio:{url:'/web/audio/pt-PT-kokoro-v1/b.mp3'}},
];

test('a Portuguese recording works with no Web Speech implementation', () => {
  const audio = fakeAudio(), h = harness({audio, noSpeech:true});
  assert.equal(h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:1}),0.65),true);
  assert.equal(audio.src,PT[0].audio.url);
  assert.equal(audio.playbackRate,0.65);
  assert.equal(audio.preservesPitch,true);
  endAudio(audio);
  assert.equal(h.completed.length,1);
  assert.equal(h.errors.length,0);
  assert.equal(h.speech.length,0);
});

test('Russian speech precedes pt-PT media; no Portuguese browser voice is called', () => {
  const audio=fakeAudio(), h=harness({audio});
  const steps=buildPlaybackSteps(PT,{language:'pt-PT',order:'ru-en',repeats:1,languagePauseMs:0});
  h.player.start(steps,1,{lang:'pt-BR',voiceURI:'br'});
  assert.equal(h.speech[0].lang,'ru-RU');
  assert.equal(h.speech[0].voice,undefined);
  assert.equal(audio.calls.length,0);
  h.speech[0].onend();
  assert.equal(audio.calls.length,1);
  assert.equal(h.speech.length,1);
  endAudio(audio);
  assert.equal(h.completed.length,1);
});

test('pt-PT repetitions and island progression retain inter-repeat pauses', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',scope:'island',repeats:2,pauseMs:500}));
  for (let i=0;i<3;i++) { endAudio(audio); assert.equal(h.tick(),500); }
  endAudio(audio);
  assert.deepEqual(audio.calls,[PT[0].audio.url,PT[0].audio.url,PT[1].audio.url,PT[1].audio.url]);
  assert.deepEqual(h.progress.map(s=>[s.index,s.repetition]),[[0,1],[0,2],[1,1],[1,2]]);
  assert.equal(h.completed.length,1);
  assert.equal(h.timers.size,0);
});

test('missing private audio fails before any Russian or Portuguese playback', () => {
  const h=harness({audio:fakeAudio()});
  const privatePhrase={id:'private',ru:'Личная фраза',target:'Privado'};
  assert.equal(h.player.start(buildPlaybackSteps([...PT,privatePhrase],{language:'pt-PT',scope:'island',order:'ru-en'})),false);
  assert.deepEqual(h.errors,['audio-missing']);
  assert.equal(h.speech.length,0);
  assert.equal(h.progress.length,0);
});

test('invalid/non-local audio URLs cannot call remote endpoints', () => {
  for (const url of ['https://example.com/a.mp3','//example.com/a.mp3','/web/audio/../secret/a.mp3','/api/tts?text=private','data:audio/mp3,abc']) {
    assert.equal(isLocalAudioUrl(url),false);
    const h=harness({audio:fakeAudio()});
    h.player.start(buildPlaybackSteps([{...PT[0],audio:{url}}],{language:'pt-PT'}));
    assert.deepEqual(h.errors,['audio-missing']);
  }
});

test('even legacy pt-PT speech steps cannot trigger browser fallback', () => {
  const h=harness({audio:fakeAudio()});
  const steps=buildPlaybackSteps(PT,{language:'pt-PT',repeats:1}).map(s=>({...s,kind:'speech'}));
  h.player.start(steps,1,{lang:'pt-BR',voiceURI:'br'});
  assert.equal(h.speech.length,0);
  assert.deepEqual(h.errors,['audio-missing']);
});

test('stop cancels MP3, watchdog, and stale media callbacks', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',scope:'island',repeats:1}));
  const ended=audio.onended, failed=audio.onerror;
  audio.currentTime=0.7;
  h.player.stop();
  ended(); failed();
  assert.equal(audio.currentTime,0);
  assert.equal(audio.onended,null);
  assert.equal(h.timers.size,0);
  assert.equal(audio.calls.length,1);
  assert.equal(h.errors.length,0);
  assert.equal(h.completed.length,0);
});

test('next/restart invalidates previous media completions', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:2}));
  const ended=audio.onended;
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',startIndex:1,repeats:1}));
  ended();
  assert.equal(audio.calls.length,2);
  assert.equal(audio.src,PT[1].audio.url);
  assert.equal(h.completed.length,0);
  endAudio(audio);
  assert.equal(h.completed.length,1);
});

test('failed MP3 stops the playlist instead of skipping or using TTS', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',scope:'island',repeats:1}));
  errorAudio(audio);
  assert.equal(h.player.active,false);
  assert.deepEqual(h.errors,['audio-failed']);
  assert.equal(audio.calls.length,1);
  assert.equal(h.speech.length,0);
});

test('rejected media play is an explicit error', async () => {
  const audio=fakeAudio(); audio.play=()=>Promise.reject(new Error('NotAllowedError'));
  const h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:1}));
  await Promise.resolve();
  assert.deepEqual(h.errors,['audio-failed']);
  assert.equal(h.player.active,false);
});

test('a stale rejected play promise cannot cancel the next item', async () => {
  const audio=fakeAudio(); let reject;
  audio.play=()=>new Promise((resolve,r)=>{reject=r;});
  const h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',scope:'island',repeats:1,pauseMs:0}));
  const oldReject=reject;
  endAudio(audio);
  oldReject(new Error('old play aborted'));
  await Promise.resolve();
  assert.equal(h.player.active,true);
  assert.equal(h.errors.length,0);
  h.player.stop();
});

test('pause/resume media retains position and does not create another repetition', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:1}));
  audio.currentTime=0.6;
  assert.equal(h.player.pause(),true);
  assert.equal(h.player.paused,true);
  const oldCalls=audio.calls.length;
  for(let i=0;i<50;i++) h.tick();
  assert.equal(h.player.active,true);
  assert.equal(h.errors.length,0);
  assert.equal(h.player.resume(),true);
  assert.equal(audio.currentTime,0.6);
  assert.equal(audio.calls.length,oldCalls+1);
  assert.equal(h.progress.length,1);
  endAudio(audio);
  assert.equal(h.completed.length,1);
});

test('pause/resume preserves remaining configured delay', () => {
  const originalNow=Date.now; let now=1000; Date.now=()=>now;
  try {
    const audio=fakeAudio(),h=harness({audio});
    h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:2,pauseMs:1000}));
    endAudio(audio); now+=250;
    h.player.pause();
    assert.equal(h.timers.size,0);
    now+=10000; h.player.resume();
    assert.equal(h.tick(),750);
    assert.equal(audio.calls.length,2);
    h.player.stop();
  } finally { Date.now=originalNow; }
});

test('media watchdog fails a stalled decoder without silently advancing', () => {
  const audio=fakeAudio(),h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:2}));
  while(h.player.active) h.tick();
  assert.deepEqual(h.errors,['audio-failed']);
  assert.equal(audio.calls.length,1);
});

test('Russian pre-reading without SpeechSynthesis fails clearly, audio-only still works', () => {
  const audio=fakeAudio(),h=harness({audio,noSpeech:true});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',order:'ru-en',repeats:1}));
  assert.deepEqual(h.errors,['unsupported']);
  assert.equal(audio.calls.length,0);
  assert.equal(h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:1})),true);
  h.player.stop();
});

test('pausing Russian pre-reading suspends watchdog inference and keeps the queue', () => {
  const originalNow=Date.now; let now=1000; Date.now=()=>now;
  try {
    const timers=new Map(),calls=[]; let nextId=0, pauses=0, resumes=0;
    const audio=fakeAudio();
    const synth={ speaking:true, pending:false, cancel(){},
      speak(u){calls.push(u);u.onstart?.();},
      pause(){pauses++;this.speaking=false;},resume(){resumes++;this.speaking=true;},
    };
    class Utterance { constructor(text){this.text=text;} }
    const player=new SpeechSequence({audio,synthesis:synth,Utterance,
      schedule(fn){const id=++nextId;timers.set(id,fn);return id;},unschedule(id){timers.delete(id);},
    });
    const tick=()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);fn();};
    player.start(buildPlaybackSteps(PT,{language:'pt-PT',order:'ru-en',repeats:1,languagePauseMs:0}));
    player.pause();now+=120000;tick();tick();
    assert.equal(audio.calls.length,0);
    assert.equal(player.active,true);
    player.resume();tick();
    assert.equal(pauses,1);assert.equal(resumes,1);
    assert.equal(calls.length,1);
    assert.equal(audio.calls.length,0);
    calls[0].onend();
    assert.equal(audio.calls.length,1);
    player.stop();
  } finally {Date.now=originalNow;}
});


test('queued DOM ended from previous source cannot finish a newly started item', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:1}));
  // Dispatch resolves the current property listener, unlike saved callback refs.
  const dispatchOldEnded=()=>audio.onended?.();
  audio.ended=true;
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',startIndex:1,repeats:1}));
  assert.equal(audio.ended,false); // load() reset current resource state.
  dispatchOldEnded();
  assert.equal(h.player.active,true);
  assert.equal(h.completed.length,0);
  assert.equal(audio.calls.length,2);
  endAudio(audio);
  assert.equal(h.completed.length,1);
});

test('queued DOM error from previous source is ignored, current media error stops', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:1}));
  const dispatchOldError=()=>audio.onerror?.();
  audio.error={code:4};
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',startIndex:1,repeats:1}));
  assert.equal(audio.error,null);
  dispatchOldError();
  assert.equal(h.player.active,true);
  assert.equal(h.errors.length,0);
  errorAudio(audio); // Genuine current-file 404/unsupported-media error.
  assert.equal(h.player.active,false);
  assert.deepEqual(h.errors,['audio-failed']);
});

test('duplicate queued ended within same playlist cannot skip a repetition', () => {
  const audio=fakeAudio(), h=harness({audio});
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:2,pauseMs:0}));
  endAudio(audio);
  assert.equal(audio.calls.length,2);
  assert.equal(audio.ended,false);
  audio.onended?.(); // Old duplicate event reaches the NEW repetition handler.
  assert.equal(h.completed.length,0);
  assert.equal(h.player.active,true);
  endAudio(audio);
  assert.equal(h.completed.length,1);
});

test('media load exceptions stop explicitly without speech fallback', () => {
  const audio=fakeAudio(), h=harness({audio});
  audio.load=()=>{throw new Error('Cannot load media');};
  h.player.start(buildPlaybackSteps(PT,{language:'pt-PT',repeats:1}));
  assert.equal(h.player.active,false);
  assert.deepEqual(h.errors,['audio-failed']);
  assert.equal(h.speech.length,0);
});


test('pre-recorded English and Russian audio both play with no Web Speech steps', () => {
  const uuid = '123e4567-e89b-12d3-a456-426614174000';
  const phrases = [{
    id: uuid, ru: 'Привет', target: 'Hello',
    audio: { url: '/api/voice-media/af_heart/' + uuid + '.mp3' },
    ru_audio: { url: '/api/voice-media/sveta/' + uuid + '.mp3' },
  }];
  const steps = buildPlaybackSteps(phrases, {
    language: 'en-US', order: 'ru-en', repeats: 1, pauseMs: 0,
    audioRequired: true, ruAudioRequired: true,
  });
  assert.deepEqual(steps.map(s => s.kind), ['audio', 'pause', 'audio']);
  assert.deepEqual(steps.filter(s => s.kind === 'audio').map(s => s.lang), ['ru-RU', 'en-US']);
  assert.ok(steps.filter(s => s.kind === 'audio').every(s => isLocalAudioUrl(s.url)));
});

test('selected but missing Kokoro voice fails closed without browser speech fallback', () => {
  const uuid = '123e4567-e89b-12d3-a456-426614174000';
  const phrases = [{ id: uuid, ru: 'Привет', target: 'Hello' }];
  const steps = buildPlaybackSteps(phrases, { audioRequired: true, language: 'en-US' });
  assert.equal(steps[0].kind, 'audio');
  assert.equal(steps[0].url, undefined);
  const h = harness();
  assert.equal(h.player.start(steps), false);
  assert.deepEqual(h.errors, ['audio-missing']);
  assert.equal(h.speech.length, 0);
});

test('voice routes stay strictly same-origin and reject path traversal', () => {
  const id = '123e4567-e89b-12d3-a456-426614174000';
  assert.equal(isLocalAudioUrl('/api/voice-media/bf_emma/' + id + '.mp3'), true);
  assert.equal(isLocalAudioUrl('https://server.example/audio.mp3'), false);
  assert.equal(isLocalAudioUrl('/api/voice-media/../../etc/passwd'), false);
  assert.equal(isLocalAudioUrl('/api/voice-media/sveta/../' + id + '.mp3'), false);
});
