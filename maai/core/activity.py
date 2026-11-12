"""The action log: what happened, when, and which agent did it.

Only names and reference numbers are written here (like "invoice INV-2026-004
drafted"). Never client addresses, message text, or money details. Each
entry goes to the database (for the office) and to a monthly file in logs/.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..security.guard import scrub
from .db import Database, now_iso, utcnow


class ActivityLog:
    def __init__(self, db: Database, logs_dir: Path):
        self.db = db
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def record(self, agent: str, action: str, ref: str | None = None, status: str = "ok", note: str = "") -> None:
        note, _ = scrub(note or "")
        note = note[:300]
        ts = now_iso()
        self.db.execute(
            "INSERT INTO activity(ts, agent, action, ref, status, note) VALUES(?,?,?,?,?,?)",
            (ts, agent, action, ref, status, note),
        )
        line = {"ts": ts, "agent": agent, "action": action, "ref": ref, "status": status, "note": note}
        path = self.logs_dir / f"activity-{utcnow():%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def recent(self, agent: str | None = None, limit: int = 20) -> list[dict]:
        if agent:
            return self.db.query(
                "SELECT * FROM activity WHERE agent = ? ORDER BY id DESC LIMIT ?", (agent, limit)
            )
        return self.db.query("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))
