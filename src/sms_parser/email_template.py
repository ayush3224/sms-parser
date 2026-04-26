"""
Structured email data builder and HTML renderer for daily spend summaries.

Usage:
    from src.sms_parser.email_template import build_email_data, render_html_email
    data = build_email_data(transactions, for_date, receiver_email="you@gmail.com")
    data.one_line_summary = "..."
    html = render_html_email(data)
"""

import html as _html
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

import json as _json
import platform
import pytz

IST = pytz.timezone("Asia/Kolkata")


def _extract_sms_text(raw: str) -> str:
    """If raw_sms is a JSON wrapper (MacroDroid format), return just the message text."""
    raw = (raw or "").strip()
    if raw.startswith("{"):
        try:
            data = _json.loads(raw)
            return str(data.get("message") or raw)
        except Exception:
            pass
    return raw


def _strftime_no_pad(dt, fmt: str) -> str:
    """strftime with no-pad day/hour that works on both Linux and Windows."""
    if platform.system() == "Windows":
        fmt = fmt.replace("%-", "%#")
    return dt.strftime(fmt)

# Payment-mode → badge label
_BADGE_MAP = {
    "upi":         "UPI",
    "atm":         "ATM",
    "neft":        "NET",
    "imps":        "NET",
    "rtgs":        "NET",
    "credit card": "CRD",
    "debit card":  "DBT",
}

