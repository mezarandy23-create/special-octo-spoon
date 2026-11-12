"""Test setup: a throwaway office in a temp folder, fake clients, and a fake AI.

The FakeRunner replaces Claude: each test scripts what an agent "decides" and
the real tools run for real (database, approval gate, invoice math, files).
No API calls, no costs, nothing leaves the computer.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from maai.agents.base import RunResult
from maai.app import build_app
from maai.config import load_config
from maai.integrations.workspace import LocalWorkspace

REPO = Path(__file__).resolve().parent.parent
SECRETS = {
    "ANTHROPIC_API_KEY": "sk-" + "ant-test-not-a-real-key-000000",   # built in pieces: obviously fake
    "TELEGRAM_BOT_TOKEN": "123456789:" + "A" * 35,
    "TELEGRAM_OWNER_ID": "42",
    "OWNER_EMAIL": "owner@example.com",
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "config", tmp_path / "config")
    shutil.copytree(REPO / "prompts", tmp_path / "prompts")
    shutil.copyfile(REPO / "config" / "business.example.yaml", tmp_path / "config" / "business.yaml")
    return tmp_path


@pytest.fixture
def config(root: Path):
    return load_config(root=root, secrets=dict(SECRETS))


class FakeRunner:
    """Stands in for Claude. Register a script per agent with `on()`."""

    def __init__(self) -> None:
        self.scripts = {}
        self.prompts: list[tuple[str, str]] = []

    def on(self, agent: str, script) -> None:
        self.scripts[agent] = script

    async def run(self, spec, prompt, ctx):
        self.prompts.append((spec.name, prompt))
        tools = {t.name: t for t in spec.tools_factory(ctx)}

        async def call(name: str, **args):
            return await tools[name].handler(args)

        text = await self.scripts[spec.name](call, prompt, ctx)
        return RunResult(text=text, cost_usd=0.01, model="fake-model", usage={"input_tokens": 100})


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def app(config, runner):
    application = build_app(config, workspace=LocalWorkspace(config.data_dir), runner=runner)
    yield application
    application.db.close()


def result_text(tool_result: dict) -> str:
    return tool_result["content"][0]["text"]
