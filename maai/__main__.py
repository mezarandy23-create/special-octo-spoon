"""Start the MAAI office.

    python -m maai run      Telegram + background jobs (this is what the server runs)
    python -m maai chat     practice chat in this terminal (no Telegram needed)
    python -m maai doctor   check the setup and say what's missing
    python -m maai backup   make a backup right now
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from .config import SECRET_KEYS, load_config
from .security.redact import setup_logging

log = logging.getLogger("maai")


def _clear_inherited_ai_settings() -> None:
    """Use ONLY the key in .env: drop any Anthropic/Claude settings this process
    inherited from the shell, so a stray key or address can't be used by mistake."""
    import os

    for key in list(os.environ):
        if key.startswith(("ANTHROPIC_", "CLAUDE_")) or key == "CLAUDECODE":
            del os.environ[key]


def _boot():
    from .app import build_app

    _clear_inherited_ai_settings()
    config = load_config()
    setup_logging(config.logs_dir, config.secrets.values())
    for warning in config.warnings:
        log.warning(warning)
    return build_app(config)


async def _run() -> None:
    from .channels.telegram_bot import TelegramChannel
    from .jobs.scheduler import Scheduler

    app = _boot()
    telegram = TelegramChannel(app)
    scheduler = Scheduler(app)
    await app.dispatcher.start()
    await telegram.start()
    scheduler.start()
    log.info("MAAI office running (%s mode)", "practice" if app.config.dry_run else "LIVE")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    log.info("Shutting down")
    await scheduler.stop()
    await telegram.stop()
    await app.dispatcher.stop()


async def _chat() -> None:
    from .channels.console import ConsoleChannel

    app = _boot()
    console = ConsoleChannel(app)
    await app.dispatcher.start()
    await console.run()
    await app.dispatcher.stop()


def _doctor() -> int:
    config = load_config()
    ok = True

    def check(passed: bool, good: str, bad: str) -> None:
        nonlocal ok
        print(("  ✅ " + good) if passed else ("  ❌ " + bad))
        ok = ok and passed

    print("MAAI setup check")
    print(f"  Mode: {'PRACTICE (dry-run)' if config.dry_run else 'LIVE'}")
    for warning in config.warnings:
        print("  ⚠️ " + warning)
    env = config.root / ".env"
    check(env.exists(), ".env found", ".env missing: copy .env.example to .env and fill it in")
    check(bool(config.secret("ANTHROPIC_API_KEY")), "Anthropic API key set", "ANTHROPIC_API_KEY missing")
    check(bool(config.secret("TELEGRAM_BOT_TOKEN")), "Telegram bot token set", "TELEGRAM_BOT_TOKEN missing")
    check(config.secret("TELEGRAM_OWNER_ID").isdigit(), "Telegram owner id set",
          "TELEGRAM_OWNER_ID missing: start the bot and send it any message to see your id")
    token = config.root / config.secret("GOOGLE_TOKEN_FILE", "data/google_token.json")
    if token.exists():
        print("  ✅ Google connected")
        check(bool(config.secret("GOOGLE_INVOICE_TEMPLATE_ID")), "Invoice template id set",
              "GOOGLE_INVOICE_TEMPLATE_ID missing (see docs/SETUP.md)")
    else:
        print("  ⚪ Google not connected yet: practice files go to data/ (run scripts/google_login.py when ready)")
        if not config.dry_run:
            check(False, "", "LIVE mode needs Google connected")
    check(bool(config.secret("OWNER_EMAIL")), "Owner email set (TEST emails go here)", "OWNER_EMAIL missing")
    unknown = [k for k in config.secrets if k not in SECRET_KEYS]
    if unknown:
        print(f"  ⚠️ Unknown keys in .env (ignored): {', '.join(unknown)}")
    print("\nAll good!" if ok else "\nFix the ❌ items, then run this again.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maai", description="MAAI AI office")
    parser.add_argument("command", choices=["run", "chat", "doctor", "backup"])
    args = parser.parse_args(argv)
    if args.command == "run":
        asyncio.run(_run())
    elif args.command == "chat":
        asyncio.run(_chat())
    elif args.command == "doctor":
        return _doctor()
    elif args.command == "backup":
        from .jobs.backup import run_backup

        print("Backup saved:", run_backup(_boot()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
