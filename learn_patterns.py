#!/usr/bin/env python3
"""
Review unknown SMS templates and generate regex patterns to add to sms_parser.py.

Usage:
    python learn_patterns.py            # review all unapplied templates from Supabase
    python learn_patterns.py --all      # include already-applied templates too
    python learn_patterns.py --sms "Your A/c XX5865 debited..."  # analyse a single SMS

After reviewing the suggestions, add the patterns to src/sms_parser/sms_parser.py,
then mark the template as applied by pressing 'y' when prompted.
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

for var in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
    if not os.getenv(var):
        sys.exit(f"ERROR: {var} is not set in .env")

import anthropic
from src.sms_parser.supabase_store import SupabaseStore

ANALYSIS_PROMPT = """\
You are helping improve a regex-based Indian banking SMS parser.

Current regex patterns in the parser:

BANK ALIASES (from _BANK_SENDERS):
  HDFC: HDFCBK, HDFCBANK, HDFC
  ICICI: ICICIB, ICICIBANK, ICICI
  SBI: SBIBK, SBIINB, SBI, STATEBK
  Axis: AXISBK, AXISBANK, AXIS
  Kotak: KOTAKB, KOTAK
  Yes Bank: YESBK, YESBANK
  IndusInd: INDUSBK, INDUSIND
  IDFC: IDFCBK, IDFCFB, IDFC FIRST, IDFCFIRST
  Paytm: PAYTM, PYTM
  PhonePe: PHONPE, PHONEPE
  Amazon Pay: AMAZONPAY, AMZNPAY

MERCHANT PATTERNS (from _MERCHANT_PATTERNS):
  r'(?:at|to)\\s+([A-Z][A-Za-z0-9\\s&\\-\\.\\']{2,40}?)...'
  r'paid\\s+to\\s+([A-Za-z][A-Za-z0-9\\s&\\-\\.\\']{2,40}?)...'
  r'VPA\\s*[:\\-]?\\s*([^\\s@]+@[^\\s]+)'
  r'([A-Z][A-Za-z\\s]{2,30}?)\\s+credited\\b'

ACCOUNT PATTERNS (from _ACCOUNT_PATTERNS):
  r'(?:a/c|acct?|account|card)\\s*...'
  r'\\bXX([0-9]{4})\\b'
  r'\\bA/c\\s+XX([0-9]{4})\\b'
  r'\\*+([0-9]{4})\\b'

---

The following SMS templates were received but the regex could NOT extract all fields.
Missing fields are noted for each.

{templates}

---

For each template:
1. Identify WHY the regex missed the field (what pattern would match it)
2. Suggest the exact Python regex string to add
3. Specify WHICH list it should be added to (_BANK_SENDERS, _MERCHANT_PATTERNS, or _ACCOUNT_PATTERNS)
4. Show a test match: re.search(pattern, sms_body)

Format your response clearly per template, then give a SUMMARY section with copy-paste ready code additions."""


def analyse_templates(templates: list, api_key: str) -> str:
    formatted = []
    for i, t in enumerate(templates, 1):
        missing = t.get("missing_fields") or []
        formatted.append(
            f"[{i}] Missing: {', '.join(missing)}\n"
            f"    Sender: {t.get('sender', 'unknown')}\n"
            f"    SMS body: {t['body']}\n"
            f"    Extracted bank: {t.get('bank') or 'None'}\n"
            f"    Extracted merchant: {t.get('merchant') or 'None'}"
        )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": ANALYSIS_PROMPT.format(templates="\n\n".join(formatted)),
        }],
    )
    return response.content[0].text


def main():
    ap = argparse.ArgumentParser(description="Learn regex patterns from unknown SMS templates")
    ap.add_argument("--all", action="store_true", help="Include already-applied templates")
    ap.add_argument("--sms", metavar="TEXT", help="Analyse a single SMS body directly")
    args = ap.parse_args()

    api_key = os.environ["ANTHROPIC_API_KEY"]

    if args.sms:
        # Analyse a single SMS provided on the command line
        templates = [{"body": args.sms, "sender": "unknown", "missing_fields": ["bank", "merchant"]}]
    else:
        store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        templates = store.load_unknown_templates(unapplied_only=not args.all)

        if not templates:
            print("No unknown templates found. All SMS are being parsed by regex already.")
            return

        print(f"Found {len(templates)} template(s) to review.\n")

    print("Analysing with Claude Opus 4.6 …\n")
    suggestion = analyse_templates(templates, api_key)

    print("=" * 60)
    print(suggestion)
    print("=" * 60)

    # Offer to mark templates as applied
    if not args.sms and templates:
        answer = input("\nMark all these templates as applied? (y/N): ").strip().lower()
        if answer == "y":
            store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
            for t in templates:
                if t.get("id"):
                    store.mark_template_applied(t["id"])
            print(f"Marked {len(templates)} template(s) as applied.")


if __name__ == "__main__":
    main()
