"""Tiny SQLite key/value settings store (stdlib only)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .providers.config import SELECTED_MODEL_SETTING


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "voxflow"


def default_db_path() -> Path:
    return data_dir() / "voxflow.db"


def _connect(db_path: Path | None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def get(key: str, default: str | None = None, *, db_path: Path | None = None) -> str | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return default if row is None else row[0]


def set(key: str, value: str | None, *, db_path: Path | None = None) -> None:  # noqa: A001
    """Store ``value``; ``None`` deletes the key."""

    conn = _connect(db_path)
    try:
        with conn:
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
    finally:
        conn.close()


def selected_model_id(*, db_path: Path | None = None) -> str | None:
    return get(SELECTED_MODEL_SETTING, db_path=db_path)


def set_selected_model_id(model_id: str | None, *, db_path: Path | None = None) -> None:
    set(SELECTED_MODEL_SETTING, model_id, db_path=db_path)
