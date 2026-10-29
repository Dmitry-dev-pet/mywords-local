import { createApp, ref, computed, onMounted, onBeforeUnmount, watch } from '/web/vendor/vue.esm-browser.prod.js';
import { buildPlaybackSteps, SpeechSequence } from '/web/audio-sequence.mjs';

const SETTINGS_KEY = 'mywords.local.practice.v1';
const LANGUAGE_KEY = 'mywords.local.target-language.v1';
const VOICES_KEY = 'mywords.local.voices.v1';
const KOKORO_KEY = 'mywords.local.kokoro.v1';
function loadKokoroPreferences() {
  try {
    const stored = JSON.parse(localStorage.getItem(KOKORO_KEY) || '{}');
    return { en: typeof stored.en === 'string' ? stored.en : '',
             ru: typeof stored.ru === 'string' ? stored.ru : '' };
  } catch { return { en: '', ru: '' }; }
}
function loadLanguage() {
  try { return localStorage.getItem(LANGUAGE_KEY) === 'pt-PT' ? 'pt-PT' : 'en-US'; }
  catch { return 'en-US'; }
}
function loadVoicePreferences() {
  try {
    const stored = JSON.parse(localStorage.getItem(VOICES_KEY) || '{}');
    return {
      'en-US': typeof stored['en-US'] === 'string' ? stored['en-US'] : '',
      'pt-PT': typeof stored['pt-PT'] === 'string' ? stored['pt-PT'] : '',
    };
  } catch { return { 'en-US': '', 'pt-PT': '' }; }
}

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
    const selectedLanguage = ref(loadLanguage());
    const languageName = computed(() => selectedLanguage.value === 'pt-PT' ? 'Português (Portugal)' : 'English');
    const voicePreferences = ref(loadVoicePreferences());
    const voices = ref([]);
    const voiceCatalog = ref([]);
    const initialKokoro = loadKokoroPreferences();
    const selectedAudioVoice = ref(initialKokoro.en);
    const selectedRuVoice = ref(initialKokoro.ru);
    const uploadedVoiceFile = ref(null);
    const voicePackPreview = ref(null);
    const openrailAccepted = ref(false);
    const voicePackBusy = ref(false);
    const voicePackMessage = ref('');
    const englishKokoroVoices = computed(() => voiceCatalog.value.filter(v => v.locale.startsWith('en-')));
    const russianKokoroVoices = computed(() => voiceCatalog.value.filter(v => v.locale === 'ru-RU'));
    const matchingVoices = computed(() => voices.value.filter(v =>
      v.lang?.toLowerCase().replace('_', '-') === selectedLanguage.value.toLowerCase()));
    const preferredVoice = computed(() => matchingVoices.value.find(
      v => v.voiceURI === voicePreferences.value[selectedLanguage.value]) || matchingVoices.value[0] || null);
    const starterPacks = ref([]);
    const audioPack = ref(null);
    const audioPackError = ref(false);
    const audioPackState = computed(() => ({
      ready: 'Пакет готов',
      'missing-package': 'Пакет отсутствует',
      'invalid-package': 'Пакет не прошёл проверку',
      'incomplete-package': 'Часть файлов отсутствует или повреждена',
    }[audioPack.value?.status] || 'Статус пакета неизвестен'));
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
    const paused = ref(false);
    const audioStatus = ref('');
    const settings = ref(loadSettings());
    const newIsland = ref('');
    const newRu = ref('');
    const newTarget = ref('');
    const editingPhraseId = ref(null);
    const translationDraft = ref('');
    const selectedIsland = computed(() => islands.value.find(x => x.id === selectedId.value));
    const availablePhrases = computed(() => phrases.value.filter(x => !!x.target));
    const currentIndex = computed(() => availablePhrases.value.findIndex(x => x.id === currentId.value));
    const currentPhrase = computed(() => availablePhrases.value[currentIndex.value] || null);
    const practiced = computed(() => availablePhrases.value.filter(x => x.review_count > 0).length);
    const mastered = computed(() => availablePhrases.value.filter(x => x.mastery === 2 && x.review_count > 0).length);
    const scoreLabel = computed(() => {
      const phrase = currentPhrase.value;
      if (!phrase || !phrase.review_count) return 'Ещё не оценено';
      return ['Не вспомнил', 'Нужно повторить', 'Выучил'][phrase.mastery];
    });

    let requestSeq = 0;
    let advancingFromPlayback = false;

    const player = new SpeechSequence({
      audio: typeof window.Audio === 'function' ? new window.Audio() : undefined,
      synthesis: window.speechSynthesis,
      Utterance: window.SpeechSynthesisUtterance,
      onState: active => { playing.value = active; },
      onPause: value => { paused.value = value; },
      onProgress: step => {
        const phrase = availablePhrases.value[step.index];
        if (!phrase || phrase.id !== step.phraseId) {
          stopAudio();
          return;
        }
        if (currentId.value !== phrase.id) {
          advancingFromPlayback = true;
          try { currentId.value = phrase.id; }
          finally { advancingFromPlayback = false; }
        }
        const language = step.lang === 'ru-RU' ? 'Русский' : step.lang === 'pt-PT' ? 'Португальский' : 'Английский';
        audioStatus.value = 'Фраза ' + (step.index + 1) + '/' + availablePhrases.value.length
          + ' · ' + language + ' · повтор ' + step.repetition + '/' + step.repeats;
      },
      onFinish: () => { audioStatus.value = 'Воспроизведение завершено'; },
      onRecovery: () => { audioStatus.value = 'Браузер пропустил событие завершения · продолжаем'; },
      onError: code => {
        const messages = {
          unsupported: 'Синтез речи не поддерживается. Для русского предварительного чтения нужен системный русский голос; его можно выключить в настройках.',
          'audio-missing': 'Для выбранного языка или голоса нет подходящей локальной записи. Установи пакет Kokoro или выбери другой установленный голос. Текстовый Recall доступен; никаких скрытых TTS-запросов.',
          'audio-unsupported': 'Браузер не поддерживает воспроизведение аудиофайлов.',
          'audio-failed': 'Не удалось проиграть локальную запись pt-PT. Проверь аудиопакет и звук, затем нажми ▶ ещё раз. Подмена голосом pt-BR отключена.',
          'speech-stalled': 'Синтезатор речи не начал чтение. Проверь голосовой движок Android и попробуй снова.',
        };
        error.value = messages[code] || 'Браузер не смог озвучить фразу. Проверь установленные голоса и звук.';
      },
    });

    async function refreshAudioPack() {
      try {
        audioPack.value = await api('/api/audio-pack');
        audioPackError.value = false;
      } catch {
        // Pack diagnostics must not prevent English or text-only practice.
        audioPack.value = null;
        audioPackError.value = true;
      }
    }
    async function refreshVoiceCatalog() {
      const payload = await api('/api/voice-packs');
      voiceCatalog.value = payload.voices || [];
      if (!selectedAudioVoice.value) {
        selectedAudioVoice.value = englishKokoroVoices.value.find(v => v.installed)?.id || '';
      }
      if (!selectedRuVoice.value) {
        selectedRuVoice.value = russianKokoroVoices.value.find(v => v.installed)?.id || '';
      }
    }
    function selectVoiceFile(event) {
      uploadedVoiceFile.value = event.target.files?.[0] || null;
      voicePackPreview.value = null;
      openrailAccepted.value = false;
      voicePackMessage.value = '';
    }
    async function voicePackAction(action) {
      if (!uploadedVoiceFile.value || voicePackBusy.value) return;
      voicePackBusy.value = true;
      voicePackMessage.value = '';
      error.value = '';
      try {
        const form = new FormData();
        form.append('pack', uploadedVoiceFile.value, uploadedVoiceFile.value.name);
        if (action === 'install' && openrailAccepted.value) form.append('accepted_openrail', 'true');
        const response = await fetch('/api/voice-packs/' + action, { method: 'POST', body: form });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Ошибка импорта ZIP');
        if (action === 'preview') {
          voicePackPreview.value = result;
          voicePackMessage.value = 'Проверен полный пакет ' + result.voice_id + ': ' + result.files + ' записей.';
        } else {
          voicePackPreview.value = null;
          voicePackMessage.value = result.changed ? 'Голос установлен: ' + result.voice_id : 'Пакет уже установлен без изменений';
          await refreshVoiceCatalog();
          await refresh();
        }
      } catch (e) {
        voicePackPreview.value = null;
        error.value = e.message || String(e);
      } finally {
        voicePackBusy.value = false;
      }
    }
    function refreshVoices() {
      try { voices.value = window.speechSynthesis?.getVoices?.() || []; }
      catch { voices.value = []; }
    }
    function stopAudio() {
      player.stop();
      playing.value = false;
      paused.value = false;
      audioStatus.value = '';
    }

    function togglePause() {
      if (paused.value) player.resume();
      else if (!player.pause()) error.value = 'Этот голос не поддерживает паузу. Используй «Остановить» и запусти фразу заново.';
    }

    // A single card, or the remaining cards of an island. No review writes.
    function play(scope = 'phrase') {
      stopAudio();
      error.value = '';
      const steps = buildPlaybackSteps(availablePhrases.value, {
        startIndex: currentIndex.value, scope, ...settings.value,
        language: selectedLanguage.value,
        audioRequired: selectedLanguage.value === 'en-US' && !!selectedAudioVoice.value,
        ruAudioRequired: settings.value.order === 'ru-en' && !!selectedRuVoice.value,
      });
      player.start(steps, settings.value.rate, preferredVoice.value);
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
      const language = selectedLanguage.value;
      const voiceQuery = '&voice=' + encodeURIComponent(language === 'en-US' ? selectedAudioVoice.value : '')
        + '&ru_voice=' + encodeURIComponent(selectedRuVoice.value);
      const freshPhrases = id ? await api(`/api/islands/${id}/phrases?language=${encodeURIComponent(language)}` + voiceQuery) : [];
      if (seq !== requestSeq || language !== selectedLanguage.value) return;
      islands.value = freshIslands;
      selectedId.value = id;
      phrases.value = freshPhrases;
      if (!freshPhrases.some(x => x.id === currentId.value && !!x.target)) {
        currentId.value = freshPhrases.find(x => !!x.target)?.id || null;
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
      refreshAudioPack();
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
    function starterText(phrase) {
      return selectedLanguage.value === 'pt-PT' ? (phrase['pt-PT'] || 'Перевод пока не добавлен') : phrase.en;
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
        starterMessage.value = result.added || result.added_translations
          ? 'Добавлено ' + result.added + ' новых мыслей и ' + result.added_translations + ' языковых вариантов. Оценки сохранены.'
          : 'Все доступные варианты уже добавлены. Твои оценки не изменились.';
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
          method: 'POST', body: JSON.stringify({
            ru: newRu.value, target: newTarget.value, language: selectedLanguage.value,
          }),
        });
        newRu.value = ''; newTarget.value = '';
        await refresh();
        currentId.value = phrase.id;
        tab.value = 'practice';
      });
    }
    function startTranslation(id) {
      editingPhraseId.value = id;
      translationDraft.value = '';
    }
    function saveTranslation() {
      const phraseId = editingPhraseId.value;
      run(async () => {
        await api(`/api/phrases/${phraseId}/translations`, {
          method: 'POST', body: JSON.stringify({
            language: selectedLanguage.value, target: translationDraft.value,
          }),
        });
        editingPhraseId.value = null;
        translationDraft.value = '';
        await refresh();
        currentId.value = phraseId;
      });
    }
    function mark(mastery) {
      const phrase = currentPhrase.value;
      if (!phrase) return;
      run(async () => {
        const updated = await api(`/api/phrases/${phrase.id}/review`, {
          method: 'PATCH', body: JSON.stringify({ mastery, language: selectedLanguage.value }),
        });
        // Do not jump the card: the saved score remains visible until Next.
        const row = phrases.value.find(x => x.id === phrase.id);
        if (row) { row.mastery = updated.mastery; row.review_count = updated.review_count; }
      });
    }
    function go(delta) {
      stopAudio();
      if (!availablePhrases.value.length) return;
      const index = currentIndex.value < 0 ? 0 : currentIndex.value;
      const next = Math.min(availablePhrases.value.length - 1, Math.max(0, index + delta));
      currentId.value = availablePhrases.value[next].id;
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
    watch(selectedLanguage, language => {
      try { localStorage.setItem(LANGUAGE_KEY, language); } catch { /* private storage */ }
      stopAudio();
      currentId.value = null;
      editingPhraseId.value = null;
      translationDraft.value = '';
      run(() => refresh());
    });
    watch([selectedAudioVoice, selectedRuVoice], ([en, ru]) => {
      stopAudio();
      try { localStorage.setItem(KOKORO_KEY, JSON.stringify({ en, ru })); } catch { /* storage disabled */ }
      run(() => refresh());
    });
    watch(voicePreferences, prefs => {
      stopAudio();
      try { localStorage.setItem(VOICES_KEY, JSON.stringify(prefs)); } catch { /* storage */ }
    }, { deep: true });
    watch(settings, (value) => {
      stopAudio();
      try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(value)); } catch { /* storage may be disabled */ }
    }, { deep: true });
    onMounted(() => {
      window.addEventListener('keydown', onKeyDown);
      window.addEventListener('pagehide', stopAudio);
      refreshVoices();
      refreshAudioPack();
      window.speechSynthesis?.addEventListener?.('voiceschanged', refreshVoices);
      run(async () => {
        await refreshVoiceCatalog();
        await refresh();
        starterPacks.value = await api('/api/starter-islands');
        if (!islands.value.length) tab.value = 'library';
      });
    });
    onBeforeUnmount(() => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('pagehide', stopAudio);
      window.speechSynthesis?.removeEventListener?.('voiceschanged', refreshVoices);
      stopAudio();
    });

    return { ready, error, islands, selectedLanguage, languageName, matchingVoices,
      voicePreferences, refreshVoices, starterPacks, audioPack, audioPackError, audioPackState, importingPresetId, starterMessage,
      voiceCatalog, englishKokoroVoices, russianKokoroVoices, selectedAudioVoice, selectedRuVoice,
      uploadedVoiceFile, voicePackPreview, voicePackBusy, voicePackMessage, openrailAccepted,
      selectVoiceFile, voicePackAction,
      starterText, starterInstalled, importPreset, selectedId, selectedIsland, phrases, availablePhrases,
      currentPhrase, currentIndex, practiced, mastered, scoreLabel,
      tab, mode, revealed, playing, paused, togglePause, audioStatus, settings, navOpen, settingsOpen, settingsTab,
      newIsland, newRu, newTarget, editingPhraseId, translationDraft, startTranslation,
      saveTranslation, selectIsland, createIsland, addPhrase,
      mark, go, practicePhrase, play, stopAudio, openCatalog, openEditor, showPractice,
      openIsland, openSettings, toggleDualAudio };
  },
}).mount('#app');
