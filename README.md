# SMS Spend Agent

An AI-powered agent that reads your Indian banking SMS in real time, stores transactions in the cloud, and delivers a daily spend summary to your inbox — all without keeping your laptop on.

Built for Indian users with HDFC, ICICI, SBI, Axis, Kotak, IDFC FIRST, and other major banks.

---

## Visuals

```
┌─────────────────────────────────────────────────────┐
│  📱 Phone receives SMS                              │
│     ↓  MacroDroid forwards via HTTP POST            │
│  ☁️  Railway webhook server (24/7)                  │
│     ↓  Parses amount, merchant, bank, type          │
│  🗄️  Supabase stores transaction                    │
│     ↓  Every day at 10 AM IST                       │
│  📧 Email: Daily Spend Summary                      │
└─────────────────────────────────────────────────────┘
```

**Daily email summary example:**
```
Subject: Daily Spend Summary — 2026-04-05

Total Spent:    ₹1,250.00  (4 transactions)
Total Received: ₹500.00    (1 credit)

Breakdown:
• Swati Jha       ₹10.00    IDFC FIRST  UPI
• Swiggy          ₹340.00   HDFC        UPI
• Amazon          ₹750.00   HDFC        UPI
• ATM Withdrawal  ₹150.00   HDFC

Net spend: ₹750.00
```

---

## Features

- **Live SMS capture** — MacroDroid forwards every banking SMS to the cloud instantly
- **AI-powered parsing** — Regex + Claude Haiku fallback extracts bank, amount, merchant, account, payment mode from any Indian bank SMS format
- **Cloud deployment** — Runs 24/7 on Railway; laptop and hotspot not required
- **Daily email summary** — Sent every day at 10:00 AM IST via Gmail SMTP
- **Natural language Q&A** — Ask questions like *"How much did I spend on UPI this week?"* via local CLI
- **Supabase storage** — Full transaction history with timestamps in IST
- **Auto storage cleanup** — Deletes oldest records when Supabase free tier hits 80% capacity, always retaining last 30 days
- **Multi-bank support** — HDFC, ICICI, SBI, Axis, Kotak, IDFC FIRST, Yes Bank, IndusInd, Paytm, PhonePe, Amazon Pay

---

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- A [Supabase](https://supabase.com/) account (free tier)
- A [Railway](https://railway.app/) account (Hobby plan, ~$5/month)
- An Android phone with [MacroDroid](https://play.google.com/store/apps/details?id=com.arlosoft.macrodroid) installed
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) for email summaries

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

Edit `.env` and fill in your keys:

```env
ANTHROPIC_API_KEY=your_anthropic_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
EMAIL_SENDER=you@gmail.com
EMAIL_PASSWORD=your_16_char_app_password
EMAIL_RECEIVER=you@gmail.com
WEBHOOK_SECRET=any_random_string   # optional
```

> **Getting a Gmail App Password:**
> 1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
> 2. Enable 2-Step Verification if not already on
> 3. Create an App Password for "Mail"
> 4. Copy the 16-character password into `EMAIL_PASSWORD`

### 4. Set up Supabase schema

In the [Supabase SQL Editor](https://supabase.com/dashboard), run the contents of `supabase/schema.sql`.

### 5. Configure MacroDroid on your Android phone

Create a macro with:
- **Trigger:** Incoming SMS
- **Action:** HTTP POST to `https://your-railway-url.up.railway.app/webhook/sms`
- **Body (JSON):**
  ```json
  {
    "phoneNumber": "[incoming_sms_number]",
    "message": "[incoming_sms_message]",
    "receivedAt": "[triggertime_seconds]"
  }
  ```

---

## Usage

### Local interactive CLI (ask questions about your spending)

```bash
python cli.py
```

Example queries:
```
You: What did I spend yesterday?
You: Show me all UPI transactions this week
You: Which merchant did I spend the most on in April?
You: Did I get any credits this week?
```

### Trigger summary email on demand

```bash
python trigger_summary.py                  # email yesterday's summary now
python trigger_summary.py 2026-04-05       # email summary for a specific date
```

### Review and improve SMS parsing patterns

```bash
python learn_patterns.py                   # review all unrecognised templates
python learn_patterns.py --sms "Your A/c XX5865 debited..."   # analyse one SMS
```

### One-shot daily summary (local, no email)

```bash
python cli.py --summary
python cli.py --summary --date 2026-04-04
```

### Bulk import from Android SMS backup

```bash
python cli.py --import-file backup.xml
```

### Cloud deployment (Railway)

The `server.py` entry point runs automatically on Railway — no interaction needed. It:
- Receives live SMS via webhook
- Sends daily email at 10 AM IST
- Checks Supabase storage every 6 hours

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI / LLM | Claude Opus 4.6 (Q&A), Claude Haiku (SMS parsing) |
| Backend | Python, FastAPI, Uvicorn |
| Database | Supabase (PostgreSQL) |
| Scheduler | APScheduler |
| Cloud hosting | Railway |
| SMS forwarding | MacroDroid (Android) |
| Email | Gmail SMTP (smtplib) |
| CLI | Rich |

---

## Project Structure

```
sms-parser/
├── server.py              # Production entry point (Railway)
├── cli.py                 # Local interactive CLI
├── main.py                # Thin redirect → server.py (Railway auto-detects this)
├── trigger_summary.py     # Send summary email on demand
├── learn_patterns.py      # Review unknown templates, get regex suggestions
├── requirements.txt
├── railpack.json          # Railway build config
├── railpack.toml          # Railway start command
├── .env.example           # Environment variable template
├── data/
│   └── sample_sms.json    # Sample SMS for local testing
├── supabase/
│   └── schema.sql         # Database schema (sms_messages, transactions, unknown_templates)
└── src/sms_parser/
    ├── agent.py           # Claude Opus 4.6 Q&A agent
    ├── models.py          # SMSMessage & Transaction dataclasses
    ├── sms_parser.py      # Regex + Claude Haiku fallback SMS parser
    ├── sms_reader.py      # Load SMS from JSON / Android XML
    ├── supabase_store.py  # Supabase read/write, storage cleanup, unknown templates
    ├── webhook_server.py  # FastAPI webhook endpoint
    └── scheduler.py       # APScheduler jobs (daily summary, storage check)
```

---

## Contributing

Contributions are welcome. To get started:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes with clear commit messages
4. Push to your fork: `git push origin feature/your-feature`
5. Open a Pull Request describing what you changed and why

Please keep changes focused — one feature or fix per PR.

---

## License

This project is licensed under the **MIT License** — free to use, modify, and distribute with attribution.

---

*Built with Claude Opus 4.6 by Anthropic.*
