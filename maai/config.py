"""Loads settings (config/*.yaml) and secrets (.env).

Secrets are kept in a private dictionary. They are never copied into the
process environment, so programs started by this one (like the Claude agent
engine) only receive the single key they need.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

SECRET_KEYS = (
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_ID",
    "OWNER_EMAIL",
    "GOOGLE_CLIENT_SECRET_FILE",
    "GOOGLE_TOKEN_FILE",
    "GOOGLE_INVOICE_TEMPLATE_ID",
)


@dataclass
class Config:
    root: Path
    settings: dict[str, Any]
    business: dict[str, Any]
    secrets: dict[str, str] = field(repr=False)
    warnings: list[str] = field(default_factory=list)

    # ---- paths -------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    # ---- switches ----------------------------------------------------
    @property
    def dry_run(self) -> bool:
        return bool(self.settings.get("dry_run", True))

    @property
    def timezone(self) -> str:
        return self.settings.get("timezone", "America/New_York")

    def secret(self, key: str, default: str = "") -> str:
        return self.secrets.get(key) or default

    def agent_settings(self, name: str) -> dict[str, Any]:
        return dict(self.settings.get("agents", {}).get(name, {}))

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.settings.get(name, {}) or {})


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _check_env_permissions(env_path: Path, warnings: list[str]) -> None:
    if os.name != "posix" or not env_path.exists():
        return
    mode = env_path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        warnings.append(
            ".env can be read by other users on this computer. "
            "Fix it with:  chmod 600 .env"
        )


def load_config(root: Path | None = None, secrets: dict[str, str] | None = None) -> Config:
    """Read settings + business info + secrets.

    `secrets` can be passed directly (used by tests); otherwise .env is read.
    """
    root = Path(root or os.environ.get("MAAI_HOME") or ROOT)
    warnings: list[str] = []

    settings = _read_yaml(root / "config" / "settings.yaml")

    business_path = root / "config" / "business.yaml"
    if not business_path.exists():
        business_path = root / "config" / "business.example.yaml"
        warnings.append(
            "config/business.yaml not found, using business.example.yaml. "
            "Copy it to business.yaml and check your details."
        )
    business = _read_yaml(business_path)

    if secrets is None:
        env_path = root / ".env"
        _check_env_permissions(env_path, warnings)
        raw = dotenv_values(env_path) if env_path.exists() else {}
        secrets = {k: (v or "").strip() for k, v in raw.items() if v}

    cfg = Config(root=root, settings=settings, business=business, secrets=dict(secrets), warnings=warnings)

    for folder in (cfg.data_dir, cfg.logs_dir):
        folder.mkdir(parents=True, exist_ok=True)
        try:
            folder.chmod(0o700)
        except OSError:
            pass
    return cfg
