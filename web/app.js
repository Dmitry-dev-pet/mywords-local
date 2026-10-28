import { createApp, ref, computed, onMounted, onBeforeUnmount, watch } from '/web/vendor/vue.esm-browser.prod.js';
import { buildPlaybackSteps, SpeechSequence } from '/web/audio-sequence.mjs';

const SETTINGS_KEY = 'mywords.local.practice.v1';
const DEFAULT_SETTINGS = Object.freeze({ rate: 0.85, repeats: 2, pauseMs: 1000, order: 'en', languagePauseMs: 500 });

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    return {
      rate: Number.isFinite(saved.rate) && saved.rate >= 0.5 && saved.rate <= 1.5 ? saved.rate : DEFAULT_SETTINGS.rate,
      repeats: [1, 2, 3, 4, 5].includes(saved.repeats) ? saved.repeats : DEFAULT_SETTINGS.repeats,
      pauseMs: [0, 500, 1000, 2000, 3000].includes(saved.pauseMs) ? saved.pauseMs : DEFAULT_SETTINGS.pauseMs,
      order: ['en', 'ru-en'].includes(saved.order) ? saved.order : DEFAULT_SETTINGS.order,
      languagePauseMs: [0, 500, 1000, 2000].includes(saved.languagePauseMs) ? saved.languagePauseMs : DEFAULT_SETTINGS.languagePauseMs,
    };
  } catch { return { ...DEFAULT_SETTINGS }; }
}

