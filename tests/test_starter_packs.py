"""Optional starter island catalog and safe idempotent import regression tests."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starter_packs import find_starter_pack, list_starter_packs, load_starter_packs, starter_island_id
from store import Store

try:
    from server import create_app
except ModuleNotFoundError as error:
    if error.name != "flask":
        raise
    create_app = None


class StarterContentTests(unittest.TestCase):
    def test_eight_distinct_packs_with_eighteen_distinct_phrases_each(self):
        packs = load_starter_packs()
        self.assertEqual(len(packs), 8)
        self.assertEqual(sum(len(p["phrases"]) for p in packs), 144)
        self.assertEqual(len({starter_island_id(p["id"]) for p in packs}), 8)
        for pack in packs:
            self.assertEqual(len(pack["phrases"]), 18)
            self.assertIs(find_starter_pack(pack["id"]), pack)

    def test_import_is_opt_in_idempotent_and_keeps_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "private.sqlite3")
            original = store.add_island("Мои собственные фразы")
            private = store.add_phrase(original["id"], "Мой текст", "My private sentence")
            store.review(private["id"], 2)
            pack = find_starter_pack("surfing")
            self.assertEqual(len(store.islands()), 1)
            first = store.import_starter_island(pack)
            self.assertTrue(first["created"])
            self.assertEqual(first["added"], 18)
            imported = store.phrases(first["island_id"])
            self.assertEqual(len(imported), 18)
            self.assertTrue(all(p["mastery"] == 0 and p["review_count"] == 0 for p in imported))
            store.review(imported[0]["id"], 1)
            repeat = store.import_starter_island(pack)
            self.assertFalse(repeat["created"])
            self.assertEqual(repeat["added"], 0)
            imported_again = store.phrases(first["island_id"])
            self.assertEqual(len(imported_again), 18)
            self.assertEqual(store.event_count(imported[0]["id"]), 1)
            self.assertEqual(imported_again[0]["mastery"], 1)
            self.assertEqual(store.phrases(original["id"])[0]["en"], "My private sentence")
            self.assertEqual(store.phrases(original["id"])[0]["mastery"], 2)
            self.assertEqual(store.event_count(private["id"]), 1)
            self.assertEqual(len(store.islands()), 2)

    def test_catalog_contains_real_sentences_and_stable_ids(self):
        packs = list_starter_packs()
        self.assertEqual(packs[0]["phrase_count"], len(packs[0]["phrases"]))
        self.assertEqual(packs[0]["island_id"], starter_island_id(packs[0]["id"]))
        self.assertEqual(packs[0]["phrases"][0]["ru"], "Привет, рад познакомиться.")


@unittest.skipIf(create_app is None, "Flask is not installed")
class StarterApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "private.sqlite3"
        self.client = create_app(self.db).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_catalog_read_does_not_seed_database(self):
        result = self.client.get("/api/starter-islands")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.get_json()), 8)
        self.assertEqual(self.client.get("/api/islands").get_json(), [])

    def test_unknown_pack_does_not_import_anything(self):
        result = self.client.post("/api/starter-islands/no-such-pack/import")
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.client.get("/api/islands").get_json(), [])

    def test_import_twice_does_not_duplicate_or_reset_review(self):
        path = "/api/starter-islands/travel/import"
        first = self.client.post(path)
        self.assertEqual(first.status_code, 201)
        island_id = first.get_json()["island_id"]
        phrases_url = f"/api/islands/{island_id}/phrases"
        phrases = self.client.get(phrases_url).get_json()
        self.assertEqual(len(phrases), 18)
        self.assertEqual(phrases[0]["en"], "Could I see the menu, please?")
        self.assertEqual(self.client.patch(f'/api/phrases/{phrases[0]["id"]}/review', json={"mastery": 2}).status_code, 200)
        again = self.client.post(path)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["added"], 0)
        self.assertEqual(len(self.client.get(phrases_url).get_json()), 18)
        self.assertEqual(self.client.get(phrases_url).get_json()[0]["review_count"], 1)


if __name__ == "__main__":
    unittest.main()
