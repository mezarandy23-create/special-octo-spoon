"""The Director: your single point of contact.

It reads your message (English or Spanish), answers simple questions from
the task board, and hands real work to the right specialist as a task.

It has NO tool to approve anything and NO tool to send anything. Approvals
only happen when you tap ✅ (or type "approve N" yourself).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any
from zoneinfo import ZoneInfo

from claude_agent_sdk import tool

from ..core.tasks import CANCELLED, OPEN_STATUSES, WAITING
from ..security.guard import scrub
from .base import RunContext, friendly_error, text_result

if TYPE_CHECKING:
    from ..app import App


def _task_line(t: dict[str, Any]) -> str:
    extra = f" | question: {t['question']}" if t.get("question") else ""
    return f"#{t['id']} [{t['status']}] {t['agent']}: {t['title']} ({t['progress']}%){extra}"


def director_tools(ctx: RunContext) -> list[Any]:
    app = ctx.app
    tasks = app.tasks
    specialists = {name: spec for name, spec in app.registry.items() if spec.accepts_tasks}
    roster = ", ".join(specialists)

    @tool("assign_task",
          f"Give a new task to a specialist agent. Available agents: {roster}. Put every detail the owner gave "
          "into `details` (names, dates, hours, amounts, emails); the specialist only sees this task.",
          {"agent": Annotated[str, f"One of: {roster}"],
           "title": Annotated[str, "Short title, e.g. 'Invoice for Berry College week of Nov 3'"],
           "details": Annotated[str, "All the information needed, in plain words"]})
    async def assign_task(args: dict[str, Any]) -> dict[str, Any]:
        agent = args["agent"].strip().lower()
        if agent not in specialists:
            return text_result(f"Unknown agent '{agent}'. Use one of: {roster}", is_error=True)
        task = tasks.create(agent, args["title"], args["details"], source="director")
        app.dispatcher.enqueue(task["id"])
        return text_result(f"Task #{task['id']} given to {specialists[agent].title}.")

    @tool("list_tasks", "See the task board. status: open, todo, in_progress, waiting_for_me, done or all.",
          {"status": str})
    async def list_tasks(args: dict[str, Any]) -> dict[str, Any]:
        status = args.get("status", "open")
        rows = tasks.list(None if status == "all" else status, limit=25)
        return text_result("\n".join(_task_line(t) for t in rows) or "No tasks.")

    @tool("get_task", "Full details of one task: notes, questions, result, and approvals.", {"task_id": int})
    async def get_task(args: dict[str, Any]) -> dict[str, Any]:
        task = tasks.get(args["task_id"])
        if not task:
            return text_result("No such task.", is_error=True)
        approvals = app.db.query("SELECT id, title, status FROM approvals WHERE task_id = ?", (task["id"],))
        info = {"task": task, "notes": tasks.notes(task["id"]), "approvals": approvals}
        return text_result(json.dumps(info, default=str))

    @tool("continue_task",
          "Send the owner's answer or requested changes to a task that is waiting, and restart it.",
          {"task_id": int, "info": Annotated[str, "The owner's answer or the changes they want"]})
    async def continue_task(args: dict[str, Any]) -> dict[str, Any]:
        task = tasks.get(args["task_id"])
        if not task or task["status"] not in OPEN_STATUSES:
            return text_result("That task is not open.", is_error=True)
        for pending in app.db.query("SELECT id FROM approvals WHERE task_id = ? AND status = 'pending'", (task["id"],)):
            await app.gate.reject(pending["id"], "Replaced by a new version")
        tasks.reopen(task["id"], args["info"])
        app.dispatcher.enqueue(task["id"])
        return text_result(f"Task #{task['id']} restarted with the new info.")

    @tool("cancel_task", "Cancel a task the owner no longer wants. Any preview waiting for approval is dropped.",
          {"task_id": int})
    async def cancel_task(args: dict[str, Any]) -> dict[str, Any]:
        task = tasks.get(args["task_id"])
        if not task:
            return text_result("No such task.", is_error=True)
        for pending in app.db.query("SELECT id FROM approvals WHERE task_id = ? AND status = 'pending'", (task["id"],)):
            await app.gate.reject(pending["id"], "Task cancelled")
        tasks.finish(task["id"], "Cancelled by owner", status=CANCELLED)
        return text_result(f"Task #{task['id']} cancelled.")

    @tool("office_status", "Who is working on what, what is waiting for the owner, and AI spending this month.", {})
    async def office_status(args: dict[str, Any]) -> dict[str, Any]:
        from ..status import agent_statuses

        info = {"agents": agent_statuses(app), "budget": app.budget.status(),
                "pending_approvals": [{"id": a["id"], "title": a["title"]} for a in app.gate.pending()]}
        return text_result(json.dumps(info, default=str))

    @tool("list_unpaid_invoices", "Quick read-only list of unpaid or overdue invoices.", {"overdue_only": bool})
    async def list_unpaid_invoices(args: dict[str, Any]) -> dict[str, Any]:
        rows = app.invoices.list_invoices("overdue" if args.get("overdue_only") else "unpaid")
        return text_result(json.dumps(rows) if rows else "No unpaid invoices.")

    return [assign_task, list_tasks, get_task, continue_task, cancel_task, office_status, list_unpaid_invoices]


class Director:
    def __init__(self, app: "App"):
        self.app = app

    def _history(self, limit: int = 12) -> str:
        rows = self.app.db.query("SELECT role, text FROM chat ORDER BY id DESC LIMIT ?", (limit,))
        return "\n".join(f"{r['role']}: {r['text']}" for r in reversed(rows))

    def _save(self, role: str, text: str) -> None:
        from ..core.db import now_iso

        self.app.db.execute("INSERT INTO chat(ts, role, text) VALUES(?,?,?)", (now_iso(), role, text[:3000]))

    def _context(self) -> str:
        now = datetime.now(ZoneInfo(self.app.config.timezone))
        mode = "PRACTICE (dry-run: nothing reaches real clients)" if self.app.config.dry_run else "LIVE"
        waiting = self.app.tasks.list(WAITING, limit=10)
        lines = [f"Now: {now:%A %Y-%m-%d %H:%M} ({self.app.config.timezone}). Mode: {mode}."]
        if waiting:
            lines.append("Tasks waiting for the owner:")
            lines.extend(_task_line(t) for t in waiting)
        return "\n".join(lines)

    async def handle(self, text: str) -> str:
        """Answer one message from the owner."""
        clean, removed = scrub(text.strip())
        if not clean:
            return "?"
        history = self._history()
        self._save("owner", clean)

        prompt = (
            f"{self._context()}\n\n"
            f"Recent conversation:\n{history or '(none)'}\n\n"
            f"Owner's new message:\n{clean}"
        )
        ctx = RunContext(app=self.app, agent="director")
        result = await self.app.runner.run(self.app.registry["director"], prompt, ctx)
        self.app.budget.record("director", result.cost_usd, result.model, result.usage)
        await self.app.dispatcher.check_budget_warnings()

        if result.is_error:
            self.app.activity.record("director", "error", status="error", note=(result.error or "")[:120])
            reply = "Sorry, I couldn't answer that. " + friendly_error(result.error)
        else:
            reply = result.text or "Done."
        self._save("director", reply)
        if removed:
            reply += f"\n\n🔒 I removed a {', '.join(removed)} from your message. I never store those."
        return reply
