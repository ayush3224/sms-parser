# Engineering Requirements Document — SMS Spend Agent

**Version:** 1.0  
**Date:** April 2026  
**Status:** Live

---

## 1. System Architecture

```
Android Phone (MacroDroid)
        |
        | HTTP POST /webhook/sms
        v
Railway (FastAPI + Uvicorn)
        |
        |-- SMSParser (regex + Claude Haiku)
        |-- SupabaseStore (read / write)
        |-- SMSSpendAgent (Claude Opus Q&A)
        |
        |-- asyncio task: daily 10 AM IST
        |       |-- build_email_data (email_template.py)
        |       |-- get_one_line_summary (agent.py)
        |       |-- send via Resend API
        |
        v
Supabase (PostgreSQL)
        sms_messages | transactions | unknown_templates
```

---

## 2. Components

### 2.1 `server.py` — Production Entry Point

- Validates required env vars at startup (`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`)
- Initialises `SupabaseStore`, `SMSParser`, `SMSSpendAgent`
- Defines `on_sms(sms)` callback: parse → store → ingest into agent
- Defines `on_summary(for_date)` callback: build email data → get one-line summary → send email
- Defines `on_storage_check()` callback: trigger Supabase cleanup if needed
- Registers all callbacks with `create_app()` and starts uvicorn

**Email delivery (`_send_email_summary`):**
1. Try Resend API if `RESEND_API_KEY` is set — from address is always `onboarding@resend.dev`
2. Fall back to Gmail SMTP (`EMAIL_SENDER` + `EMAIL_PASSWORD`) if Resend is not configured or fails

### 2.2 `src/sms_parser/webhook_server.py` — FastAPI App

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Returns server status, UTC time, IST time |
| POST | `/webhook/sms` | Receive forwarded SMS from Android |
| POST | `/trigger-summary` | Manually fire the daily summary email |

**SMS payload normalisation:**

| Format | Key names | Source |
|---|---|---|
| MacroDroid | `"phone number"`, `"message"`, `"received at"` | Android macro |
| SMS Gateway for Android | `"phoneNumber"`, `"message"`, `"receivedAt"` | Android app |
| Generic | `"sender"`, `"body"`, `"timestamp"` | Any HTTP client |

SMS are deduplicated by MD5 hash of `sender|body|timestamp` prefixed with `wh-`.

**Scheduler (asyncio — no daemon threads):**

Two asyncio tasks created in FastAPI's `@asynccontextmanager` lifespan:

- `_daily_summary_loop`: Calculates seconds until next 10:00 AM IST, sleeps, then runs `on_summary(yesterday)` in a thread-pool executor. Repeats every 24 hours. Re-calculates on every restart so Railway restarts never permanently miss the schedule.
- `_storage_check_loop`: Sleeps 6 hours, then runs `on_storage_check()` in a thread-pool executor. Repeats indefinitely.

Both tasks are cancelled cleanly on app shutdown.

### 2.3 `src/sms_parser/sms_parser.py` — Transaction Parser

**Parse pipeline for each incoming SMS:**

1. Check `_should_skip(body)` — if any skip pattern matches, return `None`
2. Determine bank from sender shortcode
3. Try each regex pattern group in order: UPI, ATM, NEFT/IMPS/RTGS, credit card, debit card
4. Extract: amount, transaction type, merchant, account last 4, payment mode, reference
5. If no pattern matches: call Claude Haiku with the SMS body as a single-shot extraction prompt
6. Return `Transaction` dataclass or `None`

**Skip patterns (return `None` without storing):**

```
will be (deducted|charged|debited|processed)   — future deductions
scheduled (for|on)                             — scheduled payments
falling due                                    — PNB loan instalment notices
One-Time Password                              — ICICI OTP
OTP is \d+                                     — HDFC OTP
Available Bal                                  — HDFC balance-only alerts
balance (is|alert|update|intimation)           — balance notifications
available balance  (not followed by Rs/digits) — generic balance alerts
                                               — note: post-txn "Available balance Rs. X"
                                               — in IDFC confirmations is NOT skipped
account balance / current balance / low balance
Get Rs. X off                                  — promotional discount SMS
Tnc Apply                                      — promotional T&C SMS
Investment value in Tier                       — NPS portfolio statements
traded value for                               — NSE trade notifications
activated Standing Instruction                 — mandate activations
(clearing)                                     — internal ledger entries
```

