#!/usr/bin/env python3
"""
Trigger the daily spend summary email on demand.

Usage:
    python trigger_summary.py              # yesterday's summary
    python trigger_summary.py 2026-04-05   # specific date
"""

import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

for var in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
    if not os.getenv(var):
        sys.exit(f"ERROR: {var} is not set in .env")

api_key = os.environ["ANTHROPIC_API_KEY"]
sb_url  = os.environ["SUPABASE_URL"]
sb_key  = os.environ["SUPABASE_KEY"]

import pytz
from src.sms_parser.agent          import SMSSpendAgent
from src.sms_parser.email_template import build_email_data
from src.sms_parser.supabase_store import SupabaseStore

IST = pytz.timezone("Asia/Kolkata")

# ── Parse target date ──────────────────────────────────────────────────────
if len(sys.argv) > 1:
    try:
        target = date.fromisoformat(sys.argv[1])
    except ValueError:
        sys.exit(f"Bad date format: {sys.argv[1]} — use YYYY-MM-DD")
else:
    target = (datetime.now(tz=IST) - timedelta(days=1)).date()

print(f"Generating summary for {target} …")

# ── Load data ──────────────────────────────────────────────────────────────
store        = SupabaseStore(sb_url, sb_key)
transactions = store.load_all_transactions()
agent        = SMSSpendAgent([], transactions, api_key)

# ── Build structured email data ────────────────────────────────────────────
receiver   = os.getenv("EMAIL_RECEIVER", "")
email_data = build_email_data(transactions, target, receiver_email=receiver, api_key=api_key)

if email_data.txn_count == 0:
    print(f"No debit transactions found for {target}.")
else:
    print(f"  ₹{email_data.total_debit:,.0f} across {email_data.txn_count} transactions")
    print(f"  Largest: ₹{email_data.largest_spend:,.0f} at {email_data.largest_merchant}")

# ── One-line summary from Claude Haiku ────────────────────────────────────
email_data.one_line_summary = agent.get_one_line_summary(email_data)
if email_data.one_line_summary:
    print(f"  → {email_data.one_line_summary}")

# ── Send HTML email ────────────────────────────────────────────────────────
from server import _send_email_summary
_send_email_summary(email_data, target)
print("Done. Check your inbox.")
