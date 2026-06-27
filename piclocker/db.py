"""SQLite access — one place that knows how to open/initialise the database."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "schemas.sql"


@contextmanager
def get_db(db_path):
    """Connection with foreign keys ON (per-connection pragma), closed on exit."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
    finally:
        conn.close()


def init_db(conn):
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def ensure_db(db_path):
    """Idempotent: schemas.sql is all CREATE IF NOT EXISTS."""
    with get_db(db_path) as conn:
        init_db(conn)
