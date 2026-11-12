"""The task board.

Columns (these match the Virtual Office board):
  todo            -> To Do
  in_progress     -> In Progress
  waiting_for_me  -> Waiting for Me (a question or an approval for you)
  done            -> Done
Plus two end states that also show under Done: failed, cancelled.
"""

from __future__ import annotations

from typing import Any

from ..security.guard import scrub
from .activity import ActivityLog
from .bus import EventBus
from .db import Database, now_iso

TODO = "todo"
IN_PROGRESS = "in_progress"
WAITING = "waiting_for_me"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
OPEN_STATUSES = (TODO, IN_PROGRESS, WAITING)
ALL_STATUSES = (TODO, IN_PROGRESS, WAITING, DONE, FAILED, CANCELLED)


class TaskBoard:
    def __init__(self, db: Database, bus: EventBus, activity: ActivityLog):
        self.db = db
        self.bus = bus
        self.activity = activity

    # ---- create / read ----------------------------------------------------
    def create(self, agent: str, title: str, details: str = "", source: str = "owner",
               parent_id: int | None = None) -> dict[str, Any]:
        title, _ = scrub(title.strip())
        details, _ = scrub((details or "").strip())
        ts = now_iso()
        cur = self.db.execute(
            "INSERT INTO tasks(agent, title, details, status, source, parent_id, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (agent, title[:200], details[:4000], TODO, source, parent_id, ts, ts),
        )
        task = self.get(cur.lastrowid)
        self.activity.record(agent, "task_created", ref=f"task#{task['id']}", note=title[:80])
        self.bus.publish_soon("task.updated", {"task": task})
        return task

    def get(self, task_id: int) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def list(self, status: str | None = None, agent: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list[Any] = []
        if status == "open":
            sql += f" AND status IN ({','.join('?' * len(OPEN_STATUSES))})"
            params.extend(OPEN_STATUSES)
        elif status:
            sql += " AND status = ?"
            params.append(status)
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self.db.query(sql, tuple(params))

    def notes(self, task_id: int) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM task_notes WHERE task_id = ? ORDER BY id", (task_id,))

    # ---- updates ----------------------------------------------------------
    def _update(self, task_id: int, **fields: Any) -> dict[str, Any] | None:
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {cols} WHERE id = ?", (*fields.values(), task_id))
        task = self.get(task_id)
        self.bus.publish_soon("task.updated", {"task": task})
        return task

    def start(self, task_id: int) -> dict[str, Any] | None:
        return self._update(task_id, status=IN_PROGRESS, progress=5, question=None)

    def set_progress(self, task_id: int, percent: int, note: str = "") -> dict[str, Any] | None:
        percent = max(0, min(100, int(percent)))
        if note:
            self.add_note(task_id, "agent", note)
        return self._update(task_id, progress=percent)

    def wait_for_owner(self, task_id: int, question: str) -> dict[str, Any] | None:
        question, _ = scrub(question)
        self.add_note(task_id, "agent", f"Question: {question}")
        return self._update(task_id, status=WAITING, question=question[:1000])

    def finish(self, task_id: int, result: str, status: str = DONE) -> dict[str, Any] | None:
        result, _ = scrub(result or "")
        fields: dict[str, Any] = {"status": status, "result": result[:2000], "question": None}
        if status == DONE:
            fields["progress"] = 100
        task = self._update(task_id, **fields)
        if task:
            self.activity.record(task["agent"], f"task_{status}", ref=f"task#{task_id}")
        return task

    def reopen(self, task_id: int, note: str, author: str = "owner") -> dict[str, Any] | None:
        """Put a task back in To Do with new info (an answer or requested changes)."""
        self.add_note(task_id, author, note)
        return self._update(task_id, status=TODO, question=None)

    def add_note(self, task_id: int, author: str, text: str) -> None:
        text, _ = scrub(text or "")
        self.db.execute(
            "INSERT INTO task_notes(task_id, ts, author, text) VALUES(?,?,?,?)",
            (task_id, now_iso(), author, text[:2000]),
        )

    def requeue_interrupted(self) -> list[int]:
        """After a restart, tasks that were mid-way go back to To Do."""
        rows = self.db.query("SELECT id FROM tasks WHERE status = ?", (IN_PROGRESS,))
        for row in rows:
            self._update(row["id"], status=TODO)
        return [row["id"] for row in rows]
