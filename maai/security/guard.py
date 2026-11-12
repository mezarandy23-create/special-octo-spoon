"""Blocks card numbers, bank account numbers and Social Security numbers.

MAAI never stores these. Anything that comes in (your messages, agent tool
inputs) is checked here first. Matches are removed and replaced with a
marker like "[REMOVED: card number]".
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int


class SensitiveDataError(ValueError):
    """Raised when a value that must be stored contains blocked data."""


LABELS = {
    "card": "card number",
    "ssn": "Social Security number",
    "bank": "bank account number",
}

_CARD_RE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_SSN_RE = re.compile(r"(?<![\d-])\d{3}[- ]\d{2}[- ]\d{4}(?![\d-])")
_SSN_KEYWORD_RE = re.compile(
    r"\b(?:ssn|social security|seguro social|itin)\b\D{0,25}(\d{9})(?!\d)", re.IGNORECASE
)
_BANK_KEYWORD_RE = re.compile(
    r"\b(?:routing|aba|account|acct|cuenta|bank|banco|ruta)\b"
    r"(?:\s*(?:number|num|no\.?|n[uú]mero|#))?\s*[:#]?\s*(\d[\d -]{4,22}\d)",
    re.IGNORECASE,
)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number]
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def scan(text: str) -> list[Finding]:
    if not text:
        return []
    findings: list[Finding] = []

    for match in _CARD_RE.finditer(text):
        digits = _digits(match.group())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            findings.append(Finding("card", match.start(), match.end()))

    for match in _SSN_RE.finditer(text):
        findings.append(Finding("ssn", match.start(), match.end()))
    for match in _SSN_KEYWORD_RE.finditer(text):
        findings.append(Finding("ssn", match.start(1), match.end(1)))

    for match in _BANK_KEYWORD_RE.finditer(text):
        if len(_digits(match.group(1))) >= 6:
            findings.append(Finding("bank", match.start(1), match.end(1)))

    # Drop overlaps, keep the earliest/longest.
    findings.sort(key=lambda f: (f.start, -(f.end - f.start)))
    cleaned: list[Finding] = []
    for finding in findings:
        if cleaned and finding.start < cleaned[-1].end:
            continue
        cleaned.append(finding)
    return cleaned


def scrub(text: str) -> tuple[str, list[str]]:
    """Return (clean_text, kinds_removed)."""
    findings = scan(text)
    if not findings:
        return text, []
    out = []
    last = 0
    for finding in findings:
        out.append(text[last:finding.start])
        out.append(f"[REMOVED: {LABELS[finding.kind]}]")
        last = finding.end
    out.append(text[last:])
    return "".join(out), sorted({LABELS[f.kind] for f in findings})


def ensure_clean(value: str, field_name: str = "value") -> str:
    """Raise if `value` contains blocked data (used before saving records)."""
    kinds = sorted({LABELS[f.kind] for f in scan(value or "")})
    if kinds:
        raise SensitiveDataError(
            f"{field_name} looks like it contains a {', '.join(kinds)}. "
            "MAAI never stores those. Remove it and try again."
        )
    return value
