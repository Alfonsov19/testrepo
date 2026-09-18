"""SQLite access layer.

All SQL lives in this module and `business.py` / `logging_store.py`; nothing
else touches the driver. Queries use parameter binding only, so swapping
SQLite for PostgreSQL means replacing `connect()` and the placeholder style,
not the chatbot logic.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

_SCHEMA = Path(__file__).with_name("schema.sql")
_SEED = Path(__file__).with_name("seed.sql")


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Open a connection with row access by column name and FKs enforced."""
    conn = sqlite3.connect(db_path or config.SETTINGS.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def bootstrap(db_path: str | None = None, seed: bool = True) -> None:
    """Create tables if absent and optionally load TEST seed data."""
    with connect(db_path) as conn:
        conn.executescript(_SCHEMA.read_text())
        if seed:
            conn.executescript(_SEED.read_text())
        conn.commit()
    logger.info("database ready at %s (seed=%s)", db_path or config.SETTINGS.db_path, seed)


if __name__ == "__main__":  # python -m app.db
    logging.basicConfig(level=logging.INFO)
    bootstrap()
    print(f"bootstrapped {config.SETTINGS.db_path}")
