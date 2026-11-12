"""Daily routines (times are in your timezone, see config/settings.yaml):
  * backup_time          nightly backup
  * reminder_check_time  finds overdue invoices and asks the Invoice Agent
                         to draft a polite reminder (you approve before it goes)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..agents.invoice.models import money
from .backup import run_backup

if TYPE_CHECKING:
    from ..app import App

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, app: "App"):
        self.app = app
        sched = app.config.section("schedule")
        self.jobs = {
            "backup": (sched.get("backup_time", "02:00"), self.backup),
            "reminders": (sched.get("reminder_check_time", "09:00"), self.reminders),
        }
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Scheduler tick failed")
            await asyncio.sleep(60)

    async def tick(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(ZoneInfo(self.app.config.timezone))
        ran = []
        for name, (hhmm, job) in self.jobs.items():
            key = f"job_last_run:{name}"
            if now.strftime("%H:%M") >= hhmm and self.app.db.kv_get(key) != now.date().isoformat():
                self.app.db.kv_set(key, now.date().isoformat())
                await job()
                ran.append(name)
        return ran

    async def backup(self) -> None:
        try:
            name = await asyncio.to_thread(run_backup, self.app)
            log.info("Backup done: %s", name)
        except Exception as exc:
            log.exception("Backup failed")
            self.app.activity.record("system", "backup_failed", status="error", note=type(exc).__name__)
            await self.app.bus.publish("notify.owner", {"text": f"⚠️ Tonight's backup failed ({type(exc).__name__}). "
                                                                 "I'll try again tomorrow; details in logs/maai.log."})

    async def reminders(self) -> None:
        due = self.app.invoices.due_for_reminder()
        open_titles = {t["title"] for t in self.app.tasks.list("open", agent="invoice", limit=100)}
        for inv in due:
            title = f"Payment reminder for {inv['number']}"
            if title in open_titles:
                continue
            details = (f"Invoice {inv['number']} ({money(inv['total_cents'])}) was due {inv['due_date']} and is "
                       f"still unpaid. Reminders already sent: {inv['reminders_sent']}. Draft a polite reminder.")
            task = self.app.tasks.create("invoice", title, details, source="schedule")
            self.app.dispatcher.enqueue(task["id"])
