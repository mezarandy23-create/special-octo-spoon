"""The approval gate: the ONLY place where things leave the office.

How it works:
  1. An agent prepares something (an invoice email, a reminder, later a post)
     and calls `request(...)`. Nothing is sent. The task moves to
     "Waiting for Me" and you get a preview with ✅ Approve / ❌ Reject.
  2. When you approve, the gate runs the matching "executor": the small piece
     of code that actually sends, publishes or posts.
  3. Agents are never given executors as tools, so an agent cannot send
     anything by itself, even by mistake.

Each approval can only run once. Tapping ✅ twice doesn't send twice.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from .activity import ActivityLog
from .bus import EventBus
from .db import Database, now_iso
from .tasks import DONE, TaskBoard

log = logging.getLogger(__name__)

Executor = Callable[[dict[str, Any]], Awaitable[str]]

PENDING = "pending"
EXECUTING = "executing"
APPROVED_DONE = "done"
REJECTED = "rejected"
FAILED = "failed"


class ApprovalGate:
    def __init__(self, db: Database, bus: EventBus, tasks: TaskBoard, activity: ActivityLog):
        self.db = db
        self.bus = bus
        self.tasks = tasks
        self.activity = activity
        self._executors: dict[str, Executor] = {}

    def register_executor(self, kind: str, executor: Executor) -> None:
        self._executors[kind] = executor

    # ---- create -----------------------------------------------------------
    async def request(self, *, agent: str, kind: str, title: str, preview: str, payload: dict[str, Any],
                      task_id: int | None = None, attachment: str | None = None) -> dict[str, Any]:
        if kind not in self._executors:
            raise ValueError(f"No executor registered for approval kind '{kind}'")
        cur = self.db.execute(
            "INSERT INTO approvals(task_id, agent, kind, title, preview, payload, attachment, status, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (task_id, agent, kind, title, preview, json.dumps(payload), attachment, PENDING, now_iso()),
        )
        approval = self.get(cur.lastrowid)
        if task_id:
            self.tasks.wait_for_owner(task_id, f"Approval needed: {title}")
        self.activity.record(agent, "approval_requested", ref=f"approval#{approval['id']}", note=kind)
        await self.bus.publish("approval.created", {"approval": approval})
        return approval

    # ---- read -------------------------------------------------------------
    def get(self, approval_id: int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if row:
            row["payload"] = json.loads(row["payload"])
        return row

    def pending(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM approvals WHERE status = ? ORDER BY id", (PENDING,))
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    # ---- decide -----------------------------------------------------------
    def _claim(self, approval_id: int, new_status: str) -> bool:
        """Atomically move pending -> new_status. False if already decided."""
        cur = self.db.execute(
            "UPDATE approvals SET status = ?, decided_at = ? WHERE id = ? AND status = ?",
            (new_status, now_iso(), approval_id, PENDING),
        )
        return cur.rowcount == 1

    async def approve(self, approval_id: int) -> str:
        if not self._claim(approval_id, EXECUTING):
            return "That one was already handled."
        approval = self.get(approval_id)
        executor = self._executors.get(approval["kind"])
        try:
            if executor is None:
                raise RuntimeError(f"No executor for {approval['kind']}")
            result = await executor(approval["payload"])
            status = APPROVED_DONE
        except Exception as exc:  # report, never retry silently
            log.exception("Approval %s failed", approval_id)
            result = f"Failed: {exc}"
            status = FAILED
        self.db.execute("UPDATE approvals SET status = ?, result = ? WHERE id = ?", (status, result[:1000], approval_id))
        self.activity.record(approval["agent"], "approved_and_executed" if status == APPROVED_DONE else "execution_failed",
                             ref=f"approval#{approval_id}", status="ok" if status == APPROVED_DONE else "error",
                             note=approval["kind"])
        self._settle_task(approval, status == APPROVED_DONE, result)
        await self.bus.publish("approval.decided", {"approval": self.get(approval_id)})
        return result

    async def reject(self, approval_id: int, reason: str = "") -> str:
        if not self._claim(approval_id, REJECTED):
            return "That one was already handled."
        approval = self.get(approval_id)
        self.db.execute("UPDATE approvals SET result = ? WHERE id = ?", (reason or "Rejected", approval_id))
        self.activity.record(approval["agent"], "rejected", ref=f"approval#{approval_id}", note=approval["kind"])
        if approval.get("task_id"):
            self.tasks.add_note(approval["task_id"], "owner", f"Rejected: {reason or 'no reason given'}")
            self.tasks.wait_for_owner(
                approval["task_id"],
                f"You rejected '{approval['title']}'. Tell me what to change, or say cancel.",
            )
        await self.bus.publish("approval.decided", {"approval": self.get(approval_id)})
        return "Rejected. Nothing was sent. Tell me what to change, or say cancel."

    def _settle_task(self, approval: dict[str, Any], ok: bool, result: str) -> None:
        task_id = approval.get("task_id")
        if not task_id:
            return
        still_pending = self.db.query_one(
            "SELECT COUNT(*) AS n FROM approvals WHERE task_id = ? AND status = ?", (task_id, PENDING)
        )["n"]
        if ok and still_pending == 0:
            self.tasks.finish(task_id, result, status=DONE)
        elif not ok:
            self.tasks.wait_for_owner(task_id, f"Sending failed: {result}")
