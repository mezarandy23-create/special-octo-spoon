"""The cost meter.

Every AI call reports what it cost. This module adds it up per month,
warns you at 50% / 80% / 95% of your limit (once each), and at 100% lets
only the "essential" agents keep working (Director and invoices by default).
"""

from __future__ import annotations

from typing import Any

from .db import Database, now_iso, utcnow


class Budget:
    def __init__(self, db: Database, settings: dict[str, Any]):
        self.db = db
        self.limit = float(settings.get("monthly_limit_usd", 25))
        self.console_limit = float(settings.get("console_limit_usd", 0) or 0)
        self.warn_at = sorted(float(x) for x in settings.get("warn_at", [0.5, 0.8, 0.95]))
        self.per_task_max = float(settings.get("per_task_max_usd", 0.5))
        self.essential = set(settings.get("essential_agents", ["director", "invoice"]))

    @staticmethod
    def month_key() -> str:
        return utcnow().strftime("%Y-%m")

    def record(self, agent: str, usd: float, model: str | None = None, usage: dict | None = None,
               task_id: int | None = None) -> None:
        usage = usage or {}
        self.db.execute(
            "INSERT INTO costs(ts, month, agent, model, usd, input_tokens, output_tokens, cache_read_tokens, task_id) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                now_iso(), self.month_key(), agent, model, float(usd or 0),
                usage.get("input_tokens"), usage.get("output_tokens"),
                usage.get("cache_read_input_tokens"), task_id,
            ),
        )

    def spent(self, month: str | None = None) -> float:
        row = self.db.query_one("SELECT COALESCE(SUM(usd), 0) AS total FROM costs WHERE month = ?",
                                (month or self.month_key(),))
        return float(row["total"]) if row else 0.0

    def by_agent(self, month: str | None = None) -> dict[str, float]:
        rows = self.db.query(
            "SELECT agent, SUM(usd) AS total FROM costs WHERE month = ? GROUP BY agent ORDER BY total DESC",
            (month or self.month_key(),),
        )
        return {row["agent"]: round(float(row["total"]), 4) for row in rows}

    def status(self) -> dict[str, Any]:
        spent = self.spent()
        pct = (spent / self.limit) if self.limit else 0.0
        return {
            "month": self.month_key(),
            "spent_usd": round(spent, 2),
            "limit_usd": self.limit,
            "console_limit_usd": self.console_limit,
            "percent": round(pct * 100, 1),
            "over_limit": pct >= 1.0,
            "by_agent": self.by_agent(),
        }

    def new_warnings(self) -> list[float]:
        """Thresholds crossed since the last check (each one reported once a month)."""
        key = f"budget_warned:{self.month_key()}"
        warned = set(self.db.kv_get(key, []))
        pct = self.spent() / self.limit if self.limit else 0
        crossed = [t for t in self.warn_at + [1.0] if pct >= t and t not in warned]
        if crossed:
            self.db.kv_set(key, sorted(warned | set(crossed)))
        return crossed

    def allowed(self, agent: str) -> bool:
        if agent in self.essential:
            return True
        return self.spent() < self.limit
