"""Offline, private-data-safe SQLite import regression tests."""

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migrate_db import MigrationError, migrate_database
from store import Store


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.old = self.base / "old.sqlite3"
        self.new = self.base / "new.sqlite3"
        self.old_store = Store(self.old)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_ratings_and_unicode_text_survive_without_modifying_source(self):
        island = self.old_store.add_island("Работа")
        phrase = self.old_store.add_phrase(
            island["id"], "Мне нравится обсуждать физику.", "I enjoy discussing physics."
        )
        self.old_store.review(phrase["id"], 0)
        self.old_store.review(phrase["id"], 2)
        count = migrate_database(self.old, self.new)
        self.assertEqual(count, {"islands": 1, "phrases": 1, "review_events": 2})
        original = Store(self.old)
        imported = Store(self.new)
        self.assertEqual(original.islands(), imported.islands())
        self.assertEqual(original.phrases(island["id"]), imported.phrases(island["id"]))
        self.assertEqual(original.event_count(phrase["id"]), 2)
        self.assertEqual(imported.event_count(phrase["id"]), 2)
        self.assertEqual(imported.phrases(island["id"])[0]["mastery"], 2)
        self.assertEqual(self.new.stat().st_mode & 0o777, 0o600)

    def test_never_overwrites_an_existing_destination(self):
        self.new.write_bytes(b"existing owner data")
        with self.assertRaises(MigrationError):
            migrate_database(self.old, self.new)
        self.assertEqual(self.new.read_bytes(), b"existing owner data")

    def test_never_deletes_or_rewrites_source(self):
        island = self.old_store.add_island("Семья")
        self.old_store.add_phrase(island["id"], "Я здесь", "I am here")
        before = self.old.read_bytes()
        migrate_database(self.old, self.new)
        self.assertEqual(self.old.read_bytes(), before)
        with self.assertRaises(MigrationError):
            migrate_database(self.old, self.new)

    def test_rejects_missing_source_and_non_sqlite_file(self):
        with self.assertRaises(MigrationError):
            migrate_database(self.base / "missing.sqlite3", self.new)
        fake = self.base / "fake.sqlite3"
        fake.write_text("not a database", encoding="utf-8")
        with self.assertRaises(MigrationError):
            migrate_database(fake, self.new)
        self.assertFalse(self.new.exists())

    def test_rejects_incompatible_schema(self):
        with sqlite3.connect(self.old) as conn:
            conn.execute("DROP TABLE review_events")
        with self.assertRaisesRegex(MigrationError, "compatible"):
            migrate_database(self.old, self.new)
        self.assertFalse(self.new.exists())

    def test_copy_of_empty_but_compatible_database(self):
        counts = migrate_database(self.old, self.new)
        self.assertEqual(counts, {"islands": 0, "phrases": 0, "review_events": 0})
        self.assertEqual(Store(self.new).islands(), [])

    def test_rejects_foreign_key_damage(self):
        with sqlite3.connect(self.old) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                "INSERT INTO phrases(id,island_id,ru,en,mastery,created_at)"
                " VALUES('p','missing','hello','Hello',0,'now')"
            )
        with self.assertRaisesRegex(MigrationError, "foreign key"):
            migrate_database(self.old, self.new)
        self.assertFalse(self.new.exists())


if __name__ == "__main__":
    unittest.main()
