"""Fills a COPY of your MAAI invoice template (Google Doc).

Your original template is never changed. For each new invoice:
  1. Drive makes a copy of the template.
  2. This file reads the copy and finds every blank by its text
     ("INV-____-___", "PO #: ____", "Worker Name" rows, "TOTAL DUE", ...).
  3. It replaces the blanks with the invoice's values in one update.

If something can't be found (for example, you redesign the template), the
invoice preview says what was missing. A wrong invoice is never sent
silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import DAYS, InvoiceData, hours_text, money

DASH = "—"


@dataclass
class Cell:
    text: str
    start: int   # first character index
    end: int     # index of the cell's final newline (not deletable)


@dataclass
class Edit:
    start: int
    end: int
    text: str


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def _is_letter_spaced(text: str) -> bool:
    tokens = [t for t in text.strip().split(" ") if t]
    return len(tokens) >= 6 and sum(len(t) == 1 for t in tokens) / len(tokens) > 0.8


def _letter_space(text: str) -> str:
    return " ".join(text)


# ---------------------------------------------------------------------------
# Reading the document
# ---------------------------------------------------------------------------
def _paragraph_text(paragraph: dict[str, Any]) -> str:
    return "".join(el.get("textRun", {}).get("content", "") for el in paragraph.get("elements", []))


def _walk_content(content: list[dict[str, Any]], rows: list[list[Cell]], chars: list[tuple[str, int]]) -> None:
    for element in content:
        if "paragraph" in element:
            for run in element["paragraph"].get("elements", []):
                text_run = run.get("textRun")
                if not text_run:
                    continue
                index = run["startIndex"]
                for ch in text_run.get("content", ""):
                    chars.append((ch, index))
                    index += _utf16_len(ch)
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                cells: list[Cell] = []
                for cell in row.get("tableCells", []):
                    cell_content = cell.get("content", [])
                    text = "".join(_paragraph_text(c["paragraph"]) for c in cell_content if "paragraph" in c)
                    start = cell_content[0]["startIndex"] if cell_content else cell.get("startIndex", 0)
                    end = (cell_content[-1]["endIndex"] - 1) if cell_content else start
                    cells.append(Cell(text=text.rstrip("\n"), start=start, end=end))
                rows.append(cells)
                for cell in row.get("tableCells", []):
                    _walk_content(cell.get("content", []), rows, chars)


def read_document(doc: dict[str, Any]) -> tuple[list[list[Cell]], str, list[int]]:
    rows: list[list[Cell]] = []
    chars: list[tuple[str, int]] = []
    _walk_content(doc.get("body", {}).get("content", []), rows, chars)
    flat = "".join(c for c, _ in chars)
    index_map = [i for _, i in chars]
    return rows, flat, index_map


# ---------------------------------------------------------------------------
# Planning the edits
# ---------------------------------------------------------------------------
class Planner:
    def __init__(self, doc: dict[str, Any]):
        self.rows, self.flat, self.index_map = read_document(doc)
        self.edits: list[Edit] = []
        self.warnings: list[str] = []

    # text anywhere in the document --------------------------------------
    def replace_text(self, pattern: str, value: str, label: str, group: int = 0, required: bool = True) -> int:
        count = 0
        for match in re.finditer(pattern, self.flat):
            s, e = match.span(group)
            if s == e:
                continue
            start = self.index_map[s]
            end = self.index_map[e - 1] + _utf16_len(self.flat[e - 1])
            self.edits.append(Edit(start, end, value))
            count += 1
        if required and count == 0:
            self.warnings.append(f"Couldn't find '{label}' in the template")
        return count

    # table cells ----------------------------------------------------------
    def set_cell(self, cell: Cell, value: str) -> None:
        self.edits.append(Edit(cell.start, cell.end, value))

    def rows_where(self, predicate) -> list[list[Cell]]:
        return [row for row in self.rows if predicate(row)]

    def find_row(self, key: str, exact: bool = False) -> list[Cell] | None:
        for row in self.rows:
            first = next((c for c in row if c.text.strip()), None)
            if not first:
                continue
            label = _norm(first.text)
            if (label == key) if exact else label.startswith(key):
                return row
        return None

    @staticmethod
    def filled_after_label(row: list[Cell]) -> tuple[Cell, list[Cell]]:
        non_empty = [c for c in row if c.text.strip()]
        return non_empty[0], non_empty[1:]

    def requests(self) -> list[dict[str, Any]]:
        edits = sorted(self.edits, key=lambda e: e.start, reverse=True)
        for earlier, later in zip(edits[1:], edits):
            if earlier.end > later.start:
                raise ValueError("Overlapping template edits; the template layout changed")
        out: list[dict[str, Any]] = []
        for edit in edits:
            if edit.end > edit.start:
                out.append({"deleteContentRange": {"range": {"startIndex": edit.start, "endIndex": edit.end}}})
            if edit.text:
                out.append({"insertText": {"location": {"index": edit.start}, "text": edit.text}})
        return out


def plan_invoice_edits(doc: dict[str, Any], inv: InvoiceData, business: dict[str, Any]) -> tuple[list[dict], list[str]]:
    p = Planner(doc)

    # ---- header -----------------------------------------------------------
    p.replace_text(r"PROJECT NAME", inv.project, "PROJECT NAME")
    p.replace_text(r"INV-_+-_+", inv.number, "INV-____-___")
    p.replace_text(r"PO #:\s*(_+)", inv.po_number or DASH, "PO #", group=1)
    p.replace_text(r"Date:\s*(_{1,2}/_{1,2}/_{2,4})", f"{inv.issue_date:%m/%d/%Y}", "Date", group=1)
    p.replace_text(r"Sent by:\s*(_+)", inv.sent_by or business.get("company", ""), "Sent by", group=1)
    p.replace_text(r"Address \(optional\)", business.get("address") or business.get("city", ""), "Address (optional)",
                   required=False)
    p.replace_text(r"Rate:\s*(\$[\d.,]+)/hr", money(inv.rate_cents), "Rate", group=1, required=False)
    if business.get("phone"):
        p.replace_text(r"Tel:\s*(\(\d{3}\)\s*\d{3}-\d{4})", business["phone"], "Tel", group=1, required=False)

    # ---- week + day labels -----------------------------------------------
    week_row = p.find_row("WEEK", exact=True)
    if week_row and inv.kind == "labor":
        label, rest = p.filled_after_label(week_row)
        if rest:
            text = inv.week_label()
            p.set_cell(rest[0], _letter_space(text) if _is_letter_spaced(rest[0].text) else text)
    elif inv.kind == "labor":
        p.warnings.append("Couldn't find the WEEK row")
    for day in DAYS:
        label = day.capitalize()
        value = inv.day_label(day).split(" ", 1)[1] if (inv.kind == "labor" and inv.week_start) else ""
        p.replace_text(rf"\b{label} (__)", value or " ", f"{label} __", group=1, required=False)

    # ---- worker rows ---------------------------------------------------------
    worker_rows = p.rows_where(lambda row: any(_norm(c.text) == "WORKERNAME" for c in row))
    if inv.kind == "labor" and len(inv.workers) > len(worker_rows):
        p.warnings.append(f"Template has {len(worker_rows)} worker rows but invoice has {len(inv.workers)} workers")
    for i, row in enumerate(worker_rows):
        name_idx = next(j for j, c in enumerate(row) if _norm(c.text) == "WORKERNAME")
        total_idx = next((j for j in range(len(row) - 1, name_idx, -1) if row[j].text.strip()), None)
        if total_idx is None or total_idx - name_idx - 1 < 7:
            p.warnings.append(f"Worker row {i + 1} layout not recognized")
            continue
        day_cells = row[total_idx - 7:total_idx]
        worker = inv.workers[i] if (inv.kind == "labor" and i < len(inv.workers)) else None
        p.set_cell(row[name_idx], worker.name if worker else "")
        for day, cell in zip(DAYS, day_cells):
            p.set_cell(cell, hours_text(float(worker.hours.get(day, 0) or 0)) if worker else "")
        p.set_cell(row[total_idx], hours_text(worker.total) if worker else "")
        if not worker and name_idx > 0 and row[name_idx - 1].text.strip() == "L":
            p.set_cell(row[name_idx - 1], "")

    per_day = p.find_row("TOTALHOURSPERDAY")
    if per_day:
        total_idx = next((j for j in range(len(per_day) - 1, 0, -1) if per_day[j].text.strip()), None)
        if total_idx is not None and total_idx >= 8:
            totals = inv.day_totals()
            for day, cell in zip(DAYS, per_day[total_idx - 7:total_idx]):
                p.set_cell(cell, hours_text(totals[day]) if inv.kind == "labor" else "")
            p.set_cell(per_day[total_idx], hours_text(inv.labor_hours) if inv.kind == "labor" else DASH)
        else:
            p.warnings.append("TOTAL HOURS PER DAY row layout not recognized")

    # ---- summary ----------------------------------------------------------------
    def fill_summary(key: str, values: list[str], label_text: str | None = None) -> None:
        row = p.find_row(key)
        if not row:
            p.warnings.append(f"Couldn't find the '{key}' summary row")
            return
        label, cells = p.filled_after_label(row)
        if len(cells) < len(values):
            p.warnings.append(f"Summary row '{key}' layout not recognized")
            return
        if label_text is not None:
            p.set_cell(label, label_text)
        for cell, value in zip(cells, values):
            if value is not None:
                p.set_cell(cell, value)

    if inv.kind == "labor":
        fill_summary("TOTALLABORHOURS", [
            hours_text(inv.labor_hours) or "0",
            hours_text(inv.overtime_hours) or DASH,
            money(inv.rate_cents),
            money(inv.labor_cents),
        ])
    else:
        description = "; ".join(s.description for s in inv.services)[:90]
        fill_summary("TOTALLABORHOURS", [DASH, DASH, DASH, money(inv.services_cents)], label_text=description)
    fill_summary("GAS/FUEL", [None, None, None, money(inv.gas_cents) if inv.gas_cents else DASH])
    fill_summary("CLEANINGSUPPLIES", [None, None, None, money(inv.supplies_cents) if inv.supplies_cents else DASH])
    fill_summary("SUBTOTAL", [hours_text(inv.labor_hours) if inv.kind == "labor" else DASH, None, None,
                              money(inv.subtotal_cents)])
    fill_summary("TOTALDUE", [money(inv.total_cents)])

    # ---- notes --------------------------------------------------------------------
    client_line = f"Client: {inv.client_name}" + (f" — {inv.client_address}" if inv.client_address else "")
    notes = [client_line, *inv.notes]
    if inv.kind == "flat" and len(inv.services) > 1:
        notes.append("Services: " + "; ".join(f"{s.description} ({money(s.amount_cents)})" for s in inv.services))
    placeholders = [
        r"Note 1: Add project details here",
        r"Note 2: Add labor summary here",
        r"Note 3: Add status / additional info here",
    ]
    for i, pattern in enumerate(placeholders):
        if i < len(notes):
            p.replace_text(pattern, notes[i], f"Note {i + 1}", required=False)
        else:
            p.replace_text(r"▸?\s*" + pattern, "", f"Note {i + 1}", required=False)
    if len(notes) > len(placeholders):
        p.warnings.append("Some notes didn't fit in the template's 3 note lines")

    return p.requests(), p.warnings
