"""Invoice data and math.

All money is handled in cents (whole numbers) so totals never have
rounding errors. The AI never does the math; this file does.

Two kinds of invoices fit your template:
  labor  weekly labor hours: workers x days x hourly rate (+ gas, supplies)
  flat   a fixed price for listed services (e.g. "Deep clean - $250")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABELS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}


def to_cents(value: Any) -> int:
    if value in (None, ""):
        return 0
    amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def hours_text(hours: float) -> str:
    if not hours:
        return ""
    return f"{hours:g}"


@dataclass
class Worker:
    name: str
    hours: dict[str, float] = field(default_factory=dict)  # {"mon": 8, ...}

    @property
    def total(self) -> float:
        return round(sum(float(self.hours.get(d, 0) or 0) for d in DAYS), 2)


@dataclass
class Service:
    description: str
    amount_cents: int


@dataclass
class InvoiceData:
    number: str
    kind: str                      # "labor" or "flat"
    client_name: str
    client_email: str
    client_address: str
    project: str
    issue_date: date
    due_date: date
    sent_by: str
    rate_cents: int
    po_number: str = ""
    week_start: date | None = None
    workers: list[Worker] = field(default_factory=list)
    overtime_hours: float = 0.0
    overtime_multiplier: Decimal = Decimal("1.5")
    gas_cents: int = 0
    supplies_cents: int = 0
    services: list[Service] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ---- labor math -----------------------------------------------------
    @property
    def labor_hours(self) -> float:
        return round(sum(w.total for w in self.workers), 2)

    def day_totals(self) -> dict[str, float]:
        return {d: round(sum(float(w.hours.get(d, 0) or 0) for w in self.workers), 2) for d in DAYS}

    @property
    def regular_hours(self) -> float:
        return round(max(self.labor_hours - self.overtime_hours, 0), 2)

    @property
    def labor_cents(self) -> int:
        regular = Decimal(str(self.regular_hours)) * self.rate_cents
        overtime = Decimal(str(self.overtime_hours)) * self.rate_cents * self.overtime_multiplier
        return int((regular + overtime).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def services_cents(self) -> int:
        return sum(s.amount_cents for s in self.services)

    @property
    def subtotal_cents(self) -> int:
        base = self.labor_cents if self.kind == "labor" else self.services_cents
        return base + self.gas_cents + self.supplies_cents

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents

    @property
    def week_end(self) -> date | None:
        return self.week_start + timedelta(days=6) if self.week_start else None

    def week_label(self) -> str:
        if not self.week_start:
            return ""
        end = self.week_end
        return f"{self.week_start:%B} {self.week_start.day}, {self.week_start.year} — {end:%B} {end.day}, {end.year}"

    def day_label(self, day: str) -> str:
        if not self.week_start:
            return DAY_LABELS[day]
        d = self.week_start + timedelta(days=DAYS.index(day))
        return f"{DAY_LABELS[day]} {d:%m/%d}"

    # ---- checks ---------------------------------------------------------
    def problems(self) -> list[str]:
        issues = []
        if self.kind not in ("labor", "flat"):
            issues.append("kind must be 'labor' or 'flat'")
        if self.kind == "labor":
            if not self.workers:
                issues.append("a labor invoice needs at least one worker with hours")
            if len(self.workers) > 10:
                issues.append("the template has room for 10 workers")
            if not self.week_start:
                issues.append("a labor invoice needs the week start date (Monday)")
            elif self.week_start.weekday() != 0:
                issues.append("week_start must be a Monday")
            if self.overtime_hours > self.labor_hours:
                issues.append("overtime hours are more than total hours")
        if self.kind == "flat" and not self.services:
            issues.append("a flat invoice needs at least one service with a price")
        if self.total_cents <= 0:
            issues.append("the total is $0.00")
        if not self.client_email or "@" not in self.client_email:
            issues.append("client email is missing")
        return issues

    def summary_lines(self) -> list[str]:
        """Plain-text preview shown to the owner before approval."""
        lines = [
            f"Invoice {self.number}",
            f"Client: {self.client_name} <{self.client_email}>",
            f"Project: {self.project}",
            f"Date: {self.issue_date:%m/%d/%Y}   Due: {self.due_date:%m/%d/%Y}",
        ]
        if self.po_number:
            lines.append(f"PO #: {self.po_number}")
        if self.kind == "labor":
            lines.append(f"Week: {self.week_label()}")
            for w in self.workers:
                lines.append(f"  • {w.name}: {w.total:g} h")
            ot = f" (incl. {self.overtime_hours:g} OT)" if self.overtime_hours else ""
            lines.append(f"Labor: {self.labor_hours:g} h{ot} × {money(self.rate_cents)}/h = {money(self.labor_cents)}")
        else:
            for s in self.services:
                lines.append(f"  • {s.description}: {money(s.amount_cents)}")
        if self.gas_cents:
            lines.append(f"Gas / fuel: {money(self.gas_cents)}")
        if self.supplies_cents:
            lines.append(f"Supplies: {money(self.supplies_cents)}")
        lines.append(f"TOTAL DUE: {money(self.total_cents)}")
        return lines

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number, "kind": self.kind, "client_name": self.client_name,
            "client_email": self.client_email, "client_address": self.client_address,
            "project": self.project, "issue_date": self.issue_date.isoformat(),
            "due_date": self.due_date.isoformat(), "sent_by": self.sent_by,
            "rate_cents": self.rate_cents, "po_number": self.po_number,
            "week_start": self.week_start.isoformat() if self.week_start else None,
            "workers": [{"name": w.name, "hours": w.hours} for w in self.workers],
            "overtime_hours": self.overtime_hours, "overtime_multiplier": str(self.overtime_multiplier),
            "gas_cents": self.gas_cents, "supplies_cents": self.supplies_cents,
            "services": [{"description": s.description, "amount_cents": s.amount_cents} for s in self.services],
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "InvoiceData":
        return cls(
            number=data["number"], kind=data["kind"], client_name=data["client_name"],
            client_email=data["client_email"], client_address=data.get("client_address", ""),
            project=data["project"], issue_date=date.fromisoformat(data["issue_date"]),
            due_date=date.fromisoformat(data["due_date"]), sent_by=data.get("sent_by", ""),
            rate_cents=int(data["rate_cents"]), po_number=data.get("po_number", ""),
            week_start=date.fromisoformat(data["week_start"]) if data.get("week_start") else None,
            workers=[Worker(w["name"], dict(w.get("hours", {}))) for w in data.get("workers", [])],
            overtime_hours=float(data.get("overtime_hours", 0)),
            overtime_multiplier=Decimal(str(data.get("overtime_multiplier", "1.5"))),
            gas_cents=int(data.get("gas_cents", 0)), supplies_cents=int(data.get("supplies_cents", 0)),
            services=[Service(s["description"], int(s["amount_cents"])) for s in data.get("services", [])],
            notes=list(data.get("notes", [])),
        )
