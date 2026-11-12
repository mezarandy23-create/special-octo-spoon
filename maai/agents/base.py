"""The shell every agent runs in (built on the Claude Agent SDK).

Least access, enforced in code:
  * Built-in tools are switched OFF (no file access, no web, no shell commands).
  * Each agent only gets its own short list of business tools.
  * A safety check runs before every tool call and blocks anything not on
    the agent's list. Every tool call is written to the activity log (tool
    name only, no private details).
  * The AI engine only receives the Anthropic API key, never Telegram or
    Google credentials.
  * Each run has a turn limit and a dollar limit, so a confused agent can't
    loop forever or run up a bill.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    from ..app import App

log = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    name: str                     # short id, e.g. "invoice"
    title: str                    # shown in Telegram / the office, e.g. "Invoice Agent"
    role: str                     # one line: what it does
    emoji: str
    prompt_file: str              # file in prompts/
    tools_factory: Callable[["RunContext"], list[Any]]
    accepts_tasks: bool = True    # False for the Director (it hands out tasks)


@dataclass
class RunContext:
    app: "App"
    agent: str
    task_id: int | None = None
    asked_owner: bool = False
    requested_approval: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    text: str
    cost_usd: float = 0.0
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    error: str | None = None


class AgentRunner(Protocol):
    async def run(self, spec: AgentSpec, prompt: str, ctx: RunContext) -> RunResult: ...


def friendly_error(error: str | None) -> str:
    """Turn a technical error into something the owner can act on."""
    text = (error or "").lower()
    if "api key" in text or "authentication" in text:
        return "My AI key isn't working. Check ANTHROPIC_API_KEY in .env (Anthropic Console > API keys)."
    if "credit" in text or "billing" in text:
        return "The Anthropic account is out of credit. Add credit in the Anthropic Console (Billing)."
    if "spend limit" in text or "usage limit" in text:
        return "The Anthropic Console spending limit was reached. Raise it in the Console, or wait for next month."
    if "max_budget" in text:
        return "This job hit its safety cost limit (per_task_max_usd) and was stopped."
    if "max_turns" in text:
        return "This job took too many steps and was stopped. Try giving more details."
    if "overloaded" in text or "529" in text or "timeout" in text or "connection" in text:
        return "The AI service is busy or unreachable right now. Please try again in a few minutes."
    return f"Something went wrong ({(error or 'unknown error')[:150]})."


def text_result(text: str, is_error: bool = False) -> dict[str, Any]:
    """The reply format tools hand back to the agent."""
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def load_prompt(prompts_dir: Path, spec: AgentSpec) -> str:
    return (prompts_dir / spec.prompt_file).read_text(encoding="utf-8").strip()


class ClaudeAgentRunner:
    """Runs an agent with the Claude Agent SDK."""

    def __init__(self, app: "App"):
        self.app = app
        self.workdir = app.config.data_dir / "agent_home"
        self.claude_config_dir = app.config.data_dir / "claude_config"
        for folder in (self.workdir, self.claude_config_dir):
            folder.mkdir(parents=True, exist_ok=True)

    def build_options(self, spec: AgentSpec, ctx: RunContext):
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, create_sdk_mcp_server

        tools = spec.tools_factory(ctx)
        server = create_sdk_mcp_server(name=spec.name, version="1.0.0", tools=tools)
        allowed = [f"mcp__{spec.name}__{t.name}" for t in tools]
        settings = self.app.config.agent_settings(spec.name)
        activity = self.app.activity
        ref = f"task#{ctx.task_id}" if ctx.task_id else None

        async def safety_check(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
            tool_name = input_data.get("tool_name", "")
            if tool_name not in allowed:
                activity.record(spec.name, "tool_blocked", ref=ref, status="blocked", note=tool_name)
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "This agent is not allowed to use that tool.",
                    }
                }
            activity.record(spec.name, "tool_call", ref=ref, note=tool_name.rsplit("__", 1)[-1])
            return {}

        return ClaudeAgentOptions(
            system_prompt=load_prompt(self.app.config.prompts_dir, spec),
            model=settings.get("model"),
            effort=settings.get("effort"),
            max_turns=int(settings.get("max_turns", 10)),
            max_budget_usd=self.app.budget.per_task_max,
            tools=[],                         # no built-in tools at all
            allowed_tools=allowed,            # only this agent's business tools
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch", "Agent", "Task"],
            mcp_servers={spec.name: server},
            strict_mcp_config=True,
            permission_mode="dontAsk",        # anything not allowed is refused
            setting_sources=[],               # ignore any settings files on the machine
            cwd=str(self.workdir),
            env={
                "ANTHROPIC_API_KEY": self.app.config.secret("ANTHROPIC_API_KEY"),
                "CLAUDE_CONFIG_DIR": str(self.claude_config_dir),
            },
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[safety_check])]},
            stderr=lambda line: log.debug("agent engine: %s", line),
        )

    async def run(self, spec: AgentSpec, prompt: str, ctx: RunContext) -> RunResult:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query

        if not self.app.config.secret("ANTHROPIC_API_KEY"):
            return RunResult(text="", is_error=True, error="ANTHROPIC_API_KEY is missing from .env")

        options = self.build_options(spec, ctx)
        texts: list[str] = []
        final = None
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    texts.extend(block.text for block in message.content if isinstance(block, TextBlock))
                elif isinstance(message, ResultMessage):
                    final = message
        except Exception as exc:
            log.exception("Agent %s crashed", spec.name)
            return RunResult(text="", is_error=True, error=f"{type(exc).__name__}: {exc}")

        if final is None:
            return RunResult(text="\n".join(texts), is_error=True, error="The agent stopped without a result")
        text = (final.result or (texts[-1] if texts else "")).strip()
        error = None
        if final.is_error:
            error = final.subtype
            if final.errors:
                error += ": " + "; ".join(final.errors)[:300]
        return RunResult(
            text=text,
            cost_usd=float(final.total_cost_usd or 0),
            model=options.model,
            usage=final.usage or {},
            is_error=bool(final.is_error),
            error=error,
        )
