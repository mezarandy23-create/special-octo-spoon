import logging

import pytest

from maai.security.guard import SensitiveDataError, ensure_clean, scan, scrub
from maai.security.redact import RedactingFormatter, Redactor


@pytest.mark.parametrize("text", [
    "card 4111 1111 1111 1111 exp 12/29",
    "Visa: 4111-1111-1111-1111",
    "amex 378282246310005",
])
def test_card_numbers_are_detected(text):
    assert [f.kind for f in scan(text)] == ["card"]


@pytest.mark.parametrize("text", [
    "Call me at (470) 709-1901",
    "Invoice INV-2026-001 total $1,180.00",
    "PO 4471, 58 hours, week of 2026-11-03",
    "order 1234 5678 9012 3456",          # 16 digits but fails the card checksum
    "Address: 5675 Jimmy Carter Blvd, Norcross GA 30071",
])
def test_normal_business_text_is_not_blocked(text):
    assert scan(text) == []


def test_ssn_and_bank_numbers():
    assert [f.kind for f in scan("SSN 123-45-6789")] == ["ssn"]
    assert [f.kind for f in scan("su seguro social es 123456789")] == ["ssn"]
    assert [f.kind for f in scan("routing number 021000021 account # 123456789012")] == ["bank", "bank"]
    assert [f.kind for f in scan("número de cuenta: 000123456789")] == ["bank"]


def test_scrub_replaces_and_reports():
    clean, kinds = scrub("Pay with 4111 1111 1111 1111 please")
    assert "4111" not in clean
    assert "[REMOVED: card number]" in clean
    assert kinds == ["card number"]


def test_ensure_clean_raises():
    with pytest.raises(SensitiveDataError):
        ensure_clean("acct 9876543210", "notes")
    assert ensure_clean("Gate code is on the side door", "notes")


def test_logs_never_show_secrets():
    redactor = Redactor(["my-very-secret-value-123"])
    formatter = RedactingFormatter(redactor, "%(message)s")
    record = logging.LogRecord("x", logging.INFO, __file__, 1,
                               "key=%s token=%s other=%s", ("sk-" + "ant-api03-abcdefghijklmnop",
                                                           "123456789:" + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
                                                           "my-very-secret-value-123"), None)
    line = formatter.format(record)
    assert "sk-ant" not in line and "ABCDEFGHIJ" not in line and "my-very-secret" not in line
    assert line.count("[SECRET]") == 3
