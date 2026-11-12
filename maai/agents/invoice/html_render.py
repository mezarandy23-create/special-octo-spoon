"""Practice-mode invoice: a simple web page that follows your template's layout.

Used before Google is connected, so you can try the invoice agent right away.
Once Google is connected, invoices are made from your real Google Doc template.
"""

from __future__ import annotations

from html import escape

from .models import DAYS, InvoiceData, hours_text, money

CSS = """
body{font-family:Arial,Helvetica,sans-serif;color:#1d2433;margin:24px;background:#fff}
.sheet{max-width:860px;margin:auto;border:1px solid #d7dce5;padding:28px}
.top{display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap}
h1{letter-spacing:6px;margin:0 0 6px;font-size:26px}
.brand{font-weight:700;font-size:18px}
.muted{color:#5b6475;font-size:13px}
table{width:100%;border-collapse:collapse;margin-top:18px;font-size:13px}
th,td{border:1px solid #d7dce5;padding:6px;text-align:center}
th{background:#1d2433;color:#fff;letter-spacing:2px;font-size:11px}
td.l{text-align:left}
.total{font-size:18px;font-weight:700}
.test{background:#ffe9a8;padding:8px 12px;font-weight:700;margin-bottom:12px}
"""


def render_html(inv: InvoiceData, business: dict, is_test: bool) -> str:
    e = escape
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(inv.number)}</title>",
             f"<style>{CSS}</style></head><body><div class='sheet'>"]
    if is_test:
        parts.append("<div class='test'>TEST INVOICE: practice mode, not a real invoice</div>")
    parts.append(
        "<div class='top'><div>"
        f"<h1>INVOICE</h1><div class='brand'>{e(business.get('company', ''))}</div>"
        f"<div class='muted'>{e(business.get('email', ''))}<br>{e(business.get('address') or business.get('city', ''))}"
        f"<br>Tel: {e(business.get('phone', ''))}</div></div><div>"
        f"<div class='brand'>{e(inv.project)}</div>"
        f"<div class='muted'>INV #: {e(inv.number)}<br>PO #: {e(inv.po_number or '—')}<br>"
        f"Date: {inv.issue_date:%m/%d/%Y}<br>Due: {inv.due_date:%m/%d/%Y}<br>Sent by: {e(inv.sent_by)}<br>"
        f"(L) Labor | Rate: {money(inv.rate_cents)}/hr</div></div></div>"
        f"<p class='muted'>Bill to: <b>{e(inv.client_name)}</b> {e(inv.client_address)}</p>"
    )
    if inv.kind == "labor":
        head = "".join(f"<th>{e(inv.day_label(d))}</th>" for d in DAYS)
        parts.append(f"<p><b>WEEK:</b> {e(inv.week_label())}</p>")
        parts.append(f"<table><tr><th>JOB</th><th>WORKER</th>{head}<th>TOTAL</th></tr>")
        for w in inv.workers:
            cells = "".join(f"<td>{hours_text(float(w.hours.get(d, 0) or 0))}</td>" for d in DAYS)
            parts.append(f"<tr><td>L</td><td class='l'>{e(w.name)}</td>{cells}<td><b>{hours_text(w.total)}</b></td></tr>")
        totals = inv.day_totals()
        cells = "".join(f"<td>{hours_text(totals[d])}</td>" for d in DAYS)
        parts.append(f"<tr><td colspan='2'><b>TOTAL HOURS PER DAY</b></td>{cells}<td><b>{hours_text(inv.labor_hours)}</b></td></tr></table>")
    parts.append("<table><tr><th>DESCRIPTION</th><th>HOURS</th><th>OT HOURS</th><th>RATE</th><th>AMOUNT</th></tr>")
    if inv.kind == "labor":
        parts.append(f"<tr><td class='l'>Total Labor Hours</td><td>{hours_text(inv.labor_hours)}</td>"
                     f"<td>{hours_text(inv.overtime_hours) or '—'}</td><td>{money(inv.rate_cents)}</td>"
                     f"<td>{money(inv.labor_cents)}</td></tr>")
    for s in inv.services:
        parts.append(f"<tr><td class='l'>{e(s.description)}</td><td>—</td><td>—</td><td>—</td><td>{money(s.amount_cents)}</td></tr>")
    parts.append(f"<tr><td class='l'>Gas / Fuel</td><td>—</td><td>—</td><td>—</td><td>{money(inv.gas_cents) if inv.gas_cents else '—'}</td></tr>")
    parts.append(f"<tr><td class='l'>Cleaning Supplies / Materials</td><td>—</td><td>—</td><td>—</td>"
                 f"<td>{money(inv.supplies_cents) if inv.supplies_cents else '—'}</td></tr>")
    parts.append(f"<tr><td class='l total' colspan='4'>TOTAL DUE</td><td class='total'>{money(inv.total_cents)}</td></tr></table>")
    if inv.notes:
        parts.append("<p><b>NOTES</b></p><ul>" + "".join(f"<li>{e(n)}</li>" for n in inv.notes) + "</ul>")
    parts.append("</div></body></html>")
    return "".join(parts)
