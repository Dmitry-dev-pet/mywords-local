"""Multilingual regression: shared Russian thoughts, independent per-language scores."""
import copy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starter_packs import find_starter_pack
from store import Store

try:
    from server import create_app
except ModuleNotFoundError as error:
    if error.name != 'flask':
        raise
    create_app = None


class MultilingualStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'study.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_language_independent_thought_and_score(self):
        store = Store(self.path)
        island = store.add_island('Поездка')
        phrase = store.add_phrase(island['id'], 'Я хочу поймать волну.', 'I want to catch a wave.')
        phrase_id = phrase['id']
        self.assertEqual(store.phrases(island['id'], 'pt-PT')[0]['target'], None)
        with self.assertRaises(LookupError):
            store.review(phrase_id, 2, 'pt-PT')
        store.review(phrase_id, 2, 'en-US')
        store.review(phrase_id, 0, 'en-US')
        store.add_translation(phrase_id, 'pt-PT', 'Quero apanhar uma onda.')
        store.review(phrase_id, 1, 'pt-PT')
        store.review(phrase_id, 2, 'pt-PT')
        reopened = Store(self.path)
        en = reopened.phrases(island['id'], 'en-US')[0]
        pt = reopened.phrases(island['id'], 'pt-PT')[0]
        self.assertEqual(en['ru'], pt['ru'])
        self.assertEqual(en['id'], pt['id'])
        self.assertEqual(en['target'], 'I want to catch a wave.')
        self.assertEqual(pt['target'], 'Quero apanhar uma onda.')
        self.assertEqual((en['mastery'], en['review_count']), (0, 2))
        self.assertEqual((pt['mastery'], pt['review_count']), (2, 2))
        self.assertEqual(reopened.event_count(phrase_id, 'en-US'), 2)
        self.assertEqual(reopened.event_count(phrase_id, 'pt-PT'), 2)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT mastery FROM phrases WHERE id=?',
                                        (phrase_id,)).fetchone()[0], 0)

    def test_create_pt_only_then_add_en(self):
        store = Store(self.path)
        island = store.add_island('Разговор')
        pt = store.add_phrase(island['id'], 'Спасибо', 'Obrigado.', language='pt-PT')
        self.assertEqual(store.phrases(island['id'], 'en-US')[0]['target'], None)
        self.assertEqual(store.phrases(island['id'], 'pt-PT')[0]['target'], 'Obrigado.')
        store.add_translation(pt['id'], 'en-US', 'Thank you.')
        self.assertEqual(store.phrases(island['id'], 'en-US')[0]['target'], 'Thank you.')
        store.review(pt['id'], 2, 'en-US')
        with self.assertRaises(ValueError):
            store.add_translation(pt['id'], 'pt-PT', 'Obrigado novamente.')
        self.assertEqual(store.phrases(island['id'], 'pt-PT')[0]['review_count'], 0)

    def test_additional_pt_translations_on_previous_import(self):
        store = Store(self.path)
        pack = find_starter_pack('surfing')
        first_version = copy.deepcopy(pack)
        for p in first_version['phrases']:
            p.pop('pt-PT', None)
        first = store.import_starter_island(first_version)
        self.assertEqual(first['added'], 18)
        self.assertEqual(first['added_translations'], 18)
        phrase = store.phrases(first['island_id'])[0]
        store.review(phrase['id'], 2)
        second = store.import_starter_island(pack)
        self.assertFalse(second['created'])
        self.assertEqual(second['added'], 0)
        self.assertEqual(second['added_translations'], 18)
        en = store.phrases(first['island_id'], 'en-US')
        pt = store.phrases(first['island_id'], 'pt-PT')
        self.assertEqual(len(en), len(pt))
        self.assertEqual(len(pt), 18)
        self.assertTrue(all(x['target'] and x['review_count'] == 0 for x in pt))
        self.assertEqual(en[0]['review_count'], 1)
        self.assertEqual(en[0]['mastery'], 2)
        third = store.import_starter_island(pack)
        self.assertEqual(third['added_translations'], 0)

    def test_one_time_backup_on_upgrade_of_legacy_schema(self):
        # Simulate a real pre-OPEN-2 database without user-controlled test data in GitHub.
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE islands(id TEXT PRIMARY KEY,title TEXT,created_at TEXT);
                CREATE TABLE phrases(id TEXT PRIMARY KEY,island_id TEXT,ru TEXT,en TEXT,
                                     mastery INTEGER,created_at TEXT);
                CREATE TABLE review_events(id TEXT PRIMARY KEY,phrase_id TEXT,
                                           mastery INTEGER,created_at TEXT);
            """)
            db.execute("INSERT INTO islands VALUES ('i','Серфинг','2026')")
            db.execute("INSERT INTO phrases VALUES ('p','i','Волна','Wave',2,'2026')")
            db.execute("INSERT INTO review_events VALUES ('r','p',2,'2026')")
        store = Store(self.path)
        backup = self.path.with_name(self.path.name + '.before-multilingual.sqlite3')
        self.assertTrue(backup.is_file())
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('SELECT en,mastery FROM phrases').fetchone(),
                             ('Wave', 2))
            self.assertNotIn('language', [r[1] for r in db.execute('PRAGMA table_info(review_events)')])
        en = store.phrases('i', 'en-US')
        self.assertEqual((en[0]['target'], en[0]['mastery'], en[0]['review_count']),
                         ('Wave', 2, 1))
        self.assertIsNone(store.phrases('i', 'pt-PT')[0]['target'])
        store.review('p', 1, 'pt-PT') if False else None
        Store(self.path)
        self.assertEqual(Store(self.path).event_count('p'), 1)
        self.assertEqual(len(list(self.path.parent.glob('*.before-multilingual.sqlite3'))), 1)


@unittest.skipIf(create_app is None, 'Flask is unavailable')
class MultilingualApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = create_app(Path(self.temp.name) / 'study.sqlite3').test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_api_target_language_and_missing_translations(self):
        island = self.client.post('/api/islands', json={'title':'Общее'}).get_json()
        phrase_id = self.client.post(f"/api/islands/{island['id']}/phrases",
            json={'ru':'Доброе утро','target':'Bom dia.','language':'pt-PT'}).get_json()['id']
        url=f"/api/islands/{island['id']}/phrases"
        self.assertIsNone(self.client.get(url).get_json()[0]['target'])
        self.assertEqual(self.client.get(url+'?language=pt-PT').get_json()[0]['target'], 'Bom dia.')
        self.assertEqual(self.client.get(url+'?language=pt-BR').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/phrases/{phrase_id}/review',
                          json={'language':'en-US','mastery':2}).status_code,404)
        self.assertEqual(self.client.post(f'/api/phrases/{phrase_id}/translations',
                          json={'language':'en-US','target':'Good morning.'}).status_code,201)
        self.assertEqual(self.client.patch(f'/api/phrases/{phrase_id}/review',
                          json={'language':'en-US','mastery':2}).status_code,200)
        self.assertEqual(self.client.patch(f'/api/phrases/{phrase_id}/review',
                          json={'language':'pt-PT','mastery':1}).status_code,200)
        self.assertEqual(self.client.get(url).get_json()[0]['mastery'], 2)
        self.assertEqual(self.client.get(url+'?language=pt-PT').get_json()[0]['mastery'], 1)
        self.assertEqual(self.client.post(f'/api/phrases/{phrase_id}/translations',
                          json={'language':'en-US','target':'Hi'}).status_code,400)


if __name__ == '__main__':
    unittest.main()
