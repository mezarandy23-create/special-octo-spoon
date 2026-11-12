"""Tools every specialist agent gets: ask you a question, report progress."""

from __future__ import annotations

from typing import Annotated, Any

from claude_agent_sdk import tool

from .base import RunContext, text_result


def common_tools(ctx: RunContext) -> list[Any]:
    tasks = ctx.app.tasks

    @tool("ask_owner",
          "Ask the owner a question when required information is missing. Ask everything you need in one "
          "short question. After calling this, stop working and end your turn.",
          {"question": Annotated[str, "One short, clear question for the owner"]})
    async def ask_owner(args: dict[str, Any]) -> dict[str, Any]:
        ctx.asked_owner = True
        if ctx.task_id:
            tasks.wait_for_owner(ctx.task_id, args["question"])
        return text_result("Question sent to the owner. Stop here; the task resumes when they answer.")

    @tool("report_progress", "Update the progress bar of the current task (0-100) with a few words.",
          {"percent": int, "note": Annotated[str, "Short status, e.g. 'Filling in the template'"]})
    async def report_progress(args: dict[str, Any]) -> dict[str, Any]:
        if ctx.task_id:
            tasks.set_progress(ctx.task_id, args["percent"], args.get("note", ""))
        return text_result("ok")

    return [ask_owner, report_progress]
