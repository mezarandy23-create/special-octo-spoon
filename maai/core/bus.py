"""A tiny message bus so parts of the office can react to each other.

Examples:
  "task.updated"      -> Telegram / Virtual Office refresh
  "approval.created"  -> Telegram shows the preview with ✅ / ❌ buttons
  later: "website.project_published" -> Director asks the social agent for posts
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        self._handlers[event].append(handler)

    async def publish(self, event: str, payload: dict[str, Any] | None = None) -> None:
        payload = dict(payload or {})
        payload.setdefault("event", event)
        handlers = self._handlers.get(event, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                await handler(payload)
            except Exception:  # one broken listener must not stop the others
                log.exception("Event handler failed for %s", event)

    def publish_soon(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """Fire-and-forget version for code that is not async."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish(event, payload))
