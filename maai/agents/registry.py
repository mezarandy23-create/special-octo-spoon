"""The team roster. To add an agent later (crew scheduling, estimates, ...):
write its prompt in prompts/, its tools in maai/agents/<name>/, add one
entry here, and add its model in config/settings.yaml.
"""

from __future__ import annotations

from .base import AgentSpec
from .director import director_tools
from .invoice.tools import invoice_tools


def build_registry() -> dict[str, AgentSpec]:
    agents = [
        AgentSpec(
            name="director", title="Director", role="Takes your requests, assigns work, keeps you posted",
            emoji="🧭", prompt_file="director.md", tools_factory=director_tools, accepts_tasks=False,
        ),
        AgentSpec(
            name="invoice", title="Invoice Agent", role="Drafts invoices, tracks unpaid ones, drafts reminders",
            emoji="🧾", prompt_file="invoice.md", tools_factory=invoice_tools,
        ),
    ]
    return {a.name: a for a in agents}
