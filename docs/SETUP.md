# Setup, step by step (about 1 hour)

You'll do this once. Take it one step at a time. If anything looks different on screen, tell me what you see and I'll guide you.

---

## Step 1: Anthropic (the AI), about 10 min

1. Go to **console.anthropic.com** and sign in (or create an account). This is separate from a Claude.ai subscription.
2. **Billing:** add prepaid credit (start with $10–20).
3. **Workspaces:** create a workspace called **MAAI Agents**. In its **spend limits**, set a monthly limit of **$30**.
4. **API keys:** inside the MAAI Agents workspace, create a key named `maai-server`. Copy it (starts with `sk-ant-`).
   Keep it private. You'll paste it into the server's `.env` file in step 5. Never send it in a chat or email.

## Step 2: Telegram bot, about 5 min

1. Install Telegram on your phone and open a chat with **@BotFather**.
2. Send `/newbot`. Name: `MAAI Director`. Username: something like `maai_office_bot` (must end in `bot`).
3. BotFather gives you a **token** (looks like `123456789:AA…`). Keep it private, same as the API key.
4. Still in BotFather: `/setjoingroups` → choose your bot → **Disable** (so nobody can add it to groups).

## Step 3: Google (Gmail drafts + Drive + Docs), about 15 min

Decide which Google account the agents use. Invoices will be emailed from it (for example `maaicleaning@gmail.com`).
**That account must be able to open your invoice template.** Your template is in the `randyalain23` Drive, so if you use the maaicleaning account, open the template and **Share** it with maaicleaning (Viewer is enough).

1. Go to **console.cloud.google.com** with that account → create a project called **MAAI Agents**.
2. **APIs & Services → Library:** enable **Gmail API**, **Google Drive API**, **Google Docs API**.
3. **OAuth consent screen** (Google Auth Platform): User type **External**, app name `MAAI Agents`, your email for the contact fields.
   Then under **Audience**, click **Publish app** ("In production"). Without this, Google logs the agents out every 7 days.
   (Google will show "unverified app" when you sign in. That's expected for your own private app.)
4. **Credentials → Create credentials → OAuth client ID → Desktop app** → name `maai-server` → **Download JSON**.
   You'll put this file on the server in step 5.
5. Copy your template's id: open **MAAI_Invoice_TEMPLATE**; the link looks like
   `docs.google.com/document/d/`**`1xGCY6K4…`**`/edit`. The bold part is the id.

## Step 4: The server, about 10 min

1. Create an account at **hetzner.com/cloud** → new project **MAAI**.
2. **Add server:** image **Ubuntu 24.04**; the cheapest shared plan with **2 vCPU / 4 GB RAM** (e.g. CX23); any location.
   Prices changed in 2026, so check it's around $7/month before confirming.
3. Open the server's **Console** button (a black terminal window in the browser) and log in as `root`.
4. Paste these two lines:
   ```bash
   apt-get update && apt-get install -y git
   git clone -b claude/youthful-gauss-figcyw https://github.com/mezarandy23-create/special-octo-spoon.git /opt/maai && bash /opt/maai/deploy/setup_server.sh
   ```
   (The new code is on the `claude/youthful-gauss-figcyw` branch until it's merged into `main`.)
   This installs everything, turns on the firewall and automatic security updates, and sets the office to start by itself.

## Step 5: Fill in your keys, about 10 min

In the server console:

1. `nano /opt/maai/.env` and fill in:
   - `ANTHROPIC_API_KEY=` (step 1)
   - `TELEGRAM_BOT_TOKEN=` (step 2)
   - `OWNER_EMAIL=` your email (practice emails go here)
   - `GOOGLE_INVOICE_TEMPLATE_ID=` (step 3.5)

   Save with **Ctrl+O**, Enter, then exit with **Ctrl+X**.
2. `nano /opt/maai/config/business.yaml`: check the phone number, add `sent_by` (your name) and your street address if you want it on invoices.
3. Google file: `nano /opt/maai/data/google_client_secret.json` → paste the full contents of the JSON from step 3.4 → save. Then make it private:
   `chown maai:maai /opt/maai/data/google_client_secret.json && chmod 600 /opt/maai/data/google_client_secret.json`
4. Connect Google:
   ```bash
   cd /opt/maai && sudo -u maai .venv/bin/python scripts/google_login.py
   ```
   Open the link it prints, sign in, allow access. The last page won't load; that's normal. Copy the full address from the browser bar and paste it back.
5. Check everything:
   ```bash
   sudo -u maai .venv/bin/python -m maai doctor
   ```

## Step 6: Start and say hi, about 5 min

1. `systemctl start maai`
2. On your phone, open your bot in Telegram and send `hi`. It answers with **your Telegram ID** (setup mode).
3. Put it in `.env` as `TELEGRAM_OWNER_ID=…`, then `systemctl restart maai`.
4. Send `/help`. The office is running in **practice mode**.

## Step 7: Practice (do this before going live)

Try a few of these with **fake clients and your own email**:
- *Invoice TEST Berry College, week of Nov 2: Ana 8h Mon–Fri, Luis 6h Mon–Wed, gas $20, PO 4471, email test@example.com*
- *Factura para TEST Juan, limpieza profunda $250, email test@example.com*
- Tap ✅ and check that the `[TEST]` email reaches **you**.
- Open the TEST invoice PDF: **check that every blank in your template got filled correctly.** If anything looks off, tell me and I'll adjust it.
- *Who still owes me money?* · `/status` · `/costs`

## Step 8: Go live

When you're happy: `nano /opt/maai/config/settings.yaml` → `dry_run: false` → `systemctl restart maai`.

---

### Optional: voice notes

```bash
cd /opt/maai && sudo -u maai .venv/bin/pip install faster-whisper && systemctl restart maai
```
The first voice note takes a minute while the speech model downloads (about 150 MB).

### Updating to a new version

```bash
cd /opt/maai && sudo -u maai git pull && sudo -u maai .venv/bin/pip install -r requirements.txt && systemctl restart maai
```

### Useful commands

| What | Command |
|---|---|
| See what it's doing | `journalctl -u maai -f` |
| Restart | `systemctl restart maai` |
| Stop | `systemctl stop maai` |
| Backup now | `cd /opt/maai && sudo -u maai .venv/bin/python -m maai backup` |