async function api(path, init) {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

createApp({
  setup() {
    const ready = ref(true);
    const error = ref('');
    const islands = ref([]);
    const starterPacks = ref([]);
    const importingPresetId = ref(null);
    const starterMessage = ref('');
    const selectedId = ref(null);
    const phrases = ref([]);
    const currentId = ref(null);
    const tab = ref('practice');
    const navOpen = ref(false);
    const settingsOpen = ref(false);
    const settingsTab = ref('sound');
    const mode = ref('focus');
    const revealed = ref(false);
    const playing = ref(false);
    const audioStatus = ref('');
    const settings = ref(loadSettings());
    const newIsland = ref('');
    const newRu = ref('');
    const newEn = ref('');
    const selectedIsland = computed(() => islands.value.find(x => x.id === selectedId.value));
    const currentIndex = computed(() => phrases.value.findIndex(x => x.id === currentId.value));
    const currentPhrase = computed(() => phrases.value[currentIndex.value] || null);
    const practiced = computed(() => phrases.value.filter(x => x.review_count > 0).length);
    const mastered = computed(() => phrases.value.filter(x => x.mastery === 2 && x.review_count > 0).length);
    const scoreLabel = computed(() => {
      const phrase = currentPhrase.value;
      if (!phrase || !phrase.review_count) return 'Ещё не оценено';
      return ['Не вспомнил', 'Нужно повторить', 'Выучил'][phrase.mastery];
    });

    let requestSeq = 0;
    let advancingFromPlayback = false;

    const player = new SpeechSequence({
      synthesis: window.speechSynthesis,
      Utterance: window.SpeechSynthesisUtterance,
      onState: active => { playing.value = active; },
      onProgress: step => {
        const phrase = phrases.value[step.index];
        if (!phrase || phrase.id !== step.phraseId) {
          stopAudio();
          return;
        }
        if (currentId.value !== phrase.id) {
          advancingFromPlayback = true;
          try { currentId.value = phrase.id; }
          finally { advancingFromPlayback = false; }
        }
        const language = step.lang === 'ru-RU' ? 'Русский' : 'Английский';
        audioStatus.value = 'Фраза ' + (step.index + 1) + '/' + phrases.value.length
          + ' · ' + language + ' · повтор ' + step.repetition + '/' + step.repeats;
      },
      onFinish: () => { audioStatus.value = 'Воспроизведение завершено'; },
      onRecovery: () => { audioStatus.value = 'Браузер пропустил событие завершения · продолжаем'; },
      onError: code => {
        error.value = code === 'unsupported'
          ? 'Озвучивание не поддерживается в этом браузере.'
          : code === 'speech-stalled'
            ? 'Синтезатор речи не начал чтение. Проверь голосовой движок Android и попробуй снова.'
            : 'Браузер не смог озвучить фразу. Проверь установленные голоса и звук.';
      },
    });

    function stopAudio() {
      player.stop();
      playing.value = false;
      audioStatus.value = '';
    }

    // A single card, or the remaining cards of an island. No review writes.
    function play(scope = 'phrase') {
      stopAudio();
      error.value = '';
      const steps = buildPlaybackSteps(phrases.value, {
        startIndex: currentIndex.value, scope, ...settings.value,
      });
      player.start(steps, settings.value.rate);
    }

    async function run(work) {
      error.value = '';
      try { await work(); }
      catch (e) { error.value = e.message || String(e); }
    }
    async function refresh(preferredIsland = selectedId.value) {
      const seq = ++requestSeq;
      const freshIslands = await api('/api/islands');
      const id = freshIslands.some(x => x.id === preferredIsland)
        ? preferredIsland : freshIslands[0]?.id || null;
      const freshPhrases = id ? await api(`/api/islands/${id}/phrases`) : [];
      if (seq !== requestSeq) return;
      islands.value = freshIslands;
      selectedId.value = id;
      phrases.value = freshPhrases;
      if (!freshPhrases.some(x => x.id === currentId.value)) {
        currentId.value = freshPhrases[0]?.id || null;
      }
    }
    function openCatalog() {
      stopAudio();
      settingsOpen.value = false;
      navOpen.value = false;
      tab.value = 'library';
    }
    function openEditor() {
      stopAudio();
      settingsOpen.value = false;
      navOpen.value = false;
      tab.value = selectedId.value ? 'editor' : 'library';
    }
    function showPractice() {
      stopAudio();
      settingsOpen.value = false;
      navOpen.value = false;
      tab.value = selectedId.value ? 'practice' : 'library';
    }
    function openIsland(id) {
      selectIsland(id);
      tab.value = 'practice';
      settingsOpen.value = false;
      navOpen.value = false;
    }
    function openSettings(section = 'sound') {
      settingsTab.value = section;
      settingsOpen.value = true;
    }
    function toggleDualAudio() {
      settings.value.order = settings.value.order === 'ru-en' ? 'en' : 'ru-en';
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') {
        settingsOpen.value = false;
        navOpen.value = false;
        return;
      }
      if (settingsOpen.value || tab.value !== 'practice') return;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
      if (event.key === 'ArrowLeft') go(-1);
      else if (event.key === 'ArrowRight') go(1);
    }
    function selectIsland(id) {
      stopAudio();
      currentId.value = null;
      selectedId.value = id;
      phrases.value = [];
      run(() => refresh(id));
    }
    function starterInstalled(pack) {
      return islands.value.some(island => island.id === pack.island_id);
    }
    async function importPreset(packId) {
      if (importingPresetId.value !== null) return;
      importingPresetId.value = packId;
      starterMessage.value = '';
      error.value = '';
      try {
        const result = await api('/api/starter-islands/' + encodeURIComponent(packId) + '/import', {
          method: 'POST',
        });
        await refresh(result.island_id);
        starterMessage.value = result.added
          ? 'Добавлено ' + result.added + ' фраз. Теперь остров можно открыть и тренировать.'
          : 'Этот набор уже добавлен. Твои оценки не изменились.';
      } catch (e) {
        error.value = e.message || String(e);
      } finally {
        importingPresetId.value = null;
      }
    }
    function createIsland() {
      run(async () => {
        const island = await api('/api/islands', {
          method: 'POST', body: JSON.stringify({ title: newIsland.value }),
        });
        newIsland.value = '';
        selectedId.value = island.id;
        currentId.value = null;
        tab.value = 'editor';
        await refresh(island.id);
      });
    }
    function addPhrase() {
      run(async () => {
        const phrase = await api(`/api/islands/${selectedId.value}/phrases`, {
          method: 'POST', body: JSON.stringify({ ru: newRu.value, en: newEn.value }),
        });
        newRu.value = ''; newEn.value = '';
        await refresh();
        currentId.value = phrase.id;
        tab.value = 'practice';
      });
    }
    function mark(mastery) {
      const phrase = currentPhrase.value;
      if (!phrase) return;
      run(async () => {
        const updated = await api(`/api/phrases/${phrase.id}/review`, {
          method: 'PATCH', body: JSON.stringify({ mastery }),
        });
        // Do not jump the card: the saved score remains visible until Next.
        const row = phrases.value.find(x => x.id === phrase.id);
        if (row) { row.mastery = updated.mastery; row.review_count = updated.review_count; }
      });
    }
    function go(delta) {
      if (!phrases.value.length) return;
      const index = currentIndex.value < 0 ? 0 : currentIndex.value;
      const next = Math.min(phrases.value.length - 1, Math.max(0, index + delta));
      currentId.value = phrases.value[next].id;
    }
    function practicePhrase(id) {
      currentId.value = id;
      tab.value = 'practice';
    }

    watch(currentId, () => {
      revealed.value = false;
      if (!advancingFromPlayback) stopAudio();
    }, { flush: 'sync' });
    watch([selectedId, mode, tab], () => { stopAudio(); revealed.value = false; });
    watch(settings, (value) => {
      stopAudio();
      try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(value)); } catch { /* storage may be disabled */ }
    }, { deep: true });
    onMounted(() => {
      window.addEventListener('keydown', onKeyDown);
      run(async () => {
        await refresh();
        starterPacks.value = await api('/api/starter-islands');
        if (!islands.value.length) tab.value = 'library';
      });
    });
    onBeforeUnmount(() => {
      window.removeEventListener('keydown', onKeyDown);
      stopAudio();
    });

    return { ready, error, islands, starterPacks, importingPresetId, starterMessage,
      starterInstalled, importPreset, selectedId, selectedIsland, phrases,
      currentPhrase, currentIndex, practiced, mastered, scoreLabel,
      tab, mode, revealed, playing, audioStatus, settings, navOpen, settingsOpen, settingsTab,
      newIsland, newRu, newEn, selectIsland, createIsland, addPhrase,
      mark, go, practicePhrase, play, stopAudio, openCatalog, openEditor, showPractice,
      openIsland, openSettings, toggleDualAudio };
  },
}).mount('#app');
