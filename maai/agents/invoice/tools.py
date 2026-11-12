"""The invoice agent's tools. These are the ONLY things it can do.

It can look up and save clients, prepare invoices and reminders (as drafts
waiting for your OK), list invoices, mark them paid, and ask you questions.
It cannot send anything, and it has no website, social or file tools.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from claude_agent_sdk import tool

from ...security.guard import SensitiveDataError
from ..base import RunContext, text_result
from ..common_tools import common_tools
from .service import InvoiceError

HOURS_SCHEMA = {
    "type": "object",
    "properties": {d: {"type": "number", "minimum": 0, "maximum": 24} for d in
                   ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
    "additionalProperties": False,
}

CREATE_INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["labor", "flat"],
                 "description": "labor = weekly hours per worker; flat = fixed price per service"},
        "client_name": {"type": "string"},
        "client_email": {"type": "string", "description": "Leave empty to use the saved client email"},
        "client_address": {"type": "string"},
        "project": {"type": "string", "description": "Project / job name printed at the top"},
        "po_number": {"type": "string"},
        "issue_date": {"type": "string", "description": "YYYY-MM-DD, default today"},
        "week_start": {"type": "string", "description": "Labor only: Monday of the week, YYYY-MM-DD"},
        "workers": {
            "type": "array", "maxItems": 10,
            "items": {"type": "object", "properties": {"name": {"type": "string"}, "hours": HOURS_SCHEMA},
                      "required": ["name", "hours"]},
        },
        "overtime_hours": {"type": "number", "minimum": 0, "description": "Only if the owner says so"},
        "rate": {"type": "number", "description": "Hourly rate; default from business settings"},
        "services": {
            "type": "array",
            "items": {"type": "object", "properties": {"description": {"type": "string"},
                                                        "amount": {"type": "number"}},
                      "required": ["description", "amount"]},
        },
        "gas": {"type": "number", "description": "Gas / fuel charge in dollars"},
        "supplies": {"type": "number", "description": "Cleaning supplies / materials charge in dollars"},
        "notes": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "email_message": {"type": "string", "description": "Short email to the client (no signature)"},
        "language": {"type": "string", "enum": ["en", "es"]},
    },
    "required": ["kind", "client_name", "project"],
}


def _fail(exc: Exception) -> dict[str, Any]:
    return text_result(str(exc), is_error=True)


def invoice_tools(ctx: RunContext) -> list[Any]:
    service = ctx.app.invoices

    @tool("find_client", "Search saved clients by name or email.", {"query": str})
    async def find_client(args: dict[str, Any]) -> dict[str, Any]:
        found = service.find_clients(args["query"])
        return text_result(json.dumps(found) if found else "No saved client matches.")

    @tool("save_client", "Save or update a client's contact info. Never include card, bank or SSN numbers.", {
        "type": "object",
        "properties": {"name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
                       "address": {"type": "string"}, "notes": {"type": "string"}},
        "required": ["name"],
    })
    async def save_client(args: dict[str, Any]) -> dict[str, Any]:
        try:
            client = service.save_client(args["name"], args.get("email", ""), args.get("phone", ""),
                                         args.get("address", ""), args.get("notes", ""))
        except (InvoiceError, SensitiveDataError) as exc:
            return _fail(exc)
        return text_result(f"Saved client #{client['id']}: {client['name']}")

    @tool("create_invoice",
          "Make the invoice from the MAAI template and prepare the email as a DRAFT. The owner gets a preview "
          "and must approve before anything is sent. The system does all the math.",
          CREATE_INVOICE_SCHEMA)
    async def create_invoice(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await service.create_draft(args, ctx.task_id)
        except (InvoiceError, SensitiveDataError) as exc:
            return _fail(exc)
        ctx.requested_approval = True
        return text_result(json.dumps(result) + "\nThe owner now has the preview to approve. Do not repeat it.")

    @tool("list_invoices", "List invoices. status: unpaid, overdue, draft, sent, paid or all.", {"status": str})
    async def list_invoices(args: dict[str, Any]) -> dict[str, Any]:
        rows = service.list_invoices(args.get("status", "unpaid"))
        return text_result(json.dumps(rows) if rows else "None.")

    @tool("mark_invoice_paid", "Mark an invoice paid. Only when the owner says it was paid.",
          {"number": Annotated[str, "Invoice number, e.g. INV-2026-004"],
           "paid_date": Annotated[str, "YYYY-MM-DD, or empty for today"]})
    async def mark_invoice_paid(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return text_result(service.mark_paid(args["number"], args.get("paid_date") or None))
        except InvoiceError as exc:
            return _fail(exc)

    @tool("draft_payment_reminder",
          "Prepare a polite payment reminder email (as a DRAFT, invoice PDF attached) for owner approval.",
          {"number": str, "subject": str,
           "message": Annotated[str, "The email text, polite and short, in the client's language, no signature"]})
    async def draft_payment_reminder(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await service.draft_reminder(args["number"], args["subject"], args["message"], ctx.task_id)
        except (InvoiceError, SensitiveDataError) as exc:
            return _fail(exc)
        ctx.requested_approval = True
        return text_result(json.dumps(result) + "\nThe owner now has the preview to approve.")

    return [find_client, save_client, create_invoice, list_invoices, mark_invoice_paid,
            draft_payment_reminder, *common_tools(ctx)]
