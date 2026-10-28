import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store import Store


class TestStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'mywords.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_islands_survive_restart(self):
        island = self.store.add_island('Серфинг')
        reopened = Store(self.path)
        self.assertEqual(reopened.islands()[0]['id'], island['id'])

    def test_phrase_and_review_survive_restart(self):
        island = self.store.add_island('Серфинг')
        phrase = self.store.add_phrase(island['id'], 'Я хочу поймать волну.', 'I want to catch a wave.')
        self.store.review(phrase['id'], 1)
        self.store.review(phrase['id'], 2)
        reopened = Store(self.path)
        self.assertEqual(reopened.phrases(island['id'])[0]['mastery'], 2)
        self.assertEqual(reopened.event_count(phrase['id']), 2)
        self.assertEqual(reopened.phrases(island['id'])[0]['review_count'], 2)

    def test_review_events_are_independent_of_playback(self):
        island = self.store.add_island('Беседа')
        phrase = self.store.add_phrase(island['id'], 'Я готов', 'I am ready')
        self.assertEqual(self.store.phrases(island['id'])[0]['review_count'], 0)
        result = self.store.review(phrase['id'], 0)
        self.assertEqual(result['review_count'], 1)
        self.assertEqual(result['mastery'], 0)
        result = self.store.review(phrase['id'], 1)
        self.assertEqual(result['review_count'], 2)
        self.assertEqual(Store(self.path).phrases(island['id'])[0]['mastery'], 1)

    def test_unknown_island_does_not_create_phrase(self):
        with self.assertRaises(LookupError):
            self.store.add_phrase('missing', 'привет', 'hello')

    def test_invalid_mastery_does_not_change_data(self):
        island = self.store.add_island('Тест')
        phrase = self.store.add_phrase(island['id'], 'проверка', 'test')
        for invalid in (-1, 3, True, '2'):
            with self.assertRaises(ValueError):
                self.store.review(phrase['id'], invalid)
        self.assertEqual(Store(self.path).phrases(island['id'])[0]['mastery'], 0)

    def test_sql_metacharacters_are_data(self):
        title = "Hello'); DROP TABLE islands;--"
        self.store.add_island(title)
        self.assertEqual(Store(self.path).islands()[0]['title'], title)


if __name__ == '__main__':
    unittest.main()
