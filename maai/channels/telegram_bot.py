"""Telegram: how you talk to the office from your phone.

Security:
  * The bot only answers YOUR Telegram account (TELEGRAM_OWNER_ID).
    Messages from anyone else are ignored.
  * Approvals are buttons handled by code (not by the AI). Only your
    account can press them, and each preview can be approved once.

Commands:  /status  /tasks  /approvals  /costs  /help
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from ..core.tasks import OPEN_STATUSES
from ..status import status_text

if TYPE_CHECKING:
    from ..app import App

log = logging.getLogger(__name__)
LIMIT = 4000

HELP = (
    "Hi! I'm the MAAI Director. Write (or send a voice note) in English or Spanish, for example:\n"
    "• Invoice Berry College, week of Nov 3: Ana 8h Mon–Fri, Luis 6h Mon–Wed, PO 4471, email ap@berry.edu\n"
    "• Factura para Juan Pérez, limpieza profunda $250, juan@email.com\n"
    "• Who still owes me money?\n"
    "• Juan paid INV-2026-004\n\n"
    "/status: what each agent is doing\n/tasks: open tasks\n/approvals: previews waiting for you\n"
    "/costs: AI spending this month"
)


def _chunks(text: str) -> list[str]:
    return [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)] or [""]


class TelegramChannel:
    def __init__(self, app: "App"):
        self.app = app
        token = app.config.secret("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from .env")
        owner = app.config.secret("TELEGRAM_OWNER_ID")
        self.owner_id: int | None = int(owner) if owner.strip().isdigit() else None
        # concurrent_updates: an ✅ tap is handled right away, even while the Director is busy answering.
        self.tg: Application = ApplicationBuilder().token(token).concurrent_updates(True).build()
        self._register_handlers()
        app.bus.subscribe("notify.owner", self._on_notify)
        app.bus.subscribe("approval.created", self._on_approval_created)

    # ---- setup -----------------------------------------------------------------
    def _register_handlers(self) -> None:
        if self.owner_id is None:
            # Setup mode: tell the person their id so they can put it in .env.
            self.tg.add_handler(MessageHandler(filters.ALL, self._setup_mode))
            return
        owner = filters.User(user_id=self.owner_id)
        self.tg.add_handler(CommandHandler(["start", "help"], self._help, filters=owner))
        self.tg.add_handler(CommandHandler("status", self._status, filters=owner))
        self.tg.add_handler(CommandHandler("tasks", self._tasks, filters=owner))
        self.tg.add_handler(CommandHandler("approvals", self._approvals, filters=owner))
        self.tg.add_handler(CommandHandler("costs", self._costs, filters=owner))
        self.tg.add_handler(CallbackQueryHandler(self._button, pattern=r"^ap:\d+:[yn]$"))
        self.tg.add_handler(MessageHandler(owner & filters.VOICE, self._voice))
        self.tg.add_handler(MessageHandler(owner & (filters.PHOTO | filters.VIDEO | filters.Document.ALL), self._media))
        self.tg.add_handler(MessageHandler(owner & filters.TEXT & ~filters.COMMAND, self._text))
        # Everyone else: ignored on purpose (no reply).

    async def start(self) -> None:
        await self.tg.initialize()
        await self.tg.start()
        await self.tg.updater.start_polling(drop_pending_updates=False)
        if self.owner_id:
            await self.send("🟢 MAAI office is online." + (" Practice mode (dry-run)." if self.app.config.dry_run else ""))

    async def stop(self) -> None:
        await self.tg.updater.stop()
        await self.tg.stop()
        await self.tg.shutdown()

    # ---- sending -----------------------------------------------------------------
    async def send(self, text: str, **kwargs: Any) -> None:
        if not self.owner_id:
            return
        parts = _chunks(text)
        for i, part in enumerate(parts):
            extra = kwargs if i == len(parts) - 1 else {}
            await self.tg.bot.send_message(chat_id=self.owner_id, text=part, **extra)

    async def _on_notify(self, event: dict[str, Any]) -> None:
        await self.send(event["text"])

    @staticmethod
    def _buttons(approval_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"ap:{approval_id}:y"),
            InlineKeyboardButton("❌ Reject", callback_data=f"ap:{approval_id}:n"),
        ]])

    async def _show_approval(self, approval: dict[str, Any]) -> None:
        if not self.owner_id:
            return
        attachment = approval.get("attachment")
        if attachment and Path(attachment).exists():
            with open(attachment, "rb") as fh:
                await self.tg.bot.send_document(chat_id=self.owner_id, document=fh,
                                                caption=f"📎 {approval['title']}"[:1000])
        text = f"🔔 Needs your OK (#{approval['id']})\n{approval['title']}\n\n{approval['preview']}"
        await self.send(text[: LIMIT - 50], reply_markup=self._buttons(approval["id"]))

    async def _on_approval_created(self, event: dict[str, Any]) -> None:
        await self._show_approval(event["approval"])

    # ---- handlers ------------------------------------------------------------------
    async def _setup_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if update.effective_message and user:
            await update.effective_message.reply_text(
                f"Setup: your Telegram ID is {user.id}. Put TELEGRAM_OWNER_ID={user.id} in .env and restart."
            )

    async def _help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(HELP)

    async def _status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(status_text(self.app))

    async def _tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rows = [t for t in self.app.tasks.list("open", limit=20)]
        if not rows:
            await update.effective_message.reply_text("No open tasks. 🎉")
            return
        names = {"todo": "To do", "in_progress": "In progress", "waiting_for_me": "Waiting for you"}
        lines = []
        for status in OPEN_STATUSES:
            group = [t for t in rows if t["status"] == status]
            if group:
                lines.append(f"{names[status]}:")
                lines.extend(f"  #{t['id']} {t['agent']}: {t['title']} ({t['progress']}%)" for t in group)
        await update.effective_message.reply_text("\n".join(lines))

    async def _approvals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        pending = self.app.gate.pending()
        if not pending:
            await update.effective_message.reply_text("Nothing waiting for your approval.")
        for approval in pending:
            await self._show_approval(approval)

    async def _costs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        b = self.app.budget.status()
        lines = [f"💰 {b['month']}: ${b['spent_usd']:.2f} of ${b['limit_usd']:.2f} ({b['percent']:.0f}%)"]
        lines.extend(f"  {agent}: ${usd:.2f}" for agent, usd in b["by_agent"].items())
        await update.effective_message.reply_text("\n".join(lines))

    async def _button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.from_user or query.from_user.id != self.owner_id:
            return
        await query.answer()
        _, approval_id, choice = query.data.split(":")
        approval_id = int(approval_id)
        await query.edit_message_reply_markup(reply_markup=None)
        if choice == "y":
            await query.message.reply_text("⏳ Working on it…")
            result = await self.app.gate.approve(approval_id)
        else:
            result = await self.app.gate.reject(approval_id)
        await query.message.reply_text(result)

    async def _keep_typing(self, chat_id: int, done: asyncio.Event) -> None:
        while not done.is_set():
            try:
                await self.tg.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(done.wait(), timeout=4)
            except asyncio.TimeoutError:
                pass

    async def _ask_director(self, update: Update, text: str) -> None:
        done = asyncio.Event()
        typing = asyncio.create_task(self._keep_typing(update.effective_chat.id, done))
        try:
            reply = await self.app.director.handle(text)
        finally:
            done.set()
            await typing
        for part in _chunks(reply):
            await update.effective_message.reply_text(part)

    async def _text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._ask_director(update, update.effective_message.text or "")

    async def _voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        from .voice import transcribe

        voice = update.effective_message.voice
        folder = self.app.config.data_dir / "voice"
        folder.mkdir(exist_ok=True)
        path = folder / f"{voice.file_unique_id}.ogg"
        tg_file = await context.bot.get_file(voice.file_id)
        await tg_file.download_to_drive(str(path))
        try:
            text = await asyncio.to_thread(transcribe, path, self.app.config.section("voice"))
        finally:
            path.unlink(missing_ok=True)   # voice notes are not kept
        if not text:
            await update.effective_message.reply_text(
                "I couldn't turn that voice note into text. Please type it, or see docs/SETUP.md (voice notes).")
            return
        await update.effective_message.reply_text(f"🎙️ I heard: {text}")
        await self._ask_director(update, text)

    async def _media(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Got it! Photos and videos will be handled by the Video & Social agent once it's added. For now, "
            "please upload job media to the 'MAAI Media / Subir aquí' folder in Google Drive."
        )
