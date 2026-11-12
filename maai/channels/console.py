"""Practice chat in a terminal window, no Telegram needed.

    python -m maai chat

Type messages to the Director like you would on your phone.
  approve 3          approve preview #3
  reject 3 reason    reject preview #3
  status / tasks / costs / quit
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..status import status_text

if TYPE_CHECKING:
    from ..app import App


class ConsoleChannel:
    def __init__(self, app: "App"):
        self.app = app
        app.bus.subscribe("notify.owner", self._on_notify)
        app.bus.subscribe("approval.created", self._on_approval)

    async def _on_notify(self, event: dict[str, Any]) -> None:
        print(f"\n📣 {event['text']}\n> ", end="", flush=True)

    async def _on_approval(self, event: dict[str, Any]) -> None:
        a = event["approval"]
        print(f"\n🔔 Needs your OK (#{a['id']}): {a['title']}\n{a['preview']}")
        if a.get("attachment"):
            print(f"📎 File: {a['attachment']}")
        print(f"Type 'approve {a['id']}' or 'reject {a['id']}'\n> ", end="", flush=True)

    async def run(self) -> None:
        print("MAAI office: practice chat. Type 'quit' to exit.")
        print("Mode:", "PRACTICE (dry-run)" if self.app.config.dry_run else "LIVE")
        while True:
            line = (await asyncio.to_thread(input, "> ")).strip()
            if not line:
                continue
            word, _, rest = line.partition(" ")
            word = word.lower()
            if word in ("quit", "exit"):
                return
            if word == "status":
                print(status_text(self.app))
            elif word == "tasks":
                for t in self.app.tasks.list("open"):
                    print(f"#{t['id']} [{t['status']}] {t['agent']}: {t['title']} ({t['progress']}%)")
            elif word == "costs":
                print(self.app.budget.status())
            elif word in ("approve", "reject") and rest.split(" ", 1)[0].isdigit():
                approval_id, _, reason = rest.partition(" ")
                if word == "approve":
                    print(await self.app.gate.approve(int(approval_id)))
                else:
                    print(await self.app.gate.reject(int(approval_id), reason))
            else:
                print("Director is thinking…")
                print(await self.app.director.handle(line))