# Badge label → background colour
_BADGE_COLORS = {
    "UPI": "#6B7280",
    "ATM": "#92400E",
    "NET": "#047857",
    "CRD": "#1D4ED8",
    "DBT": "#1E40AF",
    "OTH": "#7C3AED",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _badge(payment_mode: Optional[str]) -> str:
    if not payment_mode:
        return "OTH"
    pm = payment_mode.lower()
    for key, val in _BADGE_MAP.items():
        if key in pm:
            return val
    return "OTH"


def _pct(part: float, total: float) -> int:
    if total <= 0:
        return 0
    return round(part / total * 100)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BarDay:
    label:          str    # display label ("1", "Mon", etc.) — empty = no label
    amount:         float  # total debit for this day
    is_highlighted: bool   # True for the summary date (shown in red)
    date_str:       str    # "06 Apr" — used in bar title tooltip


@dataclass
class EmailRow:
    merchant:     str
    amount:       float
    txn_type:     str            # "debit" | "credit"
    payment_mode: str            # display string
    bank:         str
    account_last4: str           # already prefixed "XX1234" or ""
    time_str:     str            # "3:27 PM"
    raw_sms:      str
    badge:        str            # "UPI", "ATM", "OTH" …


@dataclass
class EmailData:
    date_str:            str            # "6 April 2026"
    date_short:          str            # "06 Apr 2026"
    day_of_week:         str            # "Monday"
    total_debit:         float
    txn_count:           int
    largest_spend:       float
    largest_merchant:    str
    upi_total:           float
    upi_pct:             int
    unknown_count:       int
    unknown_amount:      float
    transactions:        List[EmailRow]
    upi_instrument:      float
    card_instrument:     float
    other_instrument:    float
    upi_instrument_pct:  int
    card_instrument_pct: int
    other_instrument_pct: int
    credit_alerts:       List[dict]     # [{"amount": x, "merchant": y, "raw_sms": z}]
    one_line_summary:    str
    receiver_email:      str
    monthly_bars:        List[BarDay]  # day 1 → last day of month
    weekly_bars:         List[BarDay]  # last 7 days ending on for_date


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _llm_extract_merchant(sms_text: str, api_key: str) -> Optional[str]:
    """Ask Claude Haiku to extract the merchant/payee name from a single SMS."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=40,
            messages=[{
                "role": "user",
                "content": (
                    "From this Indian bank SMS, extract ONLY the merchant or payee name "
                    "(who money was paid to). Reply with just the name, nothing else. "
                    "If you cannot identify a merchant, reply with null.\n\nSMS: " + sms_text
                ),
            }],
        )
        result = response.content[0].text.strip().strip('"\'')
        return None if result.lower() in ("null", "none", "", "unknown") else result
    except Exception:
        return None


def build_email_data(
    transactions,           # List[Transaction]
    for_date: date,
    receiver_email: str = "",
    api_key: Optional[str] = None,
) -> EmailData:
    """Compute all fields needed for the HTML email from a transactions list."""
    from .models import TransactionType

    # --- filter to the target date (IST) ---
    day_txns = [
        t for t in transactions
        if t.timestamp.astimezone(IST).date() == for_date
    ]
    debits  = [t for t in day_txns if t.transaction_type == TransactionType.DEBIT]
    credits = [t for t in day_txns if t.transaction_type == TransactionType.CREDIT]

    total_debit = sum(t.amount for t in debits)

    # largest single spend
    largest     = max(debits, key=lambda t: t.amount, default=None)
    largest_spend    = largest.amount if largest else 0.0
    largest_merchant = (largest.merchant or "Unknown") if largest else "—"

    # UPI breakdown
    upi_debits = [t for t in debits if t.payment_mode and "upi" in t.payment_mode.lower()]
    upi_total  = sum(t.amount for t in upi_debits)
    upi_pct    = _pct(upi_total, total_debit)

    # unidentified (null merchant)
    unknown_debits = [t for t in debits if not t.merchant]
    unknown_count  = len(unknown_debits)
    unknown_amount = sum(t.amount for t in unknown_debits)

    # instrument breakdown (debits)
    upi_instr  = upi_total
    card_debits = [
        t for t in debits
        if t.payment_mode and any(
            k in t.payment_mode.lower() for k in ("credit card", "debit card")
        )
    ]
    card_instr  = sum(t.amount for t in card_debits)
    other_instr = max(total_debit - upi_instr - card_instr, 0.0)

    upi_ip   = _pct(upi_instr,   total_debit)
    card_ip  = _pct(card_instr,  total_debit)
    other_ip = _pct(other_instr, total_debit)

    # transaction rows (debits only, newest first)
    # Re-import parser lazily to avoid circular deps
    from .sms_parser import SMSParser as _SMSParser
    _parser = _SMSParser()   # regex-only instance for re-extraction

    rows: List[EmailRow] = []
    for t in sorted(debits, key=lambda x: x.timestamp, reverse=True):
        time_str = _strftime_no_pad(t.timestamp.astimezone(IST), "%-I:%M %p")

        merchant = t.merchant
        if not merchant:
            # 1. Try regex on the clean SMS text (catches SMS stored before pattern updates)
            sms_text = _extract_sms_text(t.raw_sms or "")
            merchant = _parser._extract_merchant(sms_text)
        if not merchant and api_key:
            # 2. Ask Claude Haiku — it can read what regex misses
            sms_text = _extract_sms_text(t.raw_sms or "")
            merchant = _llm_extract_merchant(sms_text, api_key)
        if not merchant:
            # 3. Last resort: bank name (better than "Unknown")
            merchant = t.bank or "Unknown"
        payment_mode = t.payment_mode
        if not payment_mode:
            sms_text = _extract_sms_text(t.raw_sms or "")
            payment_mode = _parser._extract_payment_mode(sms_text)

        rows.append(EmailRow(
            merchant      = merchant,
            amount        = t.amount,
            txn_type      = "debit",
            payment_mode  = payment_mode or "Other",
            bank          = t.bank or "",
            account_last4 = f"XX{t.account_last4}" if t.account_last4 else "",
            time_str      = time_str,
            raw_sms       = _extract_sms_text(t.raw_sms or ""),
            badge         = _badge(payment_mode),
        ))

    # credit alerts
    credit_alerts = [
        {"amount": t.amount, "merchant": t.merchant or "credit", "raw_sms": t.raw_sms or ""}
        for t in credits
    ]

    # ── Bar chart data ─────────────────────────────────────────────────────
    from .models import TransactionType as _TT

    # All debits across all time (for chart aggregation)
    all_debits = [t for t in transactions if t.transaction_type == _TT.DEBIT]

    # Group all debits by IST date
    date_totals: dict = {}
    for t in all_debits:
        d = t.timestamp.astimezone(IST).date()
        date_totals[d] = date_totals.get(d, 0.0) + t.amount

    # Monthly bars: day 1 → last day of for_date's month
    year, month     = for_date.year, for_date.month
    _, last_day     = monthrange(year, month)
    monthly_bars: List[BarDay] = []
    for day_num in range(1, last_day + 1):
        d   = date(year, month, day_num)
        amt = date_totals.get(d, 0.0)
        # Show label every 5 days and on the last day
        show = day_num == 1 or day_num % 5 == 0 or day_num == last_day
        monthly_bars.append(BarDay(
            label          = str(day_num) if show else "",
            amount         = amt,
            is_highlighted = (d == for_date),
            date_str       = d.strftime("%d %b"),
        ))

    # Weekly bars: last 7 days ending on for_date
    weekly_bars: List[BarDay] = []
    for i in range(6, -1, -1):
        d   = for_date - timedelta(days=i)
        amt = date_totals.get(d, 0.0)
        weekly_bars.append(BarDay(
            label          = d.strftime("%a"),   # "Mon", "Tue" …
            amount         = amt,
            is_highlighted = (d == for_date),
            date_str       = d.strftime("%d %b"),
        ))

    return EmailData(
        date_str             = _strftime_no_pad(for_date, "%-d %B %Y"),
        date_short           = for_date.strftime("%d %b %Y"),
        day_of_week          = for_date.strftime("%A"),
        total_debit          = total_debit,
        txn_count            = len(debits),
        largest_spend        = largest_spend,
        largest_merchant     = largest_merchant,
        upi_total            = upi_total,
        upi_pct              = upi_pct,
        unknown_count        = unknown_count,
        unknown_amount       = unknown_amount,
        transactions         = rows,
        upi_instrument       = upi_instr,
        card_instrument      = card_instr,
        other_instrument     = other_instr,
        upi_instrument_pct   = upi_ip,
        card_instrument_pct  = card_ip,
        other_instrument_pct = other_ip,
        credit_alerts        = credit_alerts,
        one_line_summary     = "",
        receiver_email       = receiver_email,
        monthly_bars         = monthly_bars,
        weekly_bars          = weekly_bars,
    )


# ---------------------------------------------------------------------------
# Bar chart renderer
# ---------------------------------------------------------------------------

def _fmt_k(amount: float) -> str:
    """Format amount compactly: 1200 -> '1.2k', 800 -> '800'."""
    if amount >= 1000:
        k = amount / 1000
        return f"{k:.0f}k" if k == int(k) else f"{k:.1f}k"
    return f"{amount:.0f}"


def _render_bar_chart(bars: List[BarDay], max_h: int = 56, show_values: bool = False) -> str:
    """Render a bottom-aligned bar chart as an email-compatible HTML table."""
    if not bars:
        return ""
    e = _html.escape
    max_amt = max((b.amount for b in bars), default=0.0) or 1.0

    cells = ""
    for bar in bars:
        if bar.amount > 0:
            bar_h = max(4, round(bar.amount / max_amt * max_h))
        else:
            bar_h = 2  # tiny stub so future/zero days are still visible
        spacer_h  = max_h - bar_h

        if bar.is_highlighted:
            bar_color   = "#B91C1C"
            label_color = "#B91C1C"
            label_w     = "700"
        elif bar.amount > 0:
            bar_color   = "#2d2d2d"
            label_color = "#888"
            label_w     = "400"
        else:
            bar_color   = "#e8e8e3"
            label_color = "#ccc"
            label_w     = "400"

        tip = f"Rs.{bar.amount:,.0f} - {bar.date_str}" if bar.amount > 0 else bar.date_str

        value_html = ""
        if show_values and bar.amount > 0:
            value_html = (
                f'<div style="font-size:7px;color:{label_color};font-weight:{label_w};'
                f'line-height:1;padding-bottom:2px;white-space:nowrap;">{_fmt_k(bar.amount)}</div>'
            )

        cells += (
            f'<td style="vertical-align:bottom;text-align:center;padding:0 1px;">'
            f'<div title="{e(tip)}">'
            f'<div style="height:{spacer_h}px;display:flex;align-items:flex-end;'
            f'justify-content:center;">{value_html}</div>'
            f'<div style="background:{bar_color};height:{bar_h}px;min-height:2px;'
            f'border-radius:2px 2px 0 0;"></div>'
            f'<div style="font-size:7px;color:{label_color};font-weight:{label_w};'
            f'padding-top:3px;line-height:1;white-space:nowrap;">{e(bar.label)}</div>'
            f'</div></td>'
        )

    return (
        "<table width='100%' cellpadding='0' cellspacing='0' role='presentation'"
        " style='border-collapse:collapse;'>"
        f"<tr>{cells}</tr>"
        "</table>"
    )


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def render_html_email(data: EmailData) -> str:
    """Render an HTML email that matches the Daily Spend Summary template."""
    e = _html.escape   # XSS-safe escaping for user-supplied strings

    # ── transaction rows ───────────────────────────────────────────────────
    txn_rows_html = ""
    for row in data.transactions:
        badge_color = _BADGE_COLORS.get(row.badge, "#6B7280")

        sub_parts = []
        if row.payment_mode and row.payment_mode.lower() not in ("other", ""):
            sub_parts.append(e(row.payment_mode))
        if row.bank:
            sub_parts.append(e(row.bank))
        if row.account_last4:
            sub_parts.append(e(row.account_last4))
        if row.time_str:
            sub_parts.append(e(row.time_str))
        sub_line = " · ".join(sub_parts)

        raw_sms_html = ""
        if row.raw_sms:
            raw_sms_html = (
                '<div style="background:#f5f5f0;border-radius:4px;'
                'padding:6px 10px;margin-top:7px;font-size:11px;color:#444;'
                "font-family:'Courier New',monospace;line-height:1.4;"
                f'word-break:break-word;">{e(row.raw_sms)}</div>'
            )

        txn_rows_html += f"""
                <tr>
                  <td style="padding:18px 0;border-bottom:1px solid #f2f2f0;">
                    <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                      <tr>
                        <td style="vertical-align:top;width:40px;">
                          <div style="background:{badge_color};color:#fff;
                                      font-size:9px;font-weight:700;letter-spacing:0.4px;
                                      text-align:center;padding:3px 6px;border-radius:4px;
                                      display:inline-block;margin-top:2px;">{e(row.badge)}</div>
                        </td>
                        <td style="vertical-align:top;padding-left:10px;">
                          <div style="font-size:15px;font-weight:700;color:#111;
                                      line-height:1.2;">{e(row.merchant)}</div>
                          <div style="font-size:11px;color:#aaa;margin-top:3px;">{sub_line}</div>
                          {raw_sms_html}
                        </td>
                        <td style="vertical-align:top;text-align:right;
                                   padding-left:16px;white-space:nowrap;width:120px;">
                          <div style="font-size:16px;font-weight:800;
                                      color:#B91C1C;">&#8722;&#8377;{row.amount:,.0f}</div>
                          <div style="font-size:11px;color:#bbb;margin-top:3px;">
                            {e(row.bank)} {e(row.account_last4)}</div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>"""

    if not txn_rows_html:
        txn_rows_html = (
            '<tr><td style="padding:20px 0;color:#aaa;font-size:14px;">'
            "No debit transactions found.</td></tr>"
        )

    # ── credit alert boxes ─────────────────────────────────────────────────
    credit_alert_html = ""
    for alert in data.credit_alerts:
        credit_alert_html += f"""
            <div style="margin-top:28px;background:#FFFBEB;border:1px solid #D97706;
                        border-radius:8px;padding:16px 20px;">
              <div style="font-size:13px;font-weight:700;color:#92400E;margin-bottom:6px;">
                Balance alert flagged as credit</div>
              <div style="font-size:12px;color:#78350F;font-style:italic;line-height:1.5;">
                {e(alert['merchant'])} &#8377;{alert['amount']:,.0f} &#8212;
                This is a balance intimation, not an actual transfer.
                Real net outflow: &#8377;{data.total_debit:,.0f}.</div>
            </div>"""

    # ── one-line summary ───────────────────────────────────────────────────
    one_liner_html = ""
    if data.one_line_summary:
        one_liner_html = f"""
            <div style="margin-top:28px;padding:14px 18px;
                        border-left:3px solid #e5e5e5;background:#fafaf8;">
              <div style="font-size:14px;color:#666;font-style:italic;line-height:1.5;">
                {e(data.one_line_summary)}</div>
            </div>"""

    # ── snapshot cards ─────────────────────────────────────────────────────
    def _card(label: str, amount: float, sub: str) -> str:
        return (
            '<td style="width:31%;vertical-align:top;">'
            '<div style="background:#f7f7f3;border-radius:8px;padding:16px 14px;">'
            f'<div style="font-size:10px;color:#bbb;letter-spacing:0.5px;">{label}</div>'
            f'<div style="font-size:22px;font-weight:900;color:#111;'
            f'letter-spacing:-0.5px;margin:5px 0;">&#8377;{amount:,.0f}</div>'
            f'<div style="font-size:11px;color:#aaa;font-style:italic;">{sub}</div>'
            "</div></td>"
        )

    spacer = '<td style="width:3.5%;"></td>'
    unknown_sub = (
        f"{data.unknown_count} unknown merchant"
        + ("s" if data.unknown_count != 1 else "")
    )
    snapshot_html = (
        "<table width='100%' cellpadding='0' cellspacing='0' role='presentation'><tr>"
        + _card("Largest spend", data.largest_spend, e(data.largest_merchant))
        + spacer
        + _card("Via UPI", data.upi_total, f"{data.upi_pct}% of total")
        + spacer
        + _card("Unidentified", data.unknown_amount, unknown_sub)
        + "</tr></table>"
    )

    # ── instrument chips ───────────────────────────────────────────────────
    def _chip(label: str, amount: float, pct: int) -> str:
        return (
            '<td style="padding-right:8px;padding-bottom:8px;">'
            '<div style="background:#f0f0ec;border-radius:20px;padding:7px 16px;">'
            f'<span style="font-size:12px;color:#888;">{label}</span>'
            f'<span style="font-size:14px;font-weight:700;color:#111;margin-left:8px;">'
            f"&#8377;{amount:,.0f}</span>"
            f'<span style="font-size:11px;color:#bbb;margin-left:6px;">{pct}%</span>'
            "</div></td>"
        )

    chips_html = (
        "<table cellpadding='0' cellspacing='0' role='presentation'><tr>"
        + _chip("UPI",   data.upi_instrument,   data.upi_instrument_pct)
        + _chip("Card",  data.card_instrument,  data.card_instrument_pct)
        + _chip("Other", data.other_instrument, data.other_instrument_pct)
        + "</tr></table>"
    )

    # ── full email ─────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Daily Spend Summary &#8212; {e(data.date_short)}</title>
</head>
<body style="margin:0;padding:0;background:#edecea;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" role="presentation"
       style="background:#edecea;">
  <tr>
    <td align="center" style="padding:28px 12px;">
      <table width="600" cellpadding="0" cellspacing="0" role="presentation"
             style="max-width:600px;width:100%;">

        <!-- === HEADER === -->
        <tr>
          <td style="background:#111111;padding:32px 40px 26px;
                     border-radius:12px 12px 0 0;">
            <div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;
                        color:rgba(255,255,255,0.38);margin-bottom:10px;">
              Daily Spend Summary</div>
            <div style="font-size:30px;font-weight:800;color:#ffffff;
                        letter-spacing:-0.5px;line-height:1.1;">
              {e(data.date_str)}</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.3);margin-top:8px;">
              {e(data.day_of_week)} &middot; India</div>
          </td>
        </tr>

        <!-- === BODY === -->
        <tr>
          <td style="background:#ffffff;padding:40px 40px 36px;">

            <!-- Total -->
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td style="vertical-align:baseline;">
                  <span style="font-size:48px;font-weight:900;color:#111;
                               letter-spacing:-2px;line-height:1;">
                    &#8377;{data.total_debit:,.0f}</span>
                </td>
                <td style="vertical-align:baseline;padding-left:14px;">
                  <span style="font-size:15px;color:#aaa;">
                    across {data.txn_count}&nbsp;transaction{"s" if data.txn_count != 1 else ""}</span>
                </td>
              </tr>
            </table>
            <div style="border-top:1px solid #eeeeec;margin:24px 0;"></div>

            <!-- SNAPSHOT -->
            <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;
                        color:#c0c0ba;margin-bottom:14px;">Snapshot</div>
            {snapshot_html}

            <!-- TRANSACTIONS -->
            <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;
                        color:#c0c0ba;margin:32px 0 4px;">Transactions</div>
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
              {txn_rows_html}
            </table>

            <!-- BY PAYMENT INSTRUMENT -->
            <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;
                        color:#c0c0ba;margin:28px 0 14px;">By Payment Instrument</div>
            {chips_html}

            <!-- THIS WEEK -->
            <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;
                        color:#c0c0ba;margin:28px 0 10px;">This Week</div>
            {_render_bar_chart(data.weekly_bars, max_h=56, show_values=True)}

            {credit_alert_html}
            {one_liner_html}

          </td>
        </tr>

        <!-- === FOOTER === -->
        <tr>
          <td style="background:#f5f5f0;padding:16px 40px;
                     border-radius:0 0 12px 12px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td style="font-size:11px;color:#c0c0ba;">
                  Expense Tracker &middot; {e(data.receiver_email)}</td>
                <td style="font-size:11px;color:#c0c0ba;text-align:right;">
                  {e(data.date_short)}</td>
              </tr>
            </table>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""
