# Product Requirements Document — SMS Spend Agent

**Version:** 1.0  
**Date:** April 2026  
**Status:** Live

---

## 1. Overview

SMS Spend Agent is a personal finance tool for Indian users that automatically captures every banking transaction from SMS, stores it in the cloud, and delivers a rich daily spend summary by email — without any manual data entry or keeping a laptop running.

---

## 2. Problem Statement

Indian bank accounts generate an SMS for every transaction. These messages pile up in the inbox unread and unstructured. Users who want to understand their spending must:

- Manually scroll through hundreds of messages
- Enter data into a spreadsheet or app by hand
- Use bank apps that only show individual bank data, not a consolidated view

There is no zero-effort, automatic, consolidated view of daily spending across all banks and payment modes.

---

## 3. Target Users

**Primary user:** An individual with one or more Indian bank accounts who:
- Receives debit/credit SMS alerts from their bank
- Uses an Android phone
- Wants a daily email digest of their spending without any manual input
- Is comfortable deploying a simple cloud app once

---

## 4. Goals

| Goal | Metric |
|---|---|
| Zero manual data entry | All transactions captured automatically from SMS |
| Daily visibility | Email delivered by 10 AM IST every day |
| High parse accuracy | >90% of transaction SMS correctly parsed |
| Reliable delivery | Email sent even when the user's phone or laptop is off |
| Low cost | Total infrastructure cost under ₹500/month |

---

## 5. User Stories

### Capture

- As a user, I want every banking SMS I receive to be automatically captured and stored so I don't have to log anything manually.
- As a user, I want the system to work even when my laptop is off, so the capture is truly automatic.
- As a user, I want non-transaction SMS (balance alerts, E-Mandate notifications) to be silently skipped so my transaction history stays clean.

### Daily Summary Email

- As a user, I want to receive a daily email at 10 AM summarising yesterday's spending so I can review it with my morning coffee.
- As a user, I want to see my total spend, each transaction with merchant and amount, and a breakdown by payment mode (UPI / Card / Other).
- As a user, I want to see how this week's daily spending compares as a bar chart so I can spot patterns.
- As a user, I want a one-sentence AI summary of the day so I can understand the day at a glance without reading every row.
- As a user, I want to be alerted if a large credit (e.g. salary) arrived that day, flagged separately from my debits.

### On-Demand

- As a user, I want to trigger a summary email for any past date from my terminal so I can catch up after travelling.
- As a user, I want to trigger the summary via an HTTP endpoint so I can test it without a laptop.

### Q&A

- As a user, I want to ask natural-language questions about my transactions (e.g. "how much did I spend on food last week?") via a local CLI so I can investigate without opening a spreadsheet.

### Parsing & Learning

- As a user, I want unknown SMS formats to be saved so I can review and improve parsing over time.
- As a user, I want Claude to suggest new regex patterns from unrecognised SMS so improving accuracy requires minimal effort.

---

## 6. Features

### 6.1 SMS Capture (Webhook)

- Android phone forwards banking SMS via MacroDroid to a Railway webhook
- Webhook accepts MacroDroid format (`"phone number"` / `"received at"`) and SMS Gateway for Android format (`"phoneNumber"` / `"receivedAt"`)
- Duplicate SMS (same sender + body + timestamp) are deduplicated by hash ID
- Every received SMS is stored in Supabase regardless of whether a transaction is parsed from it

### 6.2 Transaction Parsing

- Regex patterns cover all major Indian banks: HDFC, ICICI (debit + credit card), IDFC FIRST, SBI, Axis, Kotak, Yes, IndusInd
- Extracted fields: amount, transaction type (debit/credit), merchant, bank, account last 4 digits, payment mode (UPI / ATM / NEFT / IMPS / Credit Card / Debit Card)
- Claude Haiku fallback for SMS formats not matched by any regex
- LLM merchant recovery at email render time: for stored transactions missing a merchant, Claude Haiku re-reads the raw SMS to extract the payee before falling back to the bank name
- SMS automatically skipped (not stored as transactions):
  - Future deductions: `will be deducted`, `will be charged`, `scheduled for`
  - Balance alerts: `low balance`, `available balance`, `account balance`, `current balance`
  - Clearing entries: `(clearing)`
  - E-Mandate confirmations

### 6.3 Daily Summary Email

Sent every day at 10 AM IST for the previous day's transactions.

**Email sections:**
1. **Header** — date and day of week on dark background
2. **Total** — large rupee amount + transaction count
3. **Snapshot cards** — largest single spend, total via UPI, unidentified merchant total
4. **Transaction rows** — one per debit, sorted latest first: payment mode badge (UPI / ATM / CRD / NET), merchant name, sub-line (mode · bank · account · time), raw SMS in monospace, amount
5. **By Payment Instrument** — UPI / Card / Other chips with amounts and percentages
6. **This Week** — 7-day bar chart (Mon–Sun) ending on the summary date; bars labelled with compact amounts (e.g. `1.2k`); today highlighted in red
7. **Credit alert** — amber box if any large credit received that day
8. **One-line summary** — AI-generated sentence (≤18 words) via Claude Haiku
9. **Footer** — receiver email and date

### 6.4 On-Demand Trigger

- `python trigger_summary.py [YYYY-MM-DD]` — CLI trigger
- `POST /trigger-summary?date=YYYY-MM-DD` — HTTP trigger (with optional `X-Secret` header)

### 6.5 Email Delivery

- **Primary (Railway):** Resend API — works on all cloud platforms, no SMTP port restrictions
- **Fallback (local):** Gmail SMTP — used automatically when `RESEND_API_KEY` is not set

### 6.6 Storage Management

- Supabase free tier: 500 MB limit
- Every 6 hours, the server checks storage usage
- If usage exceeds 80%, oldest records are deleted, retaining at least the last 30 days of data

### 6.7 Local CLI

- Interactive Claude Opus 4.6 Q&A over all stored transactions
- `--summary` flag for a plain-text daily summary without email
- `--import-file` for bulk loading from an Android SMS XML backup

### 6.8 Pattern Learning

- Unrecognised SMS bodies are saved to the `unknown_templates` table
- `learn_patterns.py` sends batches of unknown SMS to Claude Opus, which suggests exact Python regex additions for `sms_parser.py`

---

## 7. Non-Goals

- iOS support (MacroDroid is Android-only; iOS SMS forwarding is not in scope)
- Multi-user support (single user, single set of credentials)
- A web dashboard or mobile app (email is the only UI)
- Budget setting or financial advice
- Investment or loan tracking (only bank debit/credit transactions)

---

## 8. Success Criteria

- User receives the daily email automatically at 10 AM IST without any manual action
- >90% of real bank SMS are correctly parsed into transactions
- Less than 1 false positive per week (non-transaction SMS stored as transactions)
- Email renders correctly in Gmail, Outlook, and Apple Mail
- Total monthly infrastructure cost is under ₹500

---

## 9. Constraints

- Free Supabase tier: 500 MB database, 2 GB file storage
- Railway Hobby plan: $5/month, shared compute, SMTP ports blocked (resolved via Resend)
- Resend free tier: 100 emails/day, 3,000/month — sufficient for 1 email/day
- Anthropic API: Claude Haiku calls per SMS parsing; Claude Haiku for one-line summary; Claude Opus for Q&A and pattern learning (cost managed by using Haiku for high-frequency calls)
