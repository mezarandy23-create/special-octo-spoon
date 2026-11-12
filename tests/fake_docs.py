"""A stand-in for the Google Docs API, shaped like your MAAI invoice template.

`template_doc()` builds a document laid out like MAAI_Invoice_TEMPLATE (the
same labels and blanks), using Google's JSON format: text with numbered
positions. `apply()` performs the same edit requests Google would, so tests
can check the finished invoice text.
"""

from __future__ import annotations

from typing import Any

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


class DocBuilder:
    def __init__(self) -> None:
        self.index = 1
        self.content: list[dict[str, Any]] = []

    def paragraph(self, *runs: str) -> dict[str, Any]:
        runs = list(runs) or [""]
        runs[-1] += "\n"
        start = self.index
        elements = []
        for run in runs:
            elements.append({"startIndex": self.index, "endIndex": self.index + len(run), "textRun": {"content": run}})
            self.index += len(run)
        return {"startIndex": start, "endIndex": self.index, "paragraph": {"elements": elements}}

    def table(self, rows: list[list[Any]]) -> dict[str, Any]:
        start = self.index
        self.index += 1                      # table start marker
        table_rows = []
        for row in rows:
            self.index += 1                  # row marker
            cells = []
            for cell in row:
                self.index += 1              # cell marker
                runs = cell if isinstance(cell, tuple) else (cell,)
                if runs and isinstance(runs[0], list):   # several paragraphs in one cell
                    content = [self.paragraph(*p) for p in runs[0]]
                else:
                    content = [self.paragraph(*runs)]
                cells.append({"content": content})
            table_rows.append({"tableCells": cells})
        return {"startIndex": start, "endIndex": self.index, "table": {"tableRows": table_rows}}


def template_doc(covered_cells: bool = False) -> dict[str, Any]:
    """covered_cells=True mimics Google listing the hidden cells of merged areas."""
    b = DocBuilder()
    header = ([
        ["INVOICE"], ["MAAI"], ["P R O J E C T"], ["MULTISERVICES"], ["PROJECT NAME"],
        ["INV #: ", "INV-____-___"], ["LLC"], ["PO #:", " ", "__________"], ["maaicleaning@gmail.com"],
        ["Date:", " __/__/____"], ["Address (optional)"], ["Tel: (470) 709-1901"], ["Sent by:", " __________"],
        ["(L) Labor", " | Rate: $20.00/hr"],
    ],)
    pad = (lambda row, n=10: row + [""] * (n - len(row)))
    rows: list[list[Any]] = [
        pad([header]),
        pad(["W E E K L Y L A B O R H O U R S"]),
        pad(["W E E K", "J u n e 2 2 , 2 0 2 6 — J u n e 2 8 , 2 0 2 6"]),
        ["JOB TITLE", "WORKER NAMES", *DAYS, "TOTAL"],
        ["", "", "Mon __", "Tue __", "Wed __", "Thu __", "Fri __", "Sat __", "Sun __", ""],
    ]
    for _ in range(10):
        rows.append(["L", "Worker Name", "", "", "", "", "", "", "", "0"])
    if covered_cells:
        rows.append(["T O T A L H O U R S P E R D A Y", "", "", "", "", "", "", "", "", "0"])
        summary = [
            ["D E S C R I P T I O N", "", "H O U R S", "", "O T H O U R S", "", "R A T E", "", "A M O U N T", ""],
            ["Total Labor Hours", "", "60", "", "—", "", "$20.00", "", "$0.00", ""],
            ["Gas / Fuel (Randy Meza — round trip driving)", "", "—", "", "—", "", "—", "", "—", ""],
            ["Cleaning Supplies / Materials", "", "—", "", "—", "", "—", "", "—", ""],
            ["Subtotal", "", "60", "", "—", "", "—", "", "$0.00", ""],
            ["T O T A L D U E", "", "", "", "", "", "", "", "$0.00", ""],
        ]
    else:
        rows.append(pad(["T O T A L H O U R S P E R D A Y", "", "", "", "", "", "", "", "0"]))
        summary = [
            pad(["D E S C R I P T I O N", "H O U R S", "O T H O U R S", "R A T E", "A M O U N T"]),
            pad(["Total Labor Hours", "60", "—", "$20.00", "$0.00"]),
            pad(["Gas / Fuel (Randy Meza — round trip driving)", "—", "—", "—", "—"]),
            pad(["Cleaning Supplies / Materials", "—", "—", "—", "—"]),
            pad(["Subtotal", "60", "—", "—", "$0.00"]),
            pad(["T O T A L D U E", "$0.00"]),
        ]
    rows.append(pad(["S U M M A R Y"]))
    rows.extend(summary)
    rows.append(pad(["N O T E S"]))
    rows.append(pad(["▸ Note 1: Add project details here"]))
    rows.append(pad(["▸ Note 2: Add labor summary here"]))
    rows.append(pad(["▸ Note 3: Add status / additional info here"]))
    rows.append(pad(["Authorized signature: ________________ MAAI Multiservices LLC Date: ____________"]))
    b.content.append(b.table(rows))
    return {"body": {"content": b.content}}


def _chars(doc: dict[str, Any]) -> list[list]:
    out: list[list] = []

    def walk(content):
        for el in content:
            if "paragraph" in el:
                for run in el["paragraph"]["elements"]:
                    for i, ch in enumerate(run["textRun"]["content"]):
                        out.append([run["startIndex"] + i, ch])
            elif "table" in el:
                for row in el["table"]["tableRows"]:
                    for cell in row["tableCells"]:
                        walk(cell["content"])

    walk(doc["body"]["content"])
    return out


def apply(doc: dict[str, Any], requests: list[dict[str, Any]]) -> str:
    """Apply insert/delete requests like Google Docs does; return the final text."""
    chars = _chars(doc)
    for req in requests:
        if "deleteContentRange" in req:
            s = req["deleteContentRange"]["range"]["startIndex"]
            e = req["deleteContentRange"]["range"]["endIndex"]
            assert e > s
            removed = [c for c in chars if s <= c[0] < e]
            assert all(c[1] != "\n" for c in removed), "must never delete a cell's final newline"
            chars = [c for c in chars if not (s <= c[0] < e)]
            for c in chars:
                if c[0] >= e:
                    c[0] -= e - s
        elif "insertText" in req:
            at = req["insertText"]["location"]["index"]
            text = req["insertText"]["text"]
            for c in chars:
                if c[0] >= at:
                    c[0] += len(text)
            chars.extend([at + i, ch] for i, ch in enumerate(text))
        else:
            raise AssertionError(f"unexpected request {req}")
    return "".join(ch for _, ch in sorted(chars, key=lambda c: c[0]))
