"""SQLite persistence for the local, single-user architecture spike."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
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
                'SELECT * FROM islands ORDER BY created_at, id'
            )]

    def add_island(self, title):
        if not isinstance(title, str) or not (1 <= len(title.strip()) <= 120):
            raise ValueError('Название острова: от 1 до 120 символов')
        island = dict(id=str(uuid.uuid4()), title=title.strip(), created_at=timestamp())
        with self.connection() as conn:
            conn.execute('INSERT INTO islands (id,title,created_at) VALUES (:id,:title,:created_at)', island)
        return island

    def phrases(self, island_id):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(
                '''SELECT p.*, (SELECT COUNT(*) FROM review_events r WHERE r.phrase_id=p.id) AS review_count
                   FROM phrases p WHERE p.island_id=? ORDER BY p.created_at, p.id''', (island_id,)
            )]

    def add_phrase(self, island_id, ru, en):
        for value, label in ((ru, 'Русский'), (en, 'Английский')):
            if not isinstance(value, str) or not (1 <= len(value.strip()) <= 2000):
                raise ValueError(f'{label} текст: от 1 до 2000 символов')
        phrase = dict(id=str(uuid.uuid4()), island_id=island_id, ru=ru.strip(), en=en.strip(), mastery=0,
                      created_at=timestamp())
        with self.connection() as conn:
            if not conn.execute('SELECT 1 FROM islands WHERE id=?', (island_id,)).fetchone():
                raise LookupError('Остров не найден')
            conn.execute('''INSERT INTO phrases(id,island_id,ru,en,mastery,created_at)
                            VALUES (:id,:island_id,:ru,:en,:mastery,:created_at)''', phrase)
        return phrase

    def review(self, phrase_id, mastery):
        if type(mastery) is not int or mastery not in (0, 1, 2):
            raise ValueError('Оценка должна быть 0, 1 или 2')
        with self.connection() as conn:
            if not conn.execute('SELECT 1 FROM phrases WHERE id=?', (phrase_id,)).fetchone():
                raise LookupError('Фраза не найдена')
            conn.execute('UPDATE phrases SET mastery=? WHERE id=?', (mastery, phrase_id))
            conn.execute('INSERT INTO review_events(id,phrase_id,mastery,created_at) VALUES(?,?,?,?)',
                         (str(uuid.uuid4()), phrase_id, mastery, timestamp()))
        return {'id': phrase_id, 'mastery': mastery, 'review_count': self.event_count(phrase_id)}

    def event_count(self, phrase_id):
        with self.connection() as conn:
            return conn.execute('SELECT COUNT(*) FROM review_events WHERE phrase_id=?', (phrase_id,)).fetchone()[0]
