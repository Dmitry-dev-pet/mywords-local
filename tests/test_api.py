"""API round-trip tests; setup.sh installs Flask before running these."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from server import create_app
except ModuleNotFoundError as error:
    if error.name != 'flask':
        raise
    create_app = None


@unittest.skipIf(create_app is None, 'Flask is not installed in this isolated test environment')
class TestApi(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'study.sqlite3'
        self.app = create_app(self.database)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_focus_recall_review_round_trip(self):
        island = self.client.post('/api/islands', json={'title': 'Серфинг'})
        self.assertEqual(island.status_code, 201)
        island_id = island.get_json()['id']
        phrase = self.client.post(f'/api/islands/{island_id}/phrases', json={
            'ru': 'Я хочу поймать волну.', 'en': 'I want to catch a wave.'
        })
        self.assertEqual(phrase.status_code, 201)
        phrase_id = phrase.get_json()['id']
        url = f'/api/islands/{island_id}/phrases'
        self.assertEqual(self.client.get(url).get_json()[0]['review_count'], 0)
        for score in (0, 2):
            response = self.client.patch(f'/api/phrases/{phrase_id}/review', json={'mastery': score})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['review_count'], 2)
        # This constructs a new app and opens the same SQLite file, just like restarting Flask.
        reopened = create_app(self.database).test_client()
        result = reopened.get(url).get_json()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['mastery'], 2)
        self.assertEqual(result[0]['review_count'], 2)

    def test_unhandled_exception_is_sanitized(self):
        app = create_app(self.database)
        @app.post('/test/crash')
        def crash():
            raise RuntimeError('EXAMPLE PRIVATE phrase and password')
        response = app.test_client().post('/test/crash', json={'answer': 'EXAMPLE USER TEXT'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()['error'], 'Внутренняя ошибка сервера')

    def test_bad_score_is_rejected_without_writes(self):
        island_id = self.client.post('/api/islands', json={'title': 'Тест'}).get_json()['id']
        phrase_id = self.client.post(f'/api/islands/{island_id}/phrases', json={
            'ru': 'Привет', 'en': 'Hello'
        }).get_json()['id']
        result = self.client.patch(f'/api/phrases/{phrase_id}/review', json={'mastery': True})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get(f'/api/islands/{island_id}/phrases').get_json()[0]['review_count'], 0)


if __name__ == '__main__':
    unittest.main()
