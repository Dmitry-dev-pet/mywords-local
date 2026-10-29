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
import shutil
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
    # Newer backups include language-specific events and translation rows.
    # Old SQLite files are still compatible; verify every extra row when present.
    event_columns = {r[1] for r in conn.execute("PRAGMA table_info(review_events)")}
    if "language" in event_columns:
        digest.update(b"review_events.language\\0")
        for row in conn.execute("SELECT id, language FROM review_events ORDER BY id"):
            digest.update(json.dumps(list(row), ensure_ascii=False).encode("utf-8") + b"\\n")
    has_translations = conn.execute("""
        SELECT 1 FROM sqlite_master WHERE type='table' AND name='phrase_translations'
    """).fetchone() is not None
    if has_translations:
        required = {"phrase_id", "language", "text", "mastery"}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(phrase_translations)")}
        if not required.issubset(columns):
            raise MigrationError("Database has an incompatible translations schema")
        digest.update(b"phrase_translations\\0")
        for row in conn.execute("""
            SELECT phrase_id, language, text, mastery
            FROM phrase_translations ORDER BY phrase_id, language
        """):
            digest.update(json.dumps(list(row), ensure_ascii=False).encode("utf-8") + b"\\n")
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
    created_destination = False
    completed = False
    try:
        with closing(_open_source(source)) as input_db:
            counts, source_digest = _fingerprint(input_db)
            # Prepare and verify a consistent SQLite backup before creating
            # the destination. Android's Termux Python may lack os.link().
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
            # O_EXCL is available in Termux even where os.link is absent.
            # Only a brand-new destination may be created; never overwrite.
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created_destination = True
            try:
                with os.fdopen(fd, "wb") as output_file:
                    fd = None
                    with temporary.open("rb") as verified_backup:
                        shutil.copyfileobj(verified_backup, output_file)
                    output_file.flush()
                    os.fsync(output_file.fileno())
            finally:
                if fd is not None:
                    os.close(fd)

            # Verify the final file too, not merely the temporary SQLite copy.
            with closing(_open_source(destination)) as final_db:
                final_counts, final_digest = _fingerprint(final_db)
            if counts != final_counts or source_digest != final_digest:
                raise MigrationError("Final database does not match the source")
            completed = True
            return final_counts
    except (OSError, sqlite3.DatabaseError) as exc:
        if isinstance(exc, FileExistsError):
            raise MigrationError("Destination already exists; refusing to overwrite") from None
        raise MigrationError("Cannot copy and verify SQLite; original is untouched") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        # If a write or final verification failed, remove only the new file
        # created by this invocation; never touch an existing destination.
        if created_destination and not completed:
            destination.unlink(missing_ok=True)


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
