# MAAI AI Office: Plan

_Last updated: November 2026_

## Build order (one at a time; each one tested in practice mode first)

| # | Piece | Status |
|---|---|---|
| 1 | 🧭 Director + 🧾 Invoice Agent + approval gate, activity log, cost meter, backups | ✅ built, ready for setup |
| 2 | 🏢 **Virtual Office** (web page for computer + phone) | next, after #1 runs with real activity |
| 3 | 💬 Client messages (EN/ES emails & texts, Google review requests) | planned |
| 4 | 📥 Leads (Angi / Thumbtack quick replies) | planned |
| 5 | 🌐 Website (maaiservice.com portfolio) | planned |
| 6 | 🎬 Video & social (editing, captions, posting) | planned |

## How the office works

```
You (Telegram or Virtual Office, English/Spanish, text or voice)
            │
        DIRECTOR ── task board (To Do / In Progress / Waiting for Me / Done)
   ┌─────┬──┴───┬────────┬──────────────┐
Invoice Client  Leads   Website   Video & Social
        msgs
            │
     APPROVAL GATE ── the only code that can send / publish / post / delete
```

- Agents only prepare **drafts**. The approval gate sends only after you tap ✅, and each approval runs once.
- Agents share information through the Director and the task board, so nothing is done twice.
- Teamwork rule (later): when the Website agent publishes a project, it posts a "project published" event; the Director then asks the Social agent for "new project" posts linking to the site, for your approval.

## Agents and models

| Agent | Model | Why |
|---|---|---|
| Director | Claude Sonnet 5.5 | Understands EN/ES, routes well |
| Invoice | Claude Haiku 5.5 | Fills the template; code does the math |
| Client messages | Claude Sonnet 5.5 | Client-facing writing |
| Leads | Claude Sonnet 5.5 | Client-facing, speed matters |
| Website | Claude Haiku 5.5 | Short descriptions you approve |
| Video & social | Claude Opus 5.5 (plans), Sonnet (captions), Haiku (sorting) | Quality where it shows |

Prices per million tokens: Haiku $0.10 / $0.50, Sonnet $2 / $10, Opus $4 / $20. Prompt caching bills repeated instructions at about 5% of the normal price.

## Monthly cost estimate (about 40 jobs a month)

| Item | Now (Director + Invoice) | Full team |
|---|---|---|
| Claude API | $10–15 | $25–40 |
| Always-on server (Hetzner, 2 CPU / 4 GB) | $7–12 | $7–12 |
| Telegram, Gmail/Drive/Wix APIs, Virtual Office | $0 | $0 |
| Google storage for videos | $0 | $2–10 |
| AI voiceover (optional) | — | $0–6 |
| AI clips/images (pay per use, capped) | — | $0–10 |
| Posting service | — | $0 (Wix, 10 posts/mo) – ~$24 |
| **Total** | **~$17–27** | **~$35–100 (likely ~$60–70)** |

## 🏢 Virtual Office (next build)

A web page you open on your computer or phone that shows the office live.

**What you'll see**
- **Office floor:** each agent has a desk with a character, name and role, and a live status light:
  🟢 working · 🟡 waiting for your approval · ✅ done · ⚪ idle. Working agents show a small "typing" animation.
- **Click an agent:** what it's working on, a progress bar, its recent activity, and a chat box to ask it questions or give it a new task.
- **Task board:** four columns: To Do · In Progress · Waiting for Me · Done. Click a card for details.
- **Approvals inbox:** every preview (invoice PDF, email text, later photos/videos/posts) with ✅ Approve / ❌ Reject. It's the same approval gate as Telegram: approve in either place, and it runs once.
- **Cost counter:** this month's AI spending vs. your limit, with a per-agent breakdown.
- **Look:** MAAI brand colors (I'll pull the exact colors from maaiservice.com and your brochure), simple, clean and a little fun. Works on phone screens and can be added to your home screen like an app.

**Login (only you)**
- Password (stored scrambled, never in plain text) **plus** a 6-digit code the bot sends to your Telegram. No extra app needed.
- Stays signed in on your own devices for 30 days. Locks after 5 wrong tries. Every login is logged.
- Secure address with free HTTPS, e.g. `https://office.maaiservice.com`.
  **Manual step:** add one DNS record for the subdomain in your Wix domain settings (about 5 minutes; I'll guide you).

**How it's built (cheap and simple)**
- Runs inside the same program on the same server, reading the same task board, approvals and costs, so it costs **$0 extra**.
- Live updates without refreshing the page.
- The office has no extra powers: everything goes through the Director, the task board and the approval gate, and every click is in the activity log ("via office").

## Security

- Secrets only in `.env` (private file, in `.gitignore`); logs automatically hide keys and tokens.
- Least access: agents have no built-in file/web/shell tools; each gets only its own tools; a safety check blocks anything else and logs it. The AI engine receives only the Anthropic key.
- Card, bank account and SSN numbers are detected and removed before anything is stored or sent to the AI.
- Approval required before any send/publish/post/delete; agents have no payment tools at all.
- Activity log without private details; nightly backup to Google Drive (30 days kept; old backups go to Drive's trash, recoverable for 30 more days).
- Telegram bot answers only your account. The server firewall only allows SSH (and HTTPS once the Virtual Office is added).

## Spending limit

1. **Anthropic Console:** a workspace "MAAI Agents" with a monthly limit (start at $30). The API key lives in that workspace.
2. **Our own meter** (`config/settings.yaml` → `budget`): warnings on Telegram at 50% / 80% / 95% of $25; at 100% only the Director and invoices keep working. Each job also has a $0.50 safety cap.

## Things that need manual work

- One-time accounts: Anthropic, Telegram bot, Google Cloud sign-in, server (see SETUP.md).
- Virtual Office: one DNS record in Wix.
- Website agent (later): a Wix API key; adding a "Post-construction" portfolio collection may need one click in the Editor.
- Social (later): you log in once to Instagram/Facebook/TikTok/Google to connect them. API posts can't use trending sounds.
- Leads (later): Thumbtack has no public API for small businesses, so you'll paste the drafted reply into the Thumbtack app.
- Google review link: copy it once from your Google Business Profile.

## Decisions made with defaults (tell me if you want them changed)

- Phone channel: **Telegram** (WhatsApp can be added later).
- Invoices: your template handles both **weekly labor hours** and **flat-price services**; numbers look like **INV-2026-001**; payment due **14 days** after the invoice date (used for reminders).
- Phone on invoices: **(470) 709-1901** (from your template; your website shows (770) 294-2348). Change it in `config/business.yaml`.
- Email account: whichever Google account you sign in with during setup (it must be able to open the invoice template).
