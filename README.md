# SMS Spend Agent

An AI-powered agent that reads your Indian banking SMS in real time, stores transactions in the cloud, and delivers a rich daily spend summary to your inbox — all without keeping your laptop on.

Built for Indian users with HDFC, ICICI, SBI, Axis, Kotak, IDFC FIRST, and other major banks.

---

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  Phone receives SMS                                 │
│     ↓  MacroDroid forwards via HTTP POST            │
│  Railway webhook server (24/7)                      │
│     ↓  Regex + Claude Haiku extracts fields         │
│  Supabase stores transaction                        │
│     ↓  Every day at 10 AM IST                       │
│  Rich HTML email: Daily Spend Summary               │
└─────────────────────────────────────────────────────┘
```

**Daily email includes:**
- Total spend + transaction count
- Snapshot cards: largest spend, UPI total, unidentified transactions
- Per-transaction rows with badge (UPI / ATM / CRD / NET), merchant, raw SMS, amount
- Payment instrument breakdown (UPI / Card / Other chips)
- This Week bar chart with rounded spend labels above each bar
- Credit alert box for large incoming credits
- One-line AI summary of the day

---

## Features

- **Live SMS capture** — MacroDroid forwards every banking SMS to Railway over the internet; no shared Wi-Fi needed
- **Smart parsing** — Regex extracts bank, amount, merchant, account, payment mode; Claude Haiku fills gaps for unknown formats
- **LLM merchant recovery** — When a stored transaction has no merchant, Claude Haiku reads the raw SMS to find the payee before falling back to the bank name
- **Skip non-transactions** — Future deductions (`will be deducted`), balance alerts, E-Mandate notifications, and clearing entries are automatically ignored
- **Rich HTML email** — Styled daily summary with per-transaction detail and weekly spend bar chart, sent at 10 AM IST every day
- **Reliable scheduler** — Daily email runs as an asyncio task inside uvicorn's event loop (no daemon thread issues on Railway)
- **Dual email delivery** — Resend API (primary, works on Railway) with Gmail SMTP as local fallback
- **On-demand email** — Trigger a summary for any date via CLI or HTTP endpoint
- **Natural language Q&A** — Ask questions like *"How much did I spend on UPI this week?"* via local CLI
- **Template learning** — Unknown SMS formats are saved to Supabase; `learn_patterns.py` uses Claude Opus to suggest new regex patterns
- **Supabase storage** — Full transaction history with IST timestamps
- **Auto storage cleanup** — Deletes oldest records when Supabase free tier hits 80% capacity, retaining last 30 days
- **Multi-bank support** — HDFC, ICICI (credit & debit cards), SBI, Axis, Kotak, IDFC FIRST, Yes Bank, IndusInd, Paytm, PhonePe, Amazon Pay

---

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- A [Supabase](https://supabase.com/) account (free tier)
- A [Railway](https://railway.app/) account (Hobby plan, ~$5/month)
- An Android phone with [MacroDroid](https://play.google.com/store/apps/details?id=com.arlosoft.macrodroid) installed
- A [Resend](https://resend.com/) account and API key for cloud email delivery (free tier available)
- Optionally: a Gmail account with an [App Password](https://myaccount.google.com/apppasswords) for local testing

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ayush3224/sms-parser.git
cd sms-parser
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # Mac/Linux
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=your_anthropic_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
EMAIL_RECEIVER=you@gmail.com

# Cloud email (Railway) — sign up at resend.com
RESEND_API_KEY=re_xxxxxxxxxxxx

# Local email fallback (optional, for local testing only)
EMAIL_SENDER=you@gmail.com
EMAIL_PASSWORD=your_16_char_app_password

WEBHOOK_SECRET=any_random_string   # optional but recommended
```