**Supported banks (sender shortcode mapping):**

- HDFC: `*-HDFCBK-*`, `*-HDFCBANK-*`, `*-HDFC-*`
- ICICI: `*-ICICIB-*`, `*-ICICIBANK-*`, `*-ICICIC-*`, `*-ICICIT-*`
- IDFC FIRST: `*-IDFCBK-*`, `*-IDFCFB-*`
- SBI: `*-SBIBK-*`, `*-SBIINB-*`, `*-STATEBK-*`
- Axis, Kotak, Yes Bank, IndusInd, PNB, Paytm, PhonePe, Amazon Pay
- SBM: `*-SBMIND-*`, `*-SBMBANK-*` — SBM Niyo Global credit card
- Zomato: `*-ZOMATO-*` — Zomato Money wallet credits
- INDmoney: `*-INDDEM-*`, `*-INDMONEY-*` — investment platform payouts
- ITD: `*-ITDCPC-*` — Income Tax Department challan confirmations

**Payment mode detection:**

| Mode | Trigger |
|---|---|
| UPI | `UPI` keyword or `Mandate` |
| NEFT | `NEFT` keyword or `FT-` prefix (HDFC fund-transfer reference) |
| IMPS | `IMPS` keyword or `RRN` (IDFC transaction confirmations) |
| RTGS | `RTGS` keyword |
| Credit Card | `credit card`, `using ... bank card`, or `Bank Card` |
| Debit Card | `debit card` |
| ATM | `ATM` |
| Net Banking | `net banking` / `netbanking` |

### 2.4 `src/sms_parser/email_template.py` — Email Builder + Renderer

**Data classes:**

```python
@dataclass
class BarDay:
    label:          str    # day abbreviation or empty string
    amount:         float  # total debit for that day
    is_highlighted: bool   # True for the summary date
    date_str:       str    # "06 Apr" — used in tooltip

@dataclass
class EmailRow:
    merchant:      str
    amount:        float
    txn_type:      str
    payment_mode:  str
    bank:          str
    account_last4: str
    time_str:      str
    raw_sms:       str
    badge:         str    # "UPI" / "ATM" / "CRD" / "NET" / "OTH"

@dataclass
class EmailData:
    date_str, date_short, day_of_week: str
    total_debit:          float
    txn_count:            int
    largest_spend:        float
    largest_merchant:     str
    upi_total:            float
    upi_pct:              int
    unknown_count:        int
    unknown_amount:       float
    transactions:         List[EmailRow]
    upi_instrument:       float
    card_instrument:      float
    other_instrument:     float
    upi_instrument_pct:   int
    card_instrument_pct:  int
    other_instrument_pct: int
    credit_alerts:        List[dict]   # {"amount", "merchant", "raw_sms"}
    one_line_summary:     str
    receiver_email:       str
    monthly_bars:         List[BarDay]  # retained on EmailData, not rendered
    weekly_bars:          List[BarDay]  # rendered in This Week section
```

**Merchant resolution (3-step, at email build time):**

1. Use `transaction.merchant` if already set in DB
2. Re-parse the raw SMS with current regex patterns (catches old transactions pre-dating newer patterns)
3. Call Claude Haiku: single-shot prompt, return payee name or `None`
4. Fall back to bank name (e.g. "HDFC", "ICICI")

**`_strftime_no_pad(dt, fmt)`:**  
Replaces `%-` with `%#` on Windows to avoid `Invalid format string` errors with `%-d` / `%-I`.

**`_extract_sms_text(raw)`:**  
If `raw_sms` starts with `{`, attempts to JSON-parse and return only the `"message"` field. Handles MacroDroid payloads stored before webhook-side normalisation was added.

**`_render_bar_chart(bars, max_h=56, show_values=False)`:**  
Pure HTML table, no JavaScript, no external assets — compatible with all major email clients.

