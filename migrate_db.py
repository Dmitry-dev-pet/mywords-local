"""Safely copy an existing local MyWords SQLite database into this clean checkout.

No network, secrets, lesson text printing or old-repository identifiers.
The source file is never modified. The destination is created exclusively.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile

TABLES = {
    "islands": (
        {"id", "title", "created_at"},
        "SELECT id, title, created_at FROM islands ORDER BY id",
    ),
    "phrases": (
        {"id", "island_id", "ru", "en", "mastery", "created_at"},
        "SELECT id, island_id, ru, en, mastery, created_at FROM phrases ORDER BY id",
    ),
    "review_events": (
        {"id", "phrase_id", "mastery", "created_at"},
        "SELECT id, phrase_id, mastery, created_at FROM review_events ORDER BY id",
    ),
}


class MigrationError(Exception):
    """Actionable error with no personal phrase content."""


def _open_source(path: Path) -> sqlite3.Connection:
    # URI mode=ro prevents accidental source changes and works with WAL.
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)


def _fingerprint(conn: sqlite3.Connection) -> tuple[dict[str, int], str]:
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise MigrationError("SQLite integrity check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MigrationError("SQLite foreign key check failed")
    digest = hashlib.sha256()
    counts = {}
    for table, (columns, query) in TABLES.items():
        present = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if not columns.issubset(present):
            raise MigrationError("Database is not a compatible MyWords database")
        count = 0
        digest.update(table.encode("ascii") + b"\0")
        for record in conn.execute(query):
            digest.update(
                json.dumps(
                    list(record), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                + b"\n"
            )
            count += 1
        counts[table] = count
    return counts, digest.hexdigest()


def migrate_database(source: Path, destination: Path) -> dict[str, int]:
    """Copy+verify all lesson rows without overwriting destination or source."""
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().absolute()
    if not source.is_file() or source.stat().st_size == 0:
        raise MigrationError("Source SQLite file is missing or empty")
    if destination == source or destination.exists() or destination.is_symlink():
        raise MigrationError("Destination already exists; existing data was not overwritten")
    if not destination.parent.is_dir():
        raise MigrationError("Destination directory does not exist")
    temporary: Path | None = None
    try:
        with closing(_open_source(source)) as input_db:
            counts, source_digest = _fingerprint(input_db)
            # A temporary database on the destination filesystem allows an
            # atomic exclusive hardlink; simultaneous destination creation
            # cannot overwrite the user's existing study file.
            fd, name = tempfile.mkstemp(
                prefix=".mywords-import-", suffix=".sqlite3",
                dir=destination.parent,
            )
            os.close(fd)
            temporary = Path(name)
            os.chmod(temporary, 0o600)
            with closing(sqlite3.connect(temporary)) as output_db:
                input_db.backup(output_db)
                output_db.commit()
                copied_counts, copied_digest = _fingerprint(output_db)
            if counts != copied_counts or source_digest != copied_digest:
                raise MigrationError("Copied lessons do not match the source")
            os.link(temporary, destination)  # fails if destination exists
            return copied_counts
    except (OSError, sqlite3.DatabaseError) as exc:
        if isinstance(exc, FileExistsError):
            raise MigrationError("Destination already exists; refusing to overwrite") from None
        raise MigrationError("Cannot copy and verify SQLite; original is untouched") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _server_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8791), timeout=0.3):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy an existing local MyWords SQLite file without overwrites."
    )
    parser.add_argument("source", type=Path, help="Old local.sqlite3 file")
    args = parser.parse_args()
    if _server_running():
        print("Stop the previous Flask/Termux supervisor first (Ctrl+C).", file=sys.stderr)
        return 2
    target = Path(__file__).resolve().parent / "local.sqlite3"
    try:
        counts = migrate_database(args.source, target)
    except MigrationError as exc:
        print(f"Import stopped: {exc}", file=sys.stderr)
        return 2
    print(
        "SQLite verified and copied locally: "
        f"{counts['islands']} islands, {counts['phrases']} phrases, "
        f"{counts['review_events']} reviews."
    )
    print("Original SQLite is unchanged. No lesson data was uploaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