> **Resend setup:**
> 1. Sign up at [resend.com](https://resend.com/) — free tier allows 100 emails/day
> 2. Create an API key under API Keys
> 3. On the free tier you can send from `onboarding@resend.dev` without domain verification
> 4. To send from your own domain, verify it under Domains

> **Gmail App Password (local fallback):**
> 1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
> 2. Enable 2-Step Verification if not already on
> 3. Create an App Password for "Mail"
> 4. Copy the 16-character password into `EMAIL_PASSWORD`

### 4. Set up Supabase schema

In the [Supabase SQL Editor](https://supabase.com/dashboard), run the contents of `supabase/schema.sql`.
This creates three tables: `sms_messages`, `transactions`, and `unknown_templates`.

### 5. Configure MacroDroid on your Android phone

Create a macro with:
- **Trigger:** SMS Received (all senders, or filter to bank shortcodes)
- **Action:** HTTP POST to `https://your-railway-url.up.railway.app/webhook/sms`
- **Headers:** `Content-Type: application/json`
- **Body (JSON):**
  ```json
  {
    "phone number": "[trigger_number]",
    "message": "[trigger_message]",
    "received at": "[triggertime_seconds]"
  }
  ```

> The webhook accepts MacroDroid's default key format (`"phone number"` / `"received at"`) and the SMS Gateway for Android camelCase format (`"phoneNumber"` / `"receivedAt"`).

### 6. Deploy to Railway

1. Push this repo to GitHub
2. Create a new Railway project → Deploy from GitHub repo
3. Add environment variables in Railway → Variables (same as `.env`)
4. Generate a public domain under Railway → Settings → Networking
5. Use that domain as the MacroDroid webhook URL

---

## Usage

### Test the HTML email locally

```bash
python test_email_template.py
```

Opens `email_preview.html` in the project folder — open it in a browser to inspect the email layout.

### Trigger a summary email on demand (CLI)

```bash
python trigger_summary.py                  # yesterday's summary
python trigger_summary.py 2026-04-05       # specific date
```

### Trigger a summary email via HTTP (Railway)

```bash
# Trigger for yesterday
curl -X POST https://your-railway-url.up.railway.app/trigger-summary \
     -H "X-Secret: your_webhook_secret"

# Trigger for a specific date
curl -X POST "https://your-railway-url.up.railway.app/trigger-summary?date=2026-04-12" \
     -H "X-Secret: your_webhook_secret"
```

### Check server health

```bash
curl https://your-railway-url.up.railway.app/health
```

### Local interactive CLI

```bash
python cli.py
```

Example queries:
```
You: What did I spend yesterday?
You: Show me all UPI transactions this week
You: Which merchant did I spend the most on in April?
```

### Review and improve SMS parsing patterns

```bash
python learn_patterns.py                          # review all unrecognised SMS templates
python learn_patterns.py --sms "Your A/c XX5865 debited..."   # analyse a single SMS
```

Claude Opus reads the stored unknown SMS formats and suggests exact regex additions for `sms_parser.py`.

### One-shot local summary (no email)

```bash
python cli.py --summary
python cli.py --summary --date 2026-04-04
```

### Bulk import from Android SMS backup

```bash
python cli.py --import-file backup.xml
```

---

## SMS Formats Supported

| Bank | Format detected |
|---|---|
| HDFC | UPI debit/credit, card spend, UPI Mandate |
| ICICI | Credit card (`VM-ICICIT-S`, `VM-ICICIB`), debit card, UPI |
| IDFC FIRST | UPI debit (`IDFCBK`, `IDFCFB`) |
| SBI, Axis, Kotak, Yes, IndusInd | Standard debit/credit alerts |
| Any bank | Claude Haiku fallback for unknown formats |

**Automatically skipped (not stored as transactions):**
- `E-Mandate! Rs.X will be deducted on DD-MM-YY` — future deduction notifications
- Balance alerts (`low balance`, `available balance`, `account balance`, etc.)
- Clearing / internal ledger entries containing `(clearing)`

---

## Email Template

The daily summary email is a table-based HTML email compatible with Gmail, Outlook, and Apple Mail. It contains:

| Section | Description |
|---|---|
| Header | Dark background with date and day of week |
| Total | Large rupee amount with transaction count |
| Snapshot | Three cards: largest spend, UPI total, unidentified amount |
| Transactions | One row per debit — badge, merchant, sub-line, raw SMS, amount |
| By Payment Instrument | UPI / Card / Other chips with amounts and percentages |
| This Week | 7-day bar chart (Mon–Sun) with rounded spend labels (e.g. `1.2k`) |
| Credit Alert | Amber box for large incoming credits flagged during the day |
| One-line summary | AI-generated sentence summarising the day's spend |
| Footer | Receiver email and date |

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI / LLM | Claude Opus 4.6 (Q&A + pattern learning), Claude Haiku 4.5 (SMS parsing + merchant recovery + one-line summary) |
| Backend | Python 3.11, FastAPI, Uvicorn |
| Scheduler | asyncio task inside FastAPI lifespan (fires daily at 10 AM IST) |
| Database | Supabase (PostgreSQL) |
| Cloud hosting | Railway |
| SMS forwarding | MacroDroid (Android) |
| Email (cloud) | Resend API |
| Email (local fallback) | Gmail SMTP |
| CLI | Rich |

---

## Project Structure

```
sms-parser/
├── server.py              # Production entry point (Railway)
├── cli.py                 # Local interactive CLI
├── main.py                # Thin redirect to server.py (Railway auto-detects this)
├── trigger_summary.py     # Send HTML summary email on demand
├── learn_patterns.py      # Review unknown SMS, get Claude regex suggestions
├── test_email_template.py # Offline test + browser preview of HTML email
├── requirements.txt
├── railpack.json          # Railway build config
├── railpack.toml          # Railway start command
├── .env.example           # Environment variable template
├── docs/
│   ├── PRD.md             # Product Requirements Document
│   └── ERD.md             # Engineering Requirements Document
├── supabase/
│   └── schema.sql         # Tables: sms_messages, transactions, unknown_templates
└── src/sms_parser/
    ├── agent.py           # Claude Opus 4.6 Q&A agent + one-line summary
    ├── email_template.py  # HTML email builder, bar chart renderer, HTML renderer
    ├── models.py          # SMSMessage & Transaction dataclasses
    ├── sms_parser.py      # Regex + Claude Haiku fallback SMS parser
    ├── sms_reader.py      # Load SMS from JSON / Android XML backup
    ├── supabase_store.py  # Supabase read/write, cleanup, unknown_templates
    ├── webhook_server.py  # FastAPI webhook + asyncio daily scheduler
    └── scheduler.py       # Legacy CLI scheduler (local only)
```

---

## Contributing

Contributions are welcome. To get started:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes with clear commit messages
4. Push and open a Pull Request

---

## License

MIT License — free to use, modify, and distribute with attribution.

---

*Built with Claude Opus 4.6 by Anthropic.*
