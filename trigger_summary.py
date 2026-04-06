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
from src.sms_parser.sms_parser     import SMSParser
from src.sms_parser.supabase_store import SupabaseStore

IST = pytz.timezone("Asia/Kolkata")

# Parse target date
if len(sys.argv) > 1:
    try:
        target = date.fromisoformat(sys.argv[1])
    except ValueError:
        sys.exit(f"Bad date format: {sys.argv[1]} — use YYYY-MM-DD")
else:
    target = (datetime.now(tz=IST) - timedelta(days=1)).date()

print(f"Generating summary for {target} …")

store        = SupabaseStore(sb_url, sb_key)
sms_messages = store.load_all_sms()
transactions = store.load_all_transactions()
agent        = SMSSpendAgent(sms_messages, transactions, api_key)
summary      = agent.get_daily_spend_summary(target)

print("\n" + "="*50)
print(summary)
print("="*50 + "\n")

# Send email
from server import _send_email_summary
_send_email_summary(summary, target)
print("Done. Check your inbox.")
