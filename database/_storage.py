"""SQLite-backed document store with a process-local cache."""

import json
import sqlite3
import threading
import time
from typing import Any, Optional

from config import DB_PATH


_conn: Optional[sqlite3.Connection] = None
_conn_lock = threading.Lock()
_cache: dict[tuple[int, str], Any] = {}


def _open() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    with _conn_lock:
        if _conn is not None:
            return _conn
        c = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None, timeout=30.0)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA temp_store=MEMORY")
        c.execute("PRAGMA mmap_size=268435456")
        c.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (guild_id, name)
            )
        """)
        _conn = c
        return c


def _write(c: sqlite3.Connection, guild_id: int, name: str, data: Any) -> None:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    c.execute(
        "INSERT INTO documents (guild_id, name, data, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (guild_id, name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (int(guild_id), name, payload, time.time()),
    )


def load_doc(guild_id: int, name: str, default: Any = None) -> Any:
    key = (int(guild_id), name)
    if key in _cache:
        return _cache[key]
    row = _open().execute(
        "SELECT data FROM documents WHERE guild_id=? AND name=?", (int(guild_id), name)
    ).fetchone()
    if row is not None:
        try:
            value = json.loads(row["data"])
        except Exception:
            value = default if default is not None else {}
    else:
        value = default if default is not None else {}
    _cache[key] = value
    return value


def save_doc(guild_id: int, name: str, data: Any) -> None:
    _write(_open(), int(guild_id), name, data)
    _cache[(int(guild_id), name)] = data
