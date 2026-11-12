"""End-to-end invoice flow in practice mode, with fake clients only."""

from datetime import date, timedelta

import pytest

from maai.agents.invoice.service import InvoiceError

LABOR = {
    "kind": "labor",
    "client_name": "TEST Berry College",
    "client_email": "ap@berry.example",
    "project": "Amber Grace Hall",
    "po_number": "4471",
    "issue_date": "2026-11-10",
    "week_start": "2026-11-02",
    "workers": [
        {"name": "Ana", "hours": {"mon": 8, "tue": 8, "wed": 8, "thu": 8, "fri": 8}},
        {"name": "Luis", "hours": {"mon": 6, "tue": 6, "wed": 6}},
    ],
    "gas": 20,
}


def outbox(app):
    box = app.config.data_dir / "outbox"
    return sorted(box.glob("draft-*.eml")), sorted((box / "sent").glob("*.eml"))


async def test_invoice_waits_for_approval_then_sends_once(app):
    result = await app.invoices.create_draft(dict(LABOR), task_id=None)
    assert result["number"] == "TEST-INV-2026-001"
    assert result["total"] == "$1,180.00"

    drafts, sent = outbox(app)
    assert len(drafts) == 1 and sent == []          # prepared, NOT sent

    [approval] = app.gate.pending()
    assert "TOTAL DUE: $1,180.00" in approval["preview"]
    assert "owner@example.com" in approval["preview"]  # practice mode: goes to the owner, not the client

    message = await app.gate.approve(approval["id"])
    assert "sent" in message.lower()
    drafts, sent = outbox(app)
    assert drafts == [] and len(sent) == 1
    email = sent[0].read_text()
    assert "[TEST]" in email and "owner@example.com" in email

    assert "already" in await app.gate.approve(approval["id"])   # tapping ✅ twice does nothing
    assert len(outbox(app)[1]) == 1
    assert app.invoices.get_invoice("TEST-INV-2026-001")["status"] == "sent"


async def test_rejected_invoice_is_never_sent(app):
    await app.invoices.create_draft(dict(LABOR), task_id=None)
    [approval] = app.gate.pending()
    await app.gate.reject(approval["id"], "wrong hours")
    assert outbox(app)[1] == []
    assert app.invoices.get_invoice("TEST-INV-2026-001")["status"] == "draft"


async def test_flat_invoice_and_saved_client_email(app):
    app.invoices.save_client("TEST Juan Perez", email="juan@example.com", address="12 Test St, Norcross GA")
    result = await app.invoices.create_draft({
        "kind": "flat", "client_name": "TEST Juan Perez", "project": "Deep clean",
        "services": [{"description": "Deep clean 3BR", "amount": 250}], "language": "es",
    }, task_id=None)
    assert result["total"] == "$250.00"
    [approval] = app.gate.pending()
    assert "Factura" in approval["preview"]
    assert "juan@example.com" in approval["preview"]   # mentioned as the real recipient in practice mode


async def test_missing_email_and_sensitive_data_are_refused(app):
    with pytest.raises(InvoiceError, match="email"):
        await app.invoices.create_draft({**LABOR, "client_name": "TEST Nobody", "client_email": ""}, task_id=None)
    with pytest.raises(InvoiceError, match="card number"):
        await app.invoices.create_draft({**LABOR, "notes": ["paid with 4111 1111 1111 1111"]}, task_id=None)
    assert app.gate.pending() == []


async def test_reminders_and_paid(app):
    old = (date.today() - timedelta(days=40)).isoformat()
    result = await app.invoices.create_draft({**LABOR, "issue_date": old}, task_id=None)
    number = result["number"]
    assert app.invoices.due_for_reminder() == []            # still a draft: no reminder
    await app.gate.approve(app.gate.pending()[0]["id"])

    [due] = app.invoices.due_for_reminder()
    assert due["number"] == number
    assert app.invoices.list_invoices("overdue")[0]["number"] == number

    await app.invoices.draft_reminder(number, "Friendly reminder", "Hi! Just a reminder about this invoice.", None)
    assert app.invoices.due_for_reminder() == []            # a reminder is already waiting for approval
    await app.gate.approve(app.gate.pending()[0]["id"])
    assert app.invoices.get_invoice(number)["reminders_sent"] == 1
    assert app.invoices.due_for_reminder() == []            # next one only after 7 more days

    assert "marked paid" in app.invoices.mark_paid(number)
    assert app.invoices.list_invoices("unpaid") == []
