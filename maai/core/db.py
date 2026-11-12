"""The shared memory of the office: one small SQLite database file.

Tables:
  tasks        the task board (To Do / In Progress / Waiting for Me / Done)
  task_notes   answers, questions and feedback attached to a task
  approvals    everything waiting for your OK (and what happened after)
  activity     the action log shown in the office (no private details)
  clients      client contact info (never card, bank or SSN numbers)
  invoices     invoices and their payment status (money stored in cents)
  costs        what each AI call cost
  chat         recent messages between you and the Director
  kv           small settings the system remembers (counters, folder ids)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',
    progress INTEGER NOT NULL DEFAULT 0,
    question TEXT,
    result TEXT,
    source TEXT NOT NULL DEFAULT 'owner',
    parent_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE TABLE IF NOT EXISTS task_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    preview TEXT NOT NULL,
    payload TEXT NOT NULL,
    attachment TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    ref TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    note TEXT
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    address TEXT,
    notes TEXT,
    is_test INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL,
    project TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    data TEXT NOT NULL,
    doc_id TEXT,
    pdf_file_id TEXT,
    pdf_path TEXT,
    sent_at TEXT,
    paid_at TEXT,
    reminders_sent INTEGER NOT NULL DEFAULT 0,
    last_reminder_at TEXT,
    is_test INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    month TEXT NOT NULL,
    agent TEXT NOT NULL,
    model TEXT,
    usd REAL NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    task_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_costs_month ON costs(month);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)

    # ---- basic helpers ----------------------------------------------------
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # ---- key/value --------------------------------------------------------
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM kv WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def next_counter(self, key: str) -> int:
        """Atomically increment and return a counter (used for invoice numbers)."""
        with self.transaction() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
            value = (json.loads(row["value"]) if row else 0) + 1
            conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        return value

    # ---- backups ----------------------------------------------------------
    def backup_to(self, target: Path) -> None:
        """Consistent copy of the live database (safe while running)."""
        with self._lock:
            dest = sqlite3.connect(str(target))
            try:
                self._conn.backup(dest)
            finally:
                dest.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