- Bars are bottom-aligned using a spacer `<div>` above each bar
- Bar height scaled proportionally to `max_h` pixels relative to maximum amount in the set
- Zero/future days shown as a 2px light grey stub
- When `show_values=True`, compact amount labels (e.g. `1.2k`, `800`) are rendered above each bar in the spacer div using flexbox bottom-alignment

**`_fmt_k(amount)`:**  
Compact formatter: `1200 → "1.2k"`, `3000 → "3k"`, `800 → "800"`.

**`render_html_email(data)`:**  
Generates a single self-contained HTML string. All CSS is inline. No external stylesheets, fonts, or images. HTML entities used for all currency symbols (`&#8377;` for ₹). File written with UTF-8 BOM (`utf-8-sig`) in tests to ensure correct browser detection on Windows.

### 2.5 `src/sms_parser/agent.py` — Claude Opus Q&A Agent

- Maintains conversation history in memory
- On `ingest_sms`: appends new transaction context to the agent's working set
- `chat(message)`: sends user question + full transaction context to Claude Opus 4.6
- `get_daily_spend_summary()`: generates a structured text summary (local CLI use)
- `get_one_line_summary(email_data)`: calls Claude Haiku with spend statistics; returns a sentence of ≤18 words describing the day

### 2.6 `src/sms_parser/supabase_store.py` — Database Layer

**Tables:**

| Table | Key columns |
|---|---|
| `sms_messages` | `id`, `sender`, `body`, `timestamp` |
| `transactions` | `id`, `sms_id`, `amount`, `transaction_type`, `merchant`, `bank`, `account_last4`, `payment_mode`, `timestamp` |
| `unknown_templates` | `id`, `sender`, `body`, `created_at` |

**Methods:**

- `save(sms, txn)` — upsert SMS + transaction (if parsed)
- `load_all_sms()` / `load_all_transactions()` — bulk load on startup
- `save_unknown_template(sms)` — store unrecognised SMS for later review
- `load_unknown_templates()` / `mark_template_applied(id)` — used by `learn_patterns.py`
- `cleanup_if_needed()` — checks row count; if >80% of estimated free-tier limit, deletes oldest rows retaining at least 30 days

---

## 3. Data Flow

### Incoming SMS

```
MacroDroid POST /webhook/sms
  → _parse_ts(): normalise timestamp to IST-aware datetime
  → deduplicate by hash ID
  → SMSMessage(id, sender, body, timestamp)
  → on_sms(sms):
      SMSParser.parse(sms)
        → _should_skip() → None if matched
        → regex extraction
        → Claude Haiku fallback if no regex match
        → Transaction or None
      SupabaseStore.save(sms, txn)
      SMSSpendAgent.ingest_sms(sms, txn)
```

### Daily Email

```
10:00 AM IST asyncio task fires
  → on_summary(yesterday):
      SupabaseStore.load_all_transactions() → fresh list
      build_email_data(transactions, for_date, receiver_email, api_key):
        → filter to for_date debits/credits
        → 3-step merchant resolution for each debit
        → compute totals, percentages, bar chart data
        → return EmailData
      SMSSpendAgent.get_one_line_summary(email_data) → str
      _send_email_summary(email_data, for_date):
        → render_html_email(email_data) → HTML string
        → Resend API (if RESEND_API_KEY set)
        → Gmail SMTP fallback
```

---

## 4. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude models |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase anon/service key |
| `EMAIL_RECEIVER` | Yes | Email address to send daily summary to |
| `RESEND_API_KEY` | Recommended | Resend API key (required on Railway) |
| `EMAIL_SENDER` | Optional | Gmail address for SMTP fallback |
| `EMAIL_PASSWORD` | Optional | Gmail App Password for SMTP fallback |
| `WEBHOOK_SECRET` | Optional | If set, all webhook requests must include `X-Secret: <value>` |
| `PORT` | Auto (Railway) | HTTP port; Railway injects this automatically |

---

## 5. API Endpoints

### `GET /health`

Returns server status. No authentication required.

```json
{
  "status": "ok",
  "utc_now": "2026-04-13T04:30:00Z",
  "ist_now": "2026-04-13 10:00:00 IST"
}
```

### `POST /webhook/sms`

