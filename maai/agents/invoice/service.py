"""Invoice work: clients, numbering, making the invoice, reminders.

The agent decides WHAT to do; this file does it safely:
  * the math and the invoice numbers (never the AI),
  * blocking card/bank/SSN data,
  * preparing emails as DRAFTS and asking for your approval.
The two `send_*` functions at the bottom are only ever called by the
approval gate after you tap ✅.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ...core.db import now_iso
from ...security.guard import SensitiveDataError, ensure_clean
from .docs_fill import plan_invoice_edits
from .html_render import render_html
from .models import DAYS, InvoiceData, Service, Worker, money, to_cents

if TYPE_CHECKING:
    from ...app import App

log = logging.getLogger(__name__)

SEND_INVOICE = "send_invoice"
SEND_REMINDER = "send_reminder"


class InvoiceError(ValueError):
    pass


class InvoiceService:
    def __init__(self, app: "App"):
        self.app = app
        self.db = app.db
        self.config = app.config
        self.business = app.config.business
        self.settings = app.config.section("invoices")
        self.files_dir = app.config.data_dir / "invoices"
        self.files_dir.mkdir(parents=True, exist_ok=True)

    # ---- helpers ------------------------------------------------------------
    @property
    def is_test(self) -> bool:
        return self.config.dry_run

    def today(self) -> date:
        return datetime.now(ZoneInfo(self.config.timezone)).date()

    def _clean(self, value: Any, field: str) -> str:
        return ensure_clean(str(value or "").strip(), field)

    # ---- clients ------------------------------------------------------------
    def find_clients(self, query: str) -> list[dict[str, Any]]:
        like = f"%{query.strip()}%"
        return self.db.query(
            "SELECT id, name, email, phone, address, notes FROM clients "
            "WHERE is_test = ? AND (name LIKE ? OR email LIKE ?) ORDER BY name LIMIT 10",
            (int(self.is_test), like, like),
        )

    def _client_by_name(self, name: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM clients WHERE is_test = ? AND lower(name) = lower(?)", (int(self.is_test), name.strip())
        )

    def save_client(self, name: str, email: str = "", phone: str = "", address: str = "",
                    notes: str = "") -> dict[str, Any]:
        name = self._clean(name, "name")
        if not name:
            raise InvoiceError("Client name is required")
        fields = {
            "email": self._clean(email, "email"),
            "phone": self._clean(phone, "phone"),
            "address": self._clean(address, "address"),
            "notes": self._clean(notes, "notes"),
        }
        existing = self._client_by_name(name)
        ts = now_iso()
        if existing:
            updates = {k: v for k, v in fields.items() if v}
            if updates:
                cols = ", ".join(f"{k} = ?" for k in updates)
                self.db.execute(f"UPDATE clients SET {cols}, updated_at = ? WHERE id = ?",
                                (*updates.values(), ts, existing["id"]))
            client_id = existing["id"]
        else:
            cur = self.db.execute(
                "INSERT INTO clients(name, email, phone, address, notes, is_test, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (name, fields["email"], fields["phone"], fields["address"], fields["notes"], int(self.is_test), ts, ts),
            )
            client_id = cur.lastrowid
        return self.db.query_one("SELECT id, name, email, phone, address FROM clients WHERE id = ?", (client_id,))

    # ---- numbering ----------------------------------------------------------
    def _next_number(self, year: int) -> str:
        fmt = self.settings.get("number_format", "INV-{year}-{seq:03d}")
        key = f"invoice_seq:{'test:' if self.is_test else ''}{year}"
        number = fmt.format(year=year, seq=self.db.next_counter(key))
        return f"TEST-{number}" if self.is_test else number

    # ---- create -------------------------------------------------------------
    def build_invoice(self, args: dict[str, Any], number: str = "PENDING") -> InvoiceData:
        client_name = self._clean(args.get("client_name"), "client_name")
        stored = self._client_by_name(client_name) if client_name else None
        email = self._clean(args.get("client_email") or (stored or {}).get("email"), "client_email")
        address = self._clean(args.get("client_address") or (stored or {}).get("address"), "client_address")

        issue = date.fromisoformat(args["issue_date"]) if args.get("issue_date") else self.today()
        terms = int(self.settings.get("payment_terms_days", 14))
        week_start = date.fromisoformat(args["week_start"]) if args.get("week_start") else None

        workers = []
        for w in args.get("workers") or []:
            hours = {d: float((w.get("hours") or {}).get(d, 0) or 0) for d in DAYS}
            workers.append(Worker(self._clean(w.get("name"), "worker name"), hours))
        services = [Service(self._clean(s.get("description"), "service"), to_cents(s.get("amount")))
                    for s in (args.get("services") or [])]
        notes = [self._clean(n, "note") for n in (args.get("notes") or []) if str(n).strip()]

        return InvoiceData(
            number=number,
            kind=args.get("kind", "labor"),
            client_name=client_name,
            client_email=email,
            client_address=address,
            project=self._clean(args.get("project") or client_name, "project"),
            issue_date=issue,
            due_date=issue + timedelta(days=terms),
            sent_by=self.business.get("sent_by") or self.business.get("company", ""),
            rate_cents=to_cents(args.get("rate") or self.business.get("labor_rate", 20)),
            po_number=self._clean(args.get("po_number"), "po_number"),
            week_start=week_start,
            workers=workers,
            overtime_hours=float(args.get("overtime_hours") or 0),
            overtime_multiplier=Decimal(str(self.business.get("overtime_multiplier", "1.5"))),
            gas_cents=to_cents(args.get("gas")),
            supplies_cents=to_cents(args.get("supplies")),
            services=services,
            notes=notes,
        )

    async def create_draft(self, args: dict[str, Any], task_id: int | None) -> dict[str, Any]:
        try:
            inv = self.build_invoice(args)
        except SensitiveDataError as exc:
            raise InvoiceError(str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise InvoiceError(f"Invalid invoice details: {exc}") from exc
        problems = inv.problems()
        if problems:
            raise InvoiceError("Can't make the invoice yet: " + "; ".join(problems))

        client = self.save_client(inv.client_name, inv.client_email, address=inv.client_address)
        inv.number = self._next_number(inv.issue_date.year)

        render = await asyncio.to_thread(self._render, inv)

        ts = now_iso()
        cur = self.db.execute(
            "INSERT INTO invoices(number, client_id, project, issue_date, due_date, total_cents, status, data, "
            "doc_id, pdf_file_id, pdf_path, is_test, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inv.number, client["id"], inv.project, inv.issue_date.isoformat(), inv.due_date.isoformat(),
             inv.total_cents, "draft", json.dumps(inv.to_json()), render.get("doc_id"), render.get("file_id"),
             str(render["path"]), int(self.is_test), ts, ts),
        )
        invoice_id = cur.lastrowid
        self.app.activity.record("invoice", "invoice_drafted", ref=inv.number)

        subject, body = self._invoice_email(inv, args.get("email_message"), args.get("language", "en"))
        approval = await self._request_send(
            kind=SEND_INVOICE, invoice_id=invoice_id, inv=inv, subject=subject, body=body,
            attachment=Path(render["path"]), task_id=task_id,
            title=f"Send invoice {inv.number} to {inv.client_name} ({money(inv.total_cents)})",
            warnings=render.get("warnings", []),
        )
        return {
            "number": inv.number,
            "total": money(inv.total_cents),
            "approval_id": approval["id"],
            "warnings": render.get("warnings", []),
            "link": render.get("link", ""),
        }

    def _render(self, inv: InvoiceData) -> dict[str, Any]:
        ws = self.app.workspace
        year_folder = str(inv.issue_date.year)
        folder = ws.ensure_folder("TEST Invoices" if self.is_test else "Invoices", year_folder)
        name = f"{inv.number} - {inv.client_name} - {inv.project}"[:120]
        template_id = self.config.secret("GOOGLE_INVOICE_TEMPLATE_ID")

        if ws.supports_docs and template_id:
            doc_id = ws.copy_file(template_id, name, folder)
            requests, warnings = plan_invoice_edits(ws.get_doc(doc_id), inv, self.business)
            ws.update_doc(doc_id, requests)
            pdf_path = self.files_dir / f"{inv.number}.pdf"
            pdf_path.write_bytes(ws.export_pdf(doc_id))
            file_id = ws.upload_file(pdf_path, f"{name}.pdf", folder, "application/pdf")
            return {"path": pdf_path, "doc_id": doc_id, "file_id": file_id, "warnings": warnings,
                    "link": ws.file_link(file_id)}

        html_path = self.files_dir / f"{inv.number}.html"
        html_path.write_text(render_html(inv, self.business, self.is_test), encoding="utf-8")
        file_id = ws.upload_file(html_path, f"{name}.html", folder, "text/html")
        warnings = [] if ws.is_local else ["GOOGLE_INVOICE_TEMPLATE_ID is not set; used the simple layout"]
        return {"path": html_path, "file_id": file_id, "warnings": warnings, "link": ws.file_link(file_id)}

    def _invoice_email(self, inv: InvoiceData, message: str | None, language: str) -> tuple[str, str]:
        company = self.business.get("company", "MAAI Multiservices LLC")
        if language == "es":
            subject = f"Factura {inv.number} - {company}"
            default = (f"Hola {inv.client_name},\n\nAdjunto la factura {inv.number} por {inv.project}. "
                       f"Total: {money(inv.total_cents)}, con vencimiento el {inv.due_date:%m/%d/%Y}.\n\n"
                       "Gracias por confiar en nosotros.")
        else:
            subject = f"Invoice {inv.number} - {company}"
            default = (f"Hi {inv.client_name},\n\nAttached is invoice {inv.number} for {inv.project}. "
                       f"Total: {money(inv.total_cents)}, due {inv.due_date:%m/%d/%Y}.\n\n"
                       "Thank you for your business.")
        body = self._clean(message, "email message") if message else default
        signature = f"\n\n{company}\n{self.business.get('phone', '')}\n{self.business.get('email', '')}"
        return subject, body.rstrip() + signature

    async def _request_send(self, *, kind: str, invoice_id: int, inv: InvoiceData, subject: str, body: str,
                            attachment: Path, task_id: int | None, title: str, warnings: list[str]) -> dict:
        to = inv.client_email
        if self.is_test:
            to = self.config.secret("OWNER_EMAIL", "owner@example.invalid")
            subject = f"[TEST] {subject}"
            body = f"(Practice mode: this would go to {inv.client_email})\n\n{body}"
        draft_id = await asyncio.to_thread(self.app.workspace.create_email_draft, to, subject, body, [attachment])

        preview = "\n".join(inv.summary_lines())
        if warnings:
            preview += "\n\n⚠️ " + "\n⚠️ ".join(warnings)
        preview += f"\n\n✉️ To: {to}\nSubject: {subject}\n\n{body[:600]}"
        return await self.app.gate.request(
            agent="invoice", kind=kind, title=title, preview=preview,
            payload={"invoice_id": invoice_id, "draft_id": draft_id, "to": to},
            task_id=task_id, attachment=str(attachment),
        )

    # ---- read / update --------------------------------------------------------
    def list_invoices(self, status: str = "unpaid") -> list[dict[str, Any]]:
        today = self.today().isoformat()
        where = {
            "unpaid": "i.status = 'sent'",
            "overdue": f"i.status = 'sent' AND i.due_date < '{today}'",
            "draft": "i.status = 'draft'",
            "sent": "i.status = 'sent'",
            "paid": "i.status = 'paid'",
            "all": "1=1",
        }.get(status, "i.status = 'sent'")
        rows = self.db.query(
            f"SELECT i.number, c.name AS client, i.project, i.total_cents, i.status, i.issue_date, i.due_date, "
            f"i.reminders_sent FROM invoices i JOIN clients c ON c.id = i.client_id "
            f"WHERE i.is_test = ? AND {where} ORDER BY i.id DESC LIMIT 50",
            (int(self.is_test),),
        )
        for row in rows:
            row["total"] = money(row.pop("total_cents"))
            if row["status"] == "sent":
                row["days_overdue"] = max((self.today() - date.fromisoformat(row["due_date"])).days, 0)
        return rows

    def get_invoice(self, number: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT i.*, c.name AS client, c.email AS client_email FROM invoices i "
            "JOIN clients c ON c.id = i.client_id WHERE i.number = ?", (number.strip(),))

    def mark_paid(self, number: str, paid_date: str | None = None) -> str:
        invoice = self.get_invoice(number)
        if not invoice:
            raise InvoiceError(f"No invoice {number}")
        if invoice["status"] == "paid":
            return f"{number} was already marked paid."
        when = paid_date or self.today().isoformat()
        self.db.execute("UPDATE invoices SET status = 'paid', paid_at = ?, updated_at = ? WHERE id = ?",
                        (when, now_iso(), invoice["id"]))
        self.app.activity.record("invoice", "invoice_marked_paid", ref=number)
        return f"{number} marked paid on {when}."

    # ---- reminders --------------------------------------------------------------
    def due_for_reminder(self) -> list[dict[str, Any]]:
        first_after = int(self.settings.get("first_reminder_after_days", 7))
        repeat = int(self.settings.get("repeat_reminder_every_days", 7))
        max_reminders = int(self.settings.get("max_reminders", 3))
        today = self.today()
        due = []
        for inv in self.db.query("SELECT * FROM invoices WHERE status = 'sent' AND is_test = ?", (int(self.is_test),)):
            if inv["reminders_sent"] >= max_reminders:
                continue
            if today < date.fromisoformat(inv["due_date"]) + timedelta(days=first_after):
                continue
            if inv["last_reminder_at"] and today < date.fromisoformat(inv["last_reminder_at"][:10]) + timedelta(days=repeat):
                continue
            pending = self.db.query_one(
                "SELECT id FROM approvals WHERE kind = ? AND status = 'pending' AND payload LIKE ?",
                (SEND_REMINDER, f'%"invoice_id": {inv["id"]},%'),
            )
            if not pending:
                due.append(inv)
        return due

    async def draft_reminder(self, number: str, subject: str, message: str, task_id: int | None) -> dict[str, Any]:
        invoice = self.get_invoice(number)
        if not invoice:
            raise InvoiceError(f"No invoice {number}")
        if invoice["status"] != "sent":
            raise InvoiceError(f"{number} is '{invoice['status']}'. Reminders are only for sent, unpaid invoices.")
        inv = InvoiceData.from_json(json.loads(invoice["data"]))
        message = self._clean(message, "reminder message")
        subject = self._clean(subject, "subject") or f"Reminder: invoice {number}"
        company = self.business.get("company", "MAAI Multiservices LLC")
        body = message.rstrip() + f"\n\n{company}\n{self.business.get('phone', '')}\n{self.business.get('email', '')}"
        attachment = Path(invoice["pdf_path"]) if invoice["pdf_path"] else None
        if not attachment or not attachment.exists():
            raise InvoiceError(f"The file for {number} is missing, so I can't attach it")
        nth = invoice["reminders_sent"] + 1
        approval = await self._request_send(
            kind=SEND_REMINDER, invoice_id=invoice["id"], inv=inv, subject=subject, body=body,
            attachment=attachment, task_id=task_id,
            title=f"Send reminder #{nth} for {number} to {inv.client_name} ({money(invoice['total_cents'])})",
            warnings=[],
        )
        self.app.activity.record("invoice", "reminder_drafted", ref=number)
        return {"number": number, "approval_id": approval["id"]}

    # ---- executors: ONLY called by the approval gate after you approve ---------------
    def _sent_note(self, to: str) -> str:
        if self.app.workspace.is_local:
            return "Practice mode: saved to data/outbox/sent (not really emailed)."
        if self.is_test:
            return f"TEST email sent to you ({to}), not to the client."
        return f"Emailed to {to}."

    async def send_invoice(self, payload: dict[str, Any]) -> str:
        invoice = self.db.query_one("SELECT * FROM invoices WHERE id = ?", (payload["invoice_id"],))
        if invoice["status"] != "draft":
            return f"{invoice['number']} was already sent."
        await asyncio.to_thread(self.app.workspace.send_email_draft, payload["draft_id"])
        self.db.execute("UPDATE invoices SET status = 'sent', sent_at = ?, updated_at = ? WHERE id = ?",
                        (now_iso(), now_iso(), invoice["id"]))
        self.app.activity.record("invoice", "invoice_sent", ref=invoice["number"])
        return f"✅ Invoice {invoice['number']} sent. {self._sent_note(payload.get('to', ''))}"

    async def send_reminder(self, payload: dict[str, Any]) -> str:
        invoice = self.db.query_one("SELECT * FROM invoices WHERE id = ?", (payload["invoice_id"],))
        if invoice["status"] == "paid":
            return f"{invoice['number']} is already paid; reminder not sent."
        await asyncio.to_thread(self.app.workspace.send_email_draft, payload["draft_id"])
        self.db.execute(
            "UPDATE invoices SET reminders_sent = reminders_sent + 1, last_reminder_at = ?, updated_at = ? WHERE id = ?",
            (self.today().isoformat(), now_iso(), invoice["id"]),
        )
        self.app.activity.record("invoice", "reminder_sent", ref=invoice["number"])
        return f"✅ Reminder for {invoice['number']} sent. {self._sent_note(payload.get('to', ''))}"
