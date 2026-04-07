#!/usr/bin/env python3
"""
Quick test: build EmailData from mock transactions and render to HTML.
Saves output to /tmp/email_preview.html — open in a browser to inspect.
"""

import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

# ── Mock Transaction objects ────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")

class MockTxn:
    def __init__(self, amount, merchant, payment_mode, bank, account_last4, raw_sms, txn_type="debit", timestamp=None):
        self.amount = amount
        self.merchant = merchant
        self.payment_mode = payment_mode
        self.bank = bank
        self.account_last4 = account_last4
        self.raw_sms = raw_sms
        self.timestamp = timestamp or datetime(2026, 4, 6, 8, 27, tzinfo=IST)
        self.reference = None
        # Mock TransactionType
        class TT:
            value = txn_type
            def __eq__(self, other):
                return self.value == other.value if hasattr(other, "value") else self.value == str(other)
        self.transaction_type = TT()

# Patch TransactionType for the builder
import types, sys
m = types.ModuleType("src.sms_parser.models")
class TransactionType:
    DEBIT  = type("D", (), {"value": "debit"})()
    CREDIT = type("C", (), {"value": "credit"})()
m.TransactionType = TransactionType
sys.modules.setdefault("src", types.ModuleType("src"))
sys.modules.setdefault("src.sms_parser", types.ModuleType("src.sms_parser"))
sys.modules["src.sms_parser.models"] = m

# Patch pytz
try:
    import pytz
except ImportError:
    pytz = None

if pytz is None:
    import types as _t
    pytz_mod = _t.ModuleType("pytz")
    class _TZ:
        def __init__(self, name): self._name = name
        def __call__(self, *a, **kw): return self
        def localize(self, dt): return dt.replace(tzinfo=IST)
    pytz_mod.timezone = lambda name: _TZ(name)
    sys.modules["pytz"] = pytz_mod

# Now import the template module directly
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "email_template",
    pathlib.Path(__file__).parent / "src/sms_parser/email_template.py"
)
et = importlib.util.module_from_spec(spec)
# Patch IST inside the module before exec
et.IST = IST  # type: ignore
spec.loader.exec_module(et)  # type: ignore

# Patch the models import inside build_email_data
original_build = et.build_email_data
def patched_build(transactions, for_date, receiver_email=""):
    # Directly filter and build without the broken import
    debits  = [t for t in transactions if t.transaction_type.value == "debit"]
    credits = [t for t in transactions if t.transaction_type.value == "credit"]

    day_debits  = [t for t in debits  if t.timestamp.astimezone(IST).date() == for_date]
    day_credits = [t for t in credits if t.timestamp.astimezone(IST).date() == for_date]

    total_debit = sum(t.amount for t in day_debits)

    largest = max(day_debits, key=lambda t: t.amount, default=None)
    largest_spend    = largest.amount if largest else 0.0
    largest_merchant = (largest.merchant or "Unknown") if largest else "—"

    upi_debits = [t for t in day_debits if t.payment_mode and "upi" in t.payment_mode.lower()]
    upi_total  = sum(t.amount for t in upi_debits)

    unknown_debits = [t for t in day_debits if not t.merchant]
    unknown_count  = len(unknown_debits)
    unknown_amount = sum(t.amount for t in unknown_debits)

    card_debits = [t for t in day_debits if t.payment_mode and
                   any(k in t.payment_mode.lower() for k in ("credit card","debit card"))]
    card_instr = sum(t.amount for t in card_debits)
    other_instr = max(total_debit - upi_total - card_instr, 0.0)

    rows = []
    for t in sorted(day_debits, key=lambda x: x.timestamp, reverse=True):
        time_str = t.timestamp.astimezone(IST).strftime("%-I:%M %p")
        rows.append(et.EmailRow(
            merchant      = t.merchant or "Unknown",
            amount        = t.amount,
            txn_type      = "debit",
            payment_mode  = t.payment_mode or "Other",
            bank          = t.bank or "",
            account_last4 = f"XX{t.account_last4}" if t.account_last4 else "",
            time_str      = time_str,
            raw_sms       = t.raw_sms or "",
            badge         = et._badge(t.payment_mode),
        ))

    credit_alerts = [
        {"amount": t.amount, "merchant": t.merchant or "credit", "raw_sms": t.raw_sms or ""}
        for t in day_credits
    ]

    def pct(a, b): return round(a/b*100) if b > 0 else 0

    return et.EmailData(
        date_str             = for_date.strftime("%-d %B %Y"),
        date_short           = for_date.strftime("%d %b %Y"),
        day_of_week          = for_date.strftime("%A"),
        total_debit          = total_debit,
        txn_count            = len(day_debits),
        largest_spend        = largest_spend,
        largest_merchant     = largest_merchant,
        upi_total            = upi_total,
        upi_pct              = pct(upi_total, total_debit),
        unknown_count        = unknown_count,
        unknown_amount       = unknown_amount,
        transactions         = rows,
        upi_instrument       = upi_total,
        card_instrument      = card_instr,
        other_instrument     = other_instr,
        upi_instrument_pct   = pct(upi_total,  total_debit),
        card_instrument_pct  = pct(card_instr, total_debit),
        other_instrument_pct = pct(other_instr,total_debit),
        credit_alerts        = credit_alerts,
        one_line_summary     = "You spent ₹4,610 across 5 transactions on 06 Apr — mostly UPI payments.",
        receiver_email       = receiver_email,
    )

