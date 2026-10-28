"""Local-only Flask API and static frontend. Not a production server."""
import os
import platform
import sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from store import Store
from starter_packs import list_starter_packs, find_starter_pack

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'


def create_app(database=None):
    app = Flask(__name__, static_folder=None)
    store = Store(database or os.environ.get('MYWORDS_TEST_DB') or (ROOT / 'local.sqlite3'))

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
                       storage='local')

    @app.get('/api/starter-islands')
    def starter_islands():
        # Public catalog only; no SQLite writes or external requests.
        return jsonify(list_starter_packs())

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
        return jsonify(store.phrases(island_id))

    @app.post('/api/islands/<island_id>/phrases')
    def add_phrase(island_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Ожидался JSON-объект'), 400
        try:
            return jsonify(store.add_phrase(island_id, data.get('ru'), data.get('en'))), 201
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
            return jsonify(store.review(phrase_id, data.get('mastery')))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except LookupError as error:
            return jsonify(error=str(error)), 404

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '8791')), debug=False)
