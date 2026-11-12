"""Runs specialist tasks in the background, one queue for the whole office.

When the Director hands out a task, it lands here. The dispatcher starts the
right agent, records the cost, updates the task board, and tells you the
result, a question, or that a preview is waiting for your approval.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .agents.base import RunContext, friendly_error
from .core.tasks import FAILED, TODO

if TYPE_CHECKING:
    from .app import App

log = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, app: "App", workers: int = 2):
        self.app = app
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.workers = workers
        self._worker_tasks: list[asyncio.Task] = []

    def enqueue(self, task_id: int) -> None:
        self.queue.put_nowait(task_id)

    async def start(self) -> None:
        for task_id in self.app.tasks.requeue_interrupted():
            log.info("Re-queued interrupted task #%s", task_id)
        for task in self.app.tasks.list(TODO, limit=100):
            self.enqueue(task["id"])
        self._worker_tasks = [asyncio.create_task(self._worker(i)) for i in range(self.workers)]

    async def stop(self) -> None:
        for worker in self._worker_tasks:
            worker.cancel()

    async def _worker(self, index: int) -> None:
        while True:
            task_id = await self.queue.get()
            try:
                await self.run_task(task_id)
            except Exception:
                log.exception("Task #%s crashed", task_id)
                self.app.tasks.finish(task_id, "Unexpected error. See logs/maai.log", status=FAILED)
            finally:
                self.queue.task_done()

    async def notify(self, text: str, **extra) -> None:
        await self.app.bus.publish("notify.owner", {"text": text, **extra})

    def _task_prompt(self, task: dict) -> str:
        notes = self.app.tasks.notes(task["id"])
        lines = [
            f"Task #{task['id']}: {task['title']}",
            f"Details: {task['details'] or '(none)'}",
            f"Mode: {'PRACTICE (dry-run)' if self.app.config.dry_run else 'LIVE'}",
        ]
        if notes:
            lines.append("Notes and answers so far (newest last):")
            lines.extend(f"- {n['author']}: {n['text']}" for n in notes[-10:])
        return "\n".join(lines)

    async def run_task(self, task_id: int) -> None:
        tasks = self.app.tasks
        task = tasks.get(task_id)
        if not task or task["status"] != TODO:
            return
        spec = self.app.registry.get(task["agent"])
        if spec is None or not spec.accepts_tasks:
            tasks.finish(task_id, f"No agent called '{task['agent']}'", status=FAILED)
            return
        if not self.app.budget.allowed(spec.name):
            tasks.wait_for_owner(task_id, "Paused: this month's AI budget is used up. Raise "
                                          "budget.monthly_limit_usd in config/settings.yaml, or wait for next month.")
            await self.notify(f"⏸️ {spec.title} paused task #{task_id}: monthly AI budget reached.")
            return

        tasks.start(task_id)
        ctx = RunContext(app=self.app, agent=spec.name, task_id=task_id)
        result = await self.app.runner.run(spec, self._task_prompt(task), ctx)
        self.app.budget.record(spec.name, result.cost_usd, result.model, result.usage, task_id)

        label = f"{spec.emoji} {spec.title} · task #{task_id}"
        if result.is_error:
            tasks.finish(task_id, f"Error: {result.error}", status=FAILED)
            self.app.activity.record(spec.name, "task_failed", ref=f"task#{task_id}", status="error")
            await self.notify(f"⚠️ {label} didn't finish. {friendly_error(result.error)}", task_id=task_id,
                              agent=spec.name)
        elif ctx.asked_owner:
            question = tasks.get(task_id)["question"]
            await self.notify(f"❓ {label}\n{question}", task_id=task_id, agent=spec.name)
        elif ctx.requested_approval:
            pass  # the approval gate already sent the preview with ✅ / ❌ buttons
        else:
            tasks.finish(task_id, result.text)
            await self.notify(f"✅ {label}\n{result.text}", task_id=task_id, agent=spec.name)
        await self.check_budget_warnings()

    async def check_budget_warnings(self) -> None:
        for level in self.app.budget.new_warnings():
            status = self.app.budget.status()
            if level >= 1.0:
                text = (f"🛑 AI spending reached your monthly limit: ${status['spent_usd']:.2f} of "
                        f"${status['limit_usd']:.2f}. Only the Director and invoices keep working.")
            else:
                text = (f"💰 Heads-up: AI spending is at {status['percent']:.0f}% of your monthly limit "
                        f"(${status['spent_usd']:.2f} of ${status['limit_usd']:.2f}).")
            await self.notify(text)
