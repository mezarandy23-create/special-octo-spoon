"""Wires the office together. One `App` object holds every shared part."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agents.base import AgentRunner, AgentSpec, ClaudeAgentRunner
from .agents.director import Director
from .agents.invoice.service import SEND_INVOICE, SEND_REMINDER, InvoiceService
from .agents.registry import build_registry
from .config import Config
from .core.activity import ActivityLog
from .core.approvals import ApprovalGate
from .core.budget import Budget
from .core.bus import EventBus
from .core.db import Database
from .core.tasks import TaskBoard
from .dispatcher import Dispatcher
from .integrations.workspace import Workspace, open_workspace


@dataclass
class App:
    config: Config
    db: Database
    bus: EventBus
    activity: ActivityLog
    tasks: TaskBoard
    gate: ApprovalGate
    budget: Budget
    workspace: Workspace
    registry: dict[str, AgentSpec] = field(default_factory=dict)
    runner: AgentRunner | Any = None
    invoices: InvoiceService | Any = None
    dispatcher: Dispatcher | Any = None
    director: Director | Any = None


def build_app(config: Config, workspace: Workspace | None = None, runner: AgentRunner | None = None,
              db_path: str | None = None) -> App:
    db = Database(db_path or config.data_dir / "maai.db")
    bus = EventBus()
    activity = ActivityLog(db, config.logs_dir)
    tasks = TaskBoard(db, bus, activity)
    gate = ApprovalGate(db, bus, tasks, activity)
    app = App(
        config=config, db=db, bus=bus, activity=activity, tasks=tasks, gate=gate,
        budget=Budget(db, config.section("budget")),
        workspace=workspace or open_workspace(config),
    )
    app.registry = build_registry()
    app.invoices = InvoiceService(app)
    app.runner = runner or ClaudeAgentRunner(app)
    app.dispatcher = Dispatcher(app)
    app.director = Director(app)

    # The only code allowed to send anything, registered with the approval gate:
    gate.register_executor(SEND_INVOICE, app.invoices.send_invoice)
    gate.register_executor(SEND_REMINDER, app.invoices.send_reminder)
    return app