Receives a forwarded SMS. Requires `X-Secret` header if `WEBHOOK_SECRET` is set.

Request body (MacroDroid format):
```json
{
  "phone number": "AD-HDFCBK",
  "message": "Your A/c XX1234 debited Rs.500 on 12-04-26 UPI/Amazon",
  "received at": 1744522200000
}
```

Response:
```json
{ "status": "ok", "id": "wh-a1b2c3d4e5f6g7h8" }
```

Error responses: `400` if body is empty, `401` if secret is wrong.

### `POST /trigger-summary`

Triggers the daily summary email immediately. Requires `X-Secret` header if `WEBHOOK_SECRET` is set.

Query parameter: `?date=YYYY-MM-DD` (optional, defaults to yesterday).

Response:
```json
{ "status": "triggered", "date": "2026-04-12" }
```

---

## 6. Scheduler Design

Previous implementation used APScheduler's `BackgroundScheduler` with a daemon thread. This was unreliable on Railway because:
- Uvicorn's signal handling interfered with background threads
- Railway container restarts killed daemon threads silently
- No guarantee of execution after a restart near the scheduled time

Current implementation uses an `asyncio.create_task` inside FastAPI's `@asynccontextmanager` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = []
    if on_summary:
        tasks.append(asyncio.create_task(_daily_summary_loop(on_summary)))
    if on_storage_check:
        tasks.append(asyncio.create_task(_storage_check_loop(on_storage_check)))
    yield
    for t in tasks:
        t.cancel()
```

`_daily_summary_loop` recalculates the next 10 AM IST on every iteration, so a restart at 9:59 AM still fires one minute later. Blocking I/O (Supabase queries, Claude API calls) runs in a thread-pool via `loop.run_in_executor(None, ...)` to avoid blocking uvicorn's event loop.

---

## 7. HTML Email Compatibility

Email clients do not support external CSS, JavaScript, or many modern CSS properties. The template follows these constraints:

- All CSS is inline on each element
- Layout uses `<table>` for structural columns (snapshot cards, bar chart cells)
- No `<div>` flexbox for primary layout (only used inside bar chart cells where email-client support is acceptable for hover tooltips)
- All special characters use HTML entities: `&#8377;` (₹), `&#8722;` (−), `&middot;` (·), `&mdash;` (—)
- No raw non-ASCII characters except in user-supplied text (merchant names, one-line summary) which are HTML-escaped
- HTML comments use only ASCII characters (box-drawing characters removed)
- File written with UTF-8 BOM for reliable browser encoding detection on Windows

---

## 8. Dependencies

```
anthropic>=0.50.0       # Claude API client
python-dotenv>=1.0.0    # .env file loading
apscheduler>=3.10.0     # Legacy local CLI scheduler
rich>=13.7.0            # CLI formatting
pytz>=2024.1            # IST timezone handling
resend>=2.0.0           # Resend email API
supabase>=2.4.0         # Supabase Python client
fastapi>=0.110.0        # Webhook server framework
uvicorn[standard]>=0.27.0  # ASGI server
```

---

## 9. Local Development

### Run the email preview test

```bash
python test_email_template.py
# Opens email_preview.html in the project folder
```

### Run the webhook server locally

```bash
python server.py
# Starts on port 8000 (or $PORT)
# Webhook: http://localhost:8000/webhook/sms
# Health:  http://localhost:8000/health
```

### Trigger a summary from the CLI

```bash
python trigger_summary.py              # yesterday
python trigger_summary.py 2026-04-12  # specific date
```

### Improve SMS parsing patterns

```bash
python learn_patterns.py
```

---

## 10. Deployment (Railway)

1. Connect GitHub repo to Railway project
2. Set all required environment variables under Railway → Variables
3. Railway auto-detects `main.py` or uses `railpack.toml` start command: `python server.py`
4. Generate a public domain under Railway → Settings → Networking
5. Point MacroDroid HTTP POST action to `https://<domain>/webhook/sms`
6. Add `X-Secret: <value>` header in MacroDroid if `WEBHOOK_SECRET` is set

Railway restarts the container on each deploy. The asyncio scheduler recalculates the next 10 AM IST on every startup, so no scheduled emails are missed due to restarts.
