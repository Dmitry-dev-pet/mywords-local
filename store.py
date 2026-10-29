"""SQLite storage for language-independent islands and language-specific progress.

Legacy phrases.en/mastery remain as compatibility mirrors for existing English data.
The authoritative multilingual text and ratings live in phrase_translations;
review_events.language separates English and Portuguese review histories.
"""
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3
import uuid

from starter_packs import starter_island_id, starter_phrase_id

LANGUAGES = ("en-US", "pt-PT")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def validate_language(language):
    if language not in LANGUAGES:
        raise ValueError("Неподдерживаемый язык обучения")
    return language


def validate_text(value, label):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
        raise ValueError(f"{label}: от 1 до 2000 символов")
    return value.strip()


class Store:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._backup_legacy_database_if_needed()
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS islands (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS phrases (
                    id TEXT PRIMARY KEY,
                    island_id TEXT NOT NULL REFERENCES islands(id) ON DELETE CASCADE,
                    ru TEXT NOT NULL,
                    en TEXT NOT NULL,
                    mastery INTEGER NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 2),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    id TEXT PRIMARY KEY,
                    phrase_id TEXT NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
                    mastery INTEGER NOT NULL CHECK (mastery BETWEEN 0 AND 2),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_phrase_time
                ON review_events(phrase_id, created_at);
            """)
            # Older on-device SQLite does not have a language column.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(review_events)")}
            if "language" not in columns:
                conn.execute(
                    "ALTER TABLE review_events ADD COLUMN language TEXT NOT NULL DEFAULT 'en-US'"
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS phrase_translations (
                    phrase_id TEXT NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
                    language TEXT NOT NULL CHECK(language IN ('en-US', 'pt-PT')),
                    text TEXT NOT NULL,
                    mastery INTEGER NOT NULL DEFAULT 0 CHECK(mastery BETWEEN 0 AND 2),
                    PRIMARY KEY (phrase_id, language)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_reviews_phrase_language_time
                ON review_events(phrase_id, language, created_at)
            """)
            # Backfill once without changing original English ratings/reviews.
            conn.execute("""
                INSERT OR IGNORE INTO phrase_translations(phrase_id, language, text, mastery)
                SELECT id, 'en-US', en, mastery FROM phrases WHERE length(trim(en)) > 0
            """)

    def _backup_legacy_database_if_needed(self):
        """Keep a consistent, private copy of older populated SQLite before migration."""
        if not self.database.is_file() or not self.database.stat().st_size:
            return
        destination = self.database.with_name(self.database.name + ".before-multilingual.sqlite3")
        with closing(sqlite3.connect(self.database)) as source:
            tables = {row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not {"islands", "phrases", "review_events"}.issubset(tables):
                return
            columns = {row[1] for row in source.execute("PRAGMA table_info(review_events)")}
            if "phrase_translations" in tables and "language" in columns:
                return
            populated = any(source.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                            for table in ("islands", "phrases", "review_events"))
            if not populated or destination.exists():
                return
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Legacy database integrity check failed")
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            try:
                with closing(sqlite3.connect(destination)) as backup:
                    source.backup(backup)
                with closing(sqlite3.connect(destination)) as check:
                    if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise sqlite3.DatabaseError("Backup verification failed")
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.database, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def islands(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM islands ORDER BY created_at, id"
            )]

    def add_island(self, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ValueError("Название острова: от 1 до 120 символов")
        island = dict(id=str(uuid.uuid4()), title=title.strip(), created_at=timestamp())
        with self.connection() as conn:
            conn.execute("INSERT INTO islands(id,title,created_at) VALUES(:id,:title,:created_at)", island)
        return island

    def phrases(self, island_id, language="en-US"):
        """All shared Russian phrases, including those not yet translated to language."""
        validate_language(language)
        with self.connection() as conn:
            rows = conn.execute("""
                SELECT p.id,p.island_id,p.ru,p.en,p.created_at,
                       tr.text AS target,tr.mastery AS language_mastery,
                       (SELECT count(*) FROM review_events rev
                        WHERE rev.phrase_id=p.id AND rev.language=?) AS review_count
                FROM phrases p
                LEFT JOIN phrase_translations tr
                    ON tr.phrase_id=p.id AND tr.language=?
                WHERE p.island_id=?
                ORDER BY p.created_at, p.id
            """, (language, language, island_id))
            result = []
            for row in rows:
                phrase = dict(row)
                phrase["mastery"] = phrase.pop("language_mastery")
                phrase["language"] = language
                result.append(phrase)
            return result

    def add_phrase(self, island_id, ru, target, language="en-US"):
        """New shared thought with one target translation; others can be added later."""
        validate_language(language)
        ru = validate_text(ru, "Русский текст")
        target = validate_text(target, "Перевод")
        phrase = dict(id=str(uuid.uuid4()), island_id=island_id, ru=ru,
                      en=(target if language == "en-US" else ""), mastery=0,
                      created_at=timestamp())
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM islands WHERE id=?", (island_id,)).fetchone():
                raise LookupError("Остров не найден")
            conn.execute("""
                INSERT INTO phrases(id,island_id,ru,en,mastery,created_at)
                VALUES(:id,:island_id,:ru,:en,:mastery,:created_at)
            """, phrase)
            conn.execute("""
                INSERT INTO phrase_translations(phrase_id,language,text,mastery)
                VALUES(?,?,?,0)
            """, (phrase["id"], language, target))
        return {**phrase, "target": target, "language": language, "review_count": 0}

    def add_translation(self, phrase_id, language, target):
        validate_language(language)
        target = validate_text(target, "Перевод")
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM phrases WHERE id=?", (phrase_id,)).fetchone():
                raise LookupError("Фраза не найдена")
            result = conn.execute("""
                INSERT OR IGNORE INTO phrase_translations(phrase_id,language,text,mastery)
                VALUES(?,?,?,0)
            """, (phrase_id, language, target))
            if result.rowcount == 0:
                raise ValueError("Перевод уже существует; прежняя оценка сохранена")
            if language == "en-US":
                conn.execute("UPDATE phrases SET en=? WHERE id=?", (target, phrase_id))
        return {"id": phrase_id, "language": language, "target": target, "mastery": 0,
                "review_count": 0}

    def review(self, phrase_id, mastery, language="en-US"):
        validate_language(language)
        if type(mastery) is not int or mastery not in (0, 1, 2):
            raise ValueError("Оценка должна быть 0, 1 или 2")
        with self.connection() as conn:
            changed = conn.execute("""
                UPDATE phrase_translations SET mastery=?
                WHERE phrase_id=? AND language=?
            """, (mastery, phrase_id, language)).rowcount
            if changed == 0:
                raise LookupError("Нет перевода для выбранного языка")
            # Keep the original column compatible with existing English checks.
            if language == "en-US":
                conn.execute("UPDATE phrases SET mastery=? WHERE id=?", (mastery, phrase_id))
            conn.execute("""
                INSERT INTO review_events(id,phrase_id,mastery,created_at,language)
                VALUES(?,?,?,?,?)
            """, (str(uuid.uuid4()), phrase_id, mastery, timestamp(), language))
            review_count = conn.execute("""
                SELECT count(*) FROM review_events WHERE phrase_id=? AND language=?
            """, (phrase_id, language)).fetchone()[0]
        return {"id": phrase_id, "language": language, "mastery": mastery,
                "review_count": review_count}

    def event_count(self, phrase_id, language="en-US"):
        validate_language(language)
        with self.connection() as conn:
            return conn.execute("""
                SELECT COUNT(*) FROM review_events WHERE phrase_id=? AND language=?
            """, (phrase_id, language)).fetchone()[0]

    def import_starter_island(self, pack):
        """Add public translations to existing shared phrases without ever resetting ratings."""
        pack_id = pack["id"]
        island_id = starter_island_id(pack_id)
        start = datetime.now(timezone.utc)
        with self.connection() as conn:
            created = conn.execute(
                "INSERT OR IGNORE INTO islands(id,title,created_at) VALUES(?,?,?)",
                (island_id, pack["title"], start.isoformat()),
            ).rowcount == 1
            added, added_translations = 0, 0
            for i, pair in enumerate(pack["phrases"]):
                phrase_id = starter_phrase_id(pack_id, pair["en"])
                added += conn.execute("""
                    INSERT OR IGNORE INTO phrases
                    (id,island_id,ru,en,mastery,created_at) VALUES (?,?,?,?,0,?)
                """, (phrase_id, island_id, pair["ru"], pair["en"],
                      (start + timedelta(microseconds=i + 1)).isoformat())).rowcount
                for language, key in (("en-US", "en"), ("pt-PT", "pt-PT")):
                    if pair.get(key):
                        # INSERT OR IGNORE means user translations and reviews always win.
                        added_translations += conn.execute("""
                            INSERT OR IGNORE INTO phrase_translations
                            (phrase_id,language,text,mastery) VALUES(?,?,?,0)
                        """, (phrase_id, language, pair[key])).rowcount
        return {"island_id": island_id, "created": created, "added": added,
                "added_translations": added_translations, "total": len(pack["phrases"])}
