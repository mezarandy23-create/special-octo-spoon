"""Director + task board + dispatcher + approvals working together (fake AI)."""

from maai.agents.base import AgentSpec, ClaudeAgentRunner, RunContext
from maai.agents.common_tools import common_tools
from maai.status import agent_statuses, status_text

from .conftest import result_text


async def test_director_hands_invoice_to_specialist_and_waits_for_approval(app, runner):
    async def director(call, prompt, ctx):
        res = await call("assign_task", agent="invoice", title="Factura Juan Perez",
                         details="Deep clean $250, juan@example.com")
        assert "Task #1" in result_text(res)
        return "¡Listo! El agente de facturas está preparando la factura."

    async def invoice(call, prompt, ctx):
        assert "Deep clean $250" in prompt
        res = await call("create_invoice", kind="flat", client_name="TEST Juan Perez", client_email="juan@example.com",
                         project="Deep clean", services=[{"description": "Deep clean", "amount": 250}])
        assert not res.get("is_error"), res
        return "Factura lista para aprobar."

    runner.on("director", director)
    runner.on("invoice", invoice)
    shown = []

    async def on_approval(event):
        shown.append(event["approval"])

    app.bus.subscribe("approval.created", on_approval)

    reply = await app.director.handle("Factura para Juan Perez, limpieza profunda $250, juan@example.com")
    assert reply.startswith("¡Listo!")
    task = app.tasks.get(1)
    assert task["status"] == "todo" and task["agent"] == "invoice"

    await app.dispatcher.run_task(1)
    assert app.tasks.get(1)["status"] == "waiting_for_me"
    assert len(shown) == 1 and shown[0]["task_id"] == 1
    assert [s["state"] for s in agent_statuses(app) if s["agent"] == "invoice"] == ["waiting"]

    await app.gate.approve(shown[0]["id"])
    assert app.tasks.get(1)["status"] == "done"
    assert app.budget.spent() > 0                        # both runs were costed
    assert "Invoice Agent" in status_text(app)


async def test_specialist_question_goes_to_owner_and_answer_restarts_task(app, runner):
    asked = []

    async def invoice(call, prompt, ctx):
        if "juan@example.com" not in prompt:
            await call("ask_owner", question="What is Juan's email?")
            return "Waiting for the email."
        return "Got it."

    async def director(call, prompt, ctx):
        await call("continue_task", task_id=1, info="juan@example.com")
        return "Thanks, passing it on."

    runner.on("invoice", invoice)
    runner.on("director", director)

    async def on_notify(event):
        asked.append(event["text"])

    app.bus.subscribe("notify.owner", on_notify)
    app.tasks.create("invoice", "Invoice Juan", "Deep clean $250")
    await app.dispatcher.run_task(1)
    assert app.tasks.get(1)["status"] == "waiting_for_me"
    assert "What is Juan's email?" in asked[-1]

    await app.director.handle("juan@example.com")
    assert app.tasks.get(1)["status"] == "todo"          # restarted with the answer
    await app.dispatcher.run_task(1)
    assert app.tasks.get(1)["status"] == "done"


async def test_card_numbers_never_reach_the_ai(app, runner):
    seen = []

    async def director(call, prompt, ctx):
        seen.append(prompt)
        return "Ok."

    runner.on("director", director)
    reply = await app.director.handle("Client paid with card 4111 1111 1111 1111")
    assert "4111" not in seen[0]
    assert "🔒" in reply
    assert "4111" not in str(app.db.query("SELECT text FROM chat"))


async def test_budget_warnings_and_pause(app, runner):
    async def director(call, prompt, ctx):
        return "Ok."

    runner.on("director", director)
    notes = []

    async def on_notify(event):
        notes.append(event["text"])

    app.bus.subscribe("notify.owner", on_notify)
    app.budget.record("director", 13.0)                    # 52% of the $25 test limit
    await app.dispatcher.check_budget_warnings()
    await app.dispatcher.check_budget_warnings()           # same threshold is not repeated
    assert len(notes) == 1 and "52%" in notes[0]

    # Over the limit: a non-essential agent pauses, essential ones keep working.
    app.budget.record("director", 20.0)
    app.registry["helper"] = AgentSpec(name="helper", title="Helper", role="test", emoji="🧪",
                                       prompt_file="invoice.md", tools_factory=common_tools)
    task = app.tasks.create("helper", "extra work")
    await app.dispatcher.run_task(task["id"])
    assert app.tasks.get(task["id"])["status"] == "waiting_for_me"
    assert app.budget.allowed("invoice") and app.budget.allowed("director")


async def test_cancel_drops_pending_preview(app, runner):
    async def director(call, prompt, ctx):
        await call("cancel_task", task_id=1)
        return "Cancelled."

    runner.on("director", director)
    task = app.tasks.create("invoice", "Invoice to cancel")
    await app.invoices.create_draft({
        "kind": "flat", "client_name": "TEST A", "client_email": "a@example.com", "project": "x",
        "services": [{"description": "Clean", "amount": 100}]}, task_id=task["id"])
    await app.director.handle("cancel that invoice")
    assert app.gate.pending() == []
    assert app.tasks.get(1)["status"] == "cancelled"


async def test_agent_engine_is_locked_down(app):
    """The real Claude runner: no built-in tools, only the agent's own tools, only the API key."""
    runner = ClaudeAgentRunner(app)
    ctx = RunContext(app=app, agent="invoice", task_id=None)
    options = runner.build_options(app.registry["invoice"], ctx)

    assert options.tools == []
    assert options.permission_mode == "dontAsk"
    assert options.setting_sources == []
    assert options.allowed_tools and all(t.startswith("mcp__invoice__") for t in options.allowed_tools)
    assert "mcp__invoice__create_invoice" in options.allowed_tools
    assert set(options.env) == {"ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR"}   # no Telegram/Google secrets
    assert options.model == "claude-haiku-5-5"
    assert options.max_budget_usd == 0.5

    check = options.hooks["PreToolUse"][0].hooks[0]
    blocked = await check({"tool_name": "Bash", "tool_input": {}}, None, {})
    assert blocked["hookSpecificOutput"]["permissionDecision"] == "deny"
    allowed = await check({"tool_name": "mcp__invoice__list_invoices", "tool_input": {}}, None, {})
    assert allowed == {}
    actions = [a["action"] for a in app.activity.recent("invoice")]
    assert "tool_blocked" in actions and "tool_call" in actions

    director_opts = runner.build_options(app.registry["director"], RunContext(app=app, agent="director"))
    names = [t.rsplit("__", 1)[-1] for t in director_opts.allowed_tools]
    assert "assign_task" in names
    assert not any("approve" in n or "send" in n for n in names)    # the Director can't approve or send
