"""Local-only Flask API and static frontend. Not a production server."""
import os
import platform
import sqlite3
from pathlib import Path
from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from store import Store, LANGUAGES
from starter_packs import list_starter_packs, find_starter_pack
from audio_pack import AudioCatalog
from voice_library import VoicePackLibrary, InvalidVoicePack, MAX_ZIP_BYTES, INSTALLED_ROOT, BUNDLED_ROOT

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'


def create_app(database=None, voice_root=None, bundle_root=None):
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = MAX_ZIP_BYTES + 1024 * 1024
    store = Store(database or os.environ.get('MYWORDS_TEST_DB') or (ROOT / 'local.sqlite3'))
    audio_catalog = AudioCatalog()
    # Production automatically discovers versioned bundled ZIPs after a normal
    # app checkout/update. Isolated tests do not read the user's voice library.
    isolated = (database is not None or bool(os.environ.get('MYWORDS_TEST_DB'))
                or voice_root is not None or bool(os.environ.get('MYWORDS_TEST_VOICE_ROOT')))
    active_bundles = (bundle_root if bundle_root is not None else
                      os.environ.get('MYWORDS_TEST_BUNDLE_ROOT') or
                      (None if isolated else BUNDLED_ROOT))
    voice_library = VoicePackLibrary(
        root=voice_root if voice_root is not None
        else os.environ.get('MYWORDS_TEST_VOICE_ROOT', INSTALLED_ROOT),
        pt_catalog=audio_catalog, bundled_root=active_bundles)

    @app.errorhandler(Exception)
    def unhandled(error):
        if isinstance(error, HTTPException):
            return error
        # Never return exception text, which might contain personal lesson data.
        app.logger.error('Unhandled request failure: %s', type(error).__name__)
        return jsonify(error='Внутренняя ошибка сервера'), 500

    @app.get('/')
    def home():
        return send_from_directory(WEB, 'index.html')

    @app.get('/web/<path:filename>')
    def static_files(filename):
        return send_from_directory(WEB, filename)

    @app.get('/api/health')
    def health():
        return jsonify(ok=True, python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                       vue_ready=(WEB / 'vendor/vue.esm-browser.prod.js').is_file(),
                       storage='local', languages=list(LANGUAGES))

    @app.get('/api/starter-islands')
    def starter_islands():
        # Public catalog only; no SQLite writes or external requests.
        return jsonify(list_starter_packs())

    @app.get('/api/audio-pack')
    def audio_pack_status():
        # Read-only public package health; never exposes local study text.
        return jsonify(audio_catalog.status())


    @app.get('/api/voice-packs')
    def voice_packs():
        # Local catalog; only verified installed packs have usable audio URLs.
        return jsonify(voices=voice_library.voices())

    def uploaded_voice_zip():
        part = request.files.get('pack')
        if part is None:
            raise InvalidVoicePack('Выбери ZIP-файл с аудиопакетом')
        content = part.stream.read(MAX_ZIP_BYTES + 1)
        if len(content) > MAX_ZIP_BYTES:
            raise InvalidVoicePack('ZIP превышает лимит 32 МБ')
        return content

    @app.post('/api/voice-packs/preview')
    def voice_pack_preview():
        try:
            return jsonify(voice_library.preview(uploaded_voice_zip()))
        except InvalidVoicePack as error:
            return jsonify(error=str(error)), 400

    @app.post('/api/voice-packs/install')
    def voice_pack_install():
        try:
            return jsonify(voice_library.install(
                uploaded_voice_zip(), accepted_openrail=request.form.get('accepted_openrail') == 'true'))
        except InvalidVoicePack as error:
            return jsonify(error=str(error)), 409 if 'уже' in str(error).lower() else 400

    @app.get('/api/voice-media/<voice_id>/<phrase_id>.mp3')
    def voice_media(voice_id, phrase_id):
        # Never serve arbitrary local files; check manifest identity and SHA256.
        payload = voice_library.media(voice_id, phrase_id)
        if payload is None:
            return jsonify(error='Запись недоступна или повреждена'), 404
        response = Response(payload, mimetype='audio/mpeg')
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.post('/api/starter-islands/<pack_id>/import')
    def import_starter_island(pack_id):
        pack = find_starter_pack(pack_id)
        if pack is None:
            return jsonify(error='Готовый остров не найден'), 404
        result = store.import_starter_island(pack)
        return jsonify(result), (201 if result['created'] else 200)

    @app.get('/api/islands')
    def islands():
        return jsonify(store.islands())

    @app.post('/api/islands')
    def add_island():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Ожидался JSON-объект'), 400
        try:
            return jsonify(store.add_island(data.get('title'))), 201
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get('/api/islands/<island_id>/phrases')
    def phrases(island_id):
        language = request.args.get('language', 'en-US')
        try:
            rows = store.phrases(island_id, language)
            target_voice = request.args.get('voice', '')
            russian_voice = request.args.get('ru_voice', '')
            for row in rows:
                if language == 'pt-PT':
                    row['audio'] = audio_catalog.for_phrase(row['id'], row.get('target'), language)
                else:
                    row['audio'] = voice_library.for_phrase(row['id'], row.get('target'),
                                                            language, target_voice)
                row['ru_audio'] = voice_library.for_phrase(row['id'], row.get('ru'),
                                                           'ru-RU', russian_voice)
            return jsonify(rows)
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post('/api/islands/<island_id>/phrases')
    def add_phrase(island_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Ожидался JSON-объект'), 400
        try:
            target = data.get('target') if 'target' in data else data.get('en')
            return jsonify(store.add_phrase(island_id, data.get('ru'), target,
                                            data.get('language', 'en-US'))), 201
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except LookupError as error:
            return jsonify(error=str(error)), 404

    @app.post('/api/phrases/<phrase_id>/translations')
    def add_translation(phrase_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Ожидался JSON-объект'), 400
        try:
            return jsonify(store.add_translation(phrase_id, data.get('language'),
                                                 data.get('target'))), 201
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except LookupError as error:
            return jsonify(error=str(error)), 404

    @app.patch('/api/phrases/<phrase_id>/review')
    def review(phrase_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Ожидался JSON-объект'), 400
        try:
            return jsonify(store.review(phrase_id, data.get('mastery'),
                                        data.get('language', 'en-US')))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except LookupError as error:
            return jsonify(error=str(error)), 404

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '8791')), debug=False)
