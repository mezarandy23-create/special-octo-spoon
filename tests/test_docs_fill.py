from datetime import date

import pytest

from maai.agents.invoice.docs_fill import plan_invoice_edits
from maai.agents.invoice.models import InvoiceData, Service, Worker

from .fake_docs import apply, template_doc

BUSINESS = {"company": "MAAI Multiservices LLC", "city": "Norcross, GA", "phone": "(470) 709-1901"}


def labor_invoice() -> InvoiceData:
    return InvoiceData(
        number="INV-2026-007", kind="labor", client_name="Berry College", client_email="ap@berry.example",
        client_address="2277 Martha Berry Hwy, Rome GA", project="Amber Grace Hall", issue_date=date(2026, 11, 10),
        due_date=date(2026, 11, 24), sent_by="Randy", rate_cents=2000, po_number="4471",
        week_start=date(2026, 11, 2), gas_cents=2000,
        workers=[Worker("Ana Lopez", {d: 8 for d in ("mon", "tue", "wed", "thu", "fri")}),
                 Worker("Luis Diaz", {"mon": 6, "tue": 6, "wed": 6.5})],
        notes=["Final clean before walk-through"],
    )


@pytest.mark.parametrize("covered", [False, True])
def test_labor_invoice_fills_every_blank(covered):
    doc = template_doc(covered_cells=covered)
    requests, warnings = plan_invoice_edits(doc, labor_invoice(), BUSINESS)
    assert warnings == []
    text = apply(doc, requests)

    for placeholder in ("PROJECT NAME", "INV-____-___", "Worker Name", "Mon __", "$0.00",
                        "Note 1: Add", "Note 2: Add", "Note 3: Add", "Address (optional)"):
        assert placeholder not in text, placeholder
    assert "Amber Grace Hall" in text
    assert "INV #: INV-2026-007" in text
    assert "PO #: 4471" in text
    assert "Date: 11/10/2026" in text
    assert "Sent by: Randy" in text
    assert "Norcross, GA" in text
    assert "N o v e m b e r" in text           # keeps the spaced-letter style of the week line
    assert "Mon 11/02" in text and "Sun 11/08" in text
    # worker rows: name, Mon..Sun, total
    assert "Ana Lopez\n8\n8\n8\n8\n8\n\n\n40\n" in text
    assert "Luis Diaz\n6\n6\n6.5\n\n\n\n\n18.5\n" in text
    # labor: 58.5 h x $20 = $1,170.00; + $20 gas = $1,190.00
    assert "58.5" in text and "$1,170.00" in text and "$1,190.00" in text
    assert "Client: Berry College — 2277 Martha Berry Hwy, Rome GA" in text
    assert "▸ Final clean before walk-through" in text
    # unused worker rows are blanked; the signature line is untouched
    assert "Authorized signature: ________________" in text


def test_flat_invoice_uses_summary_row():
    inv = labor_invoice()
    inv.kind, inv.workers, inv.week_start, inv.gas_cents = "flat", [], None, 0
    inv.services = [Service("Deep clean 3BR house", 25000), Service("Inside fridge", 3500)]
    doc = template_doc()
    requests, warnings = plan_invoice_edits(doc, inv, BUSINESS)
    assert warnings == []
    text = apply(doc, requests)
    assert "Deep clean 3BR house; Inside fridge" in text
    assert "$285.00" in text
    assert "Worker Name" not in text and "Mon __" not in text


def test_changed_template_produces_warnings_not_silence():
    doc = {"body": {"content": []}}
    _, warnings = plan_invoice_edits(doc, labor_invoice(), BUSINESS)
    assert any("INV-____-___" in w for w in warnings)
    assert any("TOTALDUE" in w for w in warnings)
