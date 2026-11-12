"""Keeps secrets out of logs.

Every log line goes through `RedactingFormatter`, which blanks:
  * the exact values of every secret loaded from .env, and
  * anything shaped like an API key or access token.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),            # Anthropic keys
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b"),     # Telegram bot token
    re.compile(r"ya29\.[A-Za-z0-9_\-\.]+"),              # Google access token
    re.compile(r"1//[A-Za-z0-9_\-]{20,}"),               # Google refresh token
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]+"),               # Google client secret
]

MASK = "[SECRET]"


class Redactor:
    def __init__(self, secret_values: Iterable[str] = ()):
        # Only mask values long enough to be real secrets (avoid masking "1").
        self.values = sorted({v for v in secret_values if v and len(v) >= 8}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for value in self.values:
            text = text.replace(value, MASK)
        for pattern in SECRET_PATTERNS:
            text = pattern.sub(MASK, text)
        return text


class RedactingFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor, fmt: str):
        super().__init__(fmt)
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        return self.redactor(super().format(record))


def setup_logging(logs_dir: Path, secret_values: Iterable[str], level: int = logging.INFO) -> Redactor:
    redactor = Redactor(secret_values)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    formatter = RedactingFormatter(redactor, fmt)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(logs_dir / "maai.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # These libraries log full request URLs, and the Telegram URL contains the
    # bot token. Keep them quiet (the formatter would mask it anyway).
    for noisy in ("httpx", "httpcore", "telegram.ext._updater", "googleapiclient.discovery_cache"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return redactor
