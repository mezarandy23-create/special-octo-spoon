"""Live status of each agent: working, waiting for you, done, or idle.

Used by Telegram's /status and, later, by the Virtual Office.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from .core.tasks import DONE, IN_PROGRESS, WAITING

if TYPE_CHECKING:
    from .app import App

RECENT_DONE = timedelta(minutes=15)


def agent_statuses(app: "App") -> list[dict[str, Any]]:
    out = []
    for name, spec in app.registry.items():
        working = app.tasks.list(IN_PROGRESS, agent=name, limit=1)
        waiting = app.tasks.list(WAITING, agent=name, limit=5)
        pending = app.db.query_one("SELECT COUNT(*) AS n FROM approvals WHERE agent = ? AND status = 'pending'",
                                   (name,))["n"]
        last_done = app.tasks.list(DONE, agent=name, limit=1)
        if working:
            state, current = "working", working[0]
        elif waiting or pending:
            state, current = "waiting", (waiting[0] if waiting else None)
        elif last_done and datetime.now(timezone.utc) - datetime.fromisoformat(last_done[0]["updated_at"]) < RECENT_DONE:
            state, current = "done", last_done[0]
        else:
            state, current = "idle", None
        out.append({
            "agent": name, "title": spec.title, "role": spec.role, "emoji": spec.emoji, "state": state,
            "task": {"id": current["id"], "title": current["title"], "progress": current["progress"]} if current else None,
            "pending_approvals": pending,
        })
    return out


STATE_ICONS = {"working": "🟢 working", "waiting": "🟡 waiting for you", "done": "✅ done", "idle": "⚪ idle"}


def status_text(app: "App") -> str:
    lines = []
    for s in agent_statuses(app):
        line = f"{s['emoji']} {s['title']}: {STATE_ICONS[s['state']]}"
        if s["task"]:
            line += f"\n    #{s['task']['id']} {s['task']['title']} ({s['task']['progress']}%)"
        lines.append(line)
    b = app.budget.status()
    lines.append(f"\n💰 AI this month: ${b['spent_usd']:.2f} of ${b['limit_usd']:.2f} ({b['percent']:.0f}%)")
    lines.append("Mode: PRACTICE (dry-run)" if app.config.dry_run else "Mode: LIVE")
    return "\n".join(lines)