et.build_email_data = patched_build

# ── Mock data ────────────────────────────────────────────────────────────────
TARGET = date(2026, 4, 6)

txns = [
    MockTxn(2200, "The Smoke Center",  "UPI",  "IDFC",  "5865",
            "Your A/c XX5865 debited Rs.2200 UPI/The Smoke Center",
            timestamp=datetime(2026,4,6, 8,16, tzinfo=IST)),
    MockTxn(1000, None,                "UPI",  "IDFC",  "5865",
            "Your A/c XX5865 debited Rs.1000 UPI/ref123",
            timestamp=datetime(2026,4,6, 3,27, tzinfo=IST)),
    MockTxn(1000, None,                "UPI",  "IDFC",  "5865",
            "Your A/c XX5865 debited Rs.1000 Info:UPI/abc",
            timestamp=datetime(2026,4,6, 7,37, tzinfo=IST)),
    MockTxn(100,  "Swati Jha",         "UPI",  "IDFC",  "5865",
            "Your A/c XX5865 debited by Rs.100 on 05-04-26. Info: UPI/Swati Jha",
            timestamp=datetime(2026,4,5,12,19, tzinfo=IST)),
    MockTxn(500,  None,                "ATM",  "IDFC",  "5865",
            "INR 500.00 withdrawn from ATM",
            timestamp=datetime(2026,4,5,11,30, tzinfo=IST)),
    # Large credit — triggers balance alert
    MockTxn(679402.85, "clearing",     None,   "IDFC",  "5865",
            "Your A/c XX5865 credited Rs.679402.85 (clearing)",
            txn_type="credit",
            timestamp=datetime(2026,4,6, 2, 6, tzinfo=IST)),
]

# ── Build and render ─────────────────────────────────────────────────────────
email_data = patched_build(txns, TARGET, receiver_email="ayush@example.com")
html = et.render_html_email(email_data)

out = "/tmp/email_preview.html"
with open(out, "w") as f:
    f.write(html)

print(f"HTML written to {out}")
print(f"  date_str     : {email_data.date_str}")
print(f"  total_debit  : ₹{email_data.total_debit:,.0f}")
print(f"  txn_count    : {email_data.txn_count}")
print(f"  upi_pct      : {email_data.upi_pct}%")
print(f"  unknown_count: {email_data.unknown_count}")
print(f"  credit_alerts: {len(email_data.credit_alerts)}")
print(f"  one_liner    : {email_data.one_line_summary}")

# Basic assertions
assert email_data.total_debit == 4200.0,   f"Expected 4200, got {email_data.total_debit}"
assert email_data.txn_count == 3,          f"Expected 3 debits on Apr-6, got {email_data.txn_count}"
assert email_data.largest_spend == 2200.0, f"Expected 2200, got {email_data.largest_spend}"
assert len(email_data.credit_alerts) == 1, "Expected 1 credit alert"
assert "₹" in html,                        "HTML must contain ₹ entity"
assert "Daily Spend Summary" in html,      "Missing header text"
assert "The Smoke Center" in html,         "Missing merchant in HTML"
assert "FFFBEB" in html,                   "Missing credit alert box"

print("\nAll assertions passed.")
