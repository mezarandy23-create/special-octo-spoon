# MAAI AI Office

A team of AI agents for **MAAI Multiservices LLC** (cleaning: residential, commercial and post-construction, Norcross GA).
You talk to the **Director** from your phone (Telegram), in English or Spanish. It hands work to specialist agents.
**Nothing is sent, published or posted until you tap ✅.**

| Agent | Status | What it does |
|---|---|---|
| 🧭 Director | ✅ built | Takes your requests, assigns tasks, tracks progress, reports back |
| 🧾 Invoice Agent | ✅ built | Makes invoices from your MAAI template, tracks unpaid ones, drafts polite reminders |
| 🏢 Virtual Office | next | Web page showing every agent, the task board, approvals and costs |
| 💬 Client messages | planned | Emails/texts in English or Spanish, Google review requests |
| 📥 Leads | planned | Fast replies to Angi / Thumbtack leads |
| 🌐 Website | planned | Adds new projects to the maaiservice.com portfolio |
| 🎬 Video & social | planned | Edits your job videos, writes captions, schedules posts |

The full plan, costs and Virtual Office design are in [docs/PLAN.md](docs/PLAN.md).
Step-by-step setup is in [docs/SETUP.md](docs/SETUP.md).

## How a request flows

```
You (Telegram) ──> Director ──> task board ──> Invoice Agent
                                                  │ prepares the invoice + email as a DRAFT
                                                  ▼
            you get the PDF + preview with  ✅ Approve / ❌ Reject
                                                  │ only after ✅
                                                  ▼
                                 approval gate sends the email (once)
```

## Examples (write or send a voice note)

- *Invoice Berry College, week of Nov 2: Ana 8h Mon–Fri, Luis 6h Mon–Wed, gas $20, PO 4471, email ap@berry.edu*
- *Factura para Juan Pérez, limpieza profunda $250, juan@email.com*
- *Who still owes me money?* / *¿Quién me debe?*
- *Juan paid INV-2026-004*

Telegram commands: `/status` `/tasks` `/approvals` `/costs` `/help`

## Practice mode (on by default)

`dry_run: true` in `config/settings.yaml`:
- invoices are numbered `TEST-INV-…` and saved in a **TEST Invoices** folder;
- emails go **only to you**, marked `[TEST]`, never to the client;
- before Google is connected, files go to `data/` and emails are saved as files in `data/outbox/`.

Switch to `dry_run: false` only after you've tried everything.

## Safety, in short

- **Secrets** live only in `.env` on the server (private file, never uploaded); logs automatically hide keys and tokens.
- **Least access:** agents have no file, web or shell access, only their own short list of business tools. The Director can't approve or send anything.
- **No card, bank account or Social Security numbers** are stored. They're detected and removed automatically.
- **Your approval** is required for every send/publish/post/delete. Each approval can only run once.
- **Activity log** of every action (which agent, what, when) without private details: `logs/activity-YYYY-MM.jsonl`.
- **Nightly backup** (database, invoices, logs) to Google Drive → *MAAI Agents/Backups*, 30 days kept.
- **Spending:** monthly limit with warnings at 50% / 80% / 95%; each job also has its own cost cap.

## Commands (on the server)

```bash
python -m maai doctor   # check setup, says what's missing
python -m maai chat     # practice chat in the terminal
python -m maai run      # the real thing (the server runs this automatically)
python -m maai backup   # backup now
pytest                  # run the automatic tests (fake clients, no AI cost)
```

## Adding an agent later

1. Write its instructions in `prompts/<name>.md` (short!).
2. Give it tools in `maai/agents/<name>/tools.py`. Anything that sends or publishes must go through the approval gate.
3. Add one entry in `maai/agents/registry.py` and its model in `config/settings.yaml`.
