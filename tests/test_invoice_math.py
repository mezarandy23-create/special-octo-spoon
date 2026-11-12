from datetime import date
from decimal import Decimal

from maai.agents.invoice.models import InvoiceData, Service, Worker, money, to_cents


def make(**overrides):
    base = dict(
        number="INV-2026-001", kind="labor", client_name="Berry College", client_email="ap@berry.example",
        client_address="", project="Amber Grace Hall", issue_date=date(2026, 11, 10), due_date=date(2026, 11, 24),
        sent_by="MAAI", rate_cents=2000, week_start=date(2026, 11, 2),
        workers=[Worker("Ana", {d: 8 for d in ("mon", "tue", "wed", "thu", "fri")}),
                 Worker("Luis", {"mon": 6, "tue": 6, "wed": 6})],
    )
    base.update(overrides)
    return InvoiceData(**base)


def test_money_helpers():
    assert to_cents("$1,180.50") == 118050
    assert to_cents(19.999) == 2000
    assert money(118050) == "$1,180.50"


def test_labor_totals():
    inv = make(gas_cents=2000)
    assert inv.labor_hours == 58
    assert inv.day_totals()["mon"] == 14
    assert inv.labor_cents == 116000
    assert inv.total_cents == 118000
    assert inv.problems() == []
    assert inv.week_label() == "November 2, 2026 — November 8, 2026"
    assert inv.day_label("wed") == "Wed 11/04"


def test_overtime_is_paid_at_multiplier():
    inv = make(overtime_hours=2, overtime_multiplier=Decimal("1.5"))
    # 56 regular h x $20 + 2 OT h x $30
    assert inv.labor_cents == 56 * 2000 + 2 * 3000


def test_flat_invoice():
    inv = make(kind="flat", workers=[], week_start=None,
               services=[Service("Deep clean 3BR", 25000), Service("Inside oven", 4000)], supplies_cents=1500)
    assert inv.total_cents == 30500
    assert inv.problems() == []


def test_problems_are_reported():
    assert "client email is missing" in make(client_email="").problems()
    assert "week_start must be a Monday" in make(week_start=date(2026, 11, 4)).problems()
    assert any("needs at least one service" in p for p in make(kind="flat", workers=[]).problems())


def test_json_round_trip():
    inv = make(gas_cents=2000, notes=["Thanks!"])
    assert InvoiceData.from_json(inv.to_json()).total_cents == inv.total_cents
