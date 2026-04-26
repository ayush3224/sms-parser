"""Parse business SMS messages to extract transaction details."""

import json
import re
from typing import Optional

from .models import SMSMessage, Transaction, TransactionType

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_AMOUNT_PATTERNS = [
    r'(?:Rs\.?|INR|₹)\s*([0-9,]+(?:\.[0-9]{1,2})?)',
    r'([0-9,]+(?:\.[0-9]{1,2})?)\s*(?:Rs\.?|INR|₹)',
    r'(?:amount|amt)(?:\s+of)?\s+(?:Rs\.?|INR|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)',
]

_DEBIT_KEYWORDS = [
    'debited', 'spent', 'paid', 'payment of', 'purchase of',
    'withdrawn', 'deducted', 'charged', 'sent',
]
_CREDIT_KEYWORDS = [
    'credited', 'received', 'deposited', 'refund', 'cashback', 'reversed',
    'added to',   # Zomato Money / wallet cashbacks
]

# Messages matching any of these are NOT real transactions — skip entirely
_SKIP_PATTERNS = [
    # Future / scheduled deductions (not yet executed)
    r'\bwill\s+be\s+(?:deducted|charged|debited|processed)\b',
    r'\bscheduled\s+(?:for|on)\b',
    r'\bfalling\s+due\b',                          # PNB loan instalment notices
    # OTP messages (not transaction confirmations)
    r'\bOne-Time\s+Password\b',                    # ICICI OTP
    r'\bOTP\s+is\s+\d+\b',                        # HDFC OTP
    # Balance-only alerts
    r'\bbalance\s+(?:is|alert|update|intimation)\b',
    r'\bavailable\s+balance\b',
    r'\baccount\s+balance\b',
    r'\bcurrent\s+balance\b',
    r'\blow\s+balance\b',
    # Investment / portfolio statements (not cash transactions)
    r'\bInvestment\s+value\s+in\s+Tier\b',         # NPS balance
    r'\btraded\s+value\s+for\b',                   # NSE trade notification
    # Standing instruction activations (not actual debits)
    r'\bactivated\s+Standing\s+Instruction\b',
    # Bank "clearing" / internal ledger credits
    r'\(clearing\)',
]

_BANK_SENDERS = {
    'HDFC':       ['HDFCBK', 'HDFCBANK', 'HDFC'],
    'ICICI':      ['ICICIB', 'ICICIBANK', 'ICICIC', 'ICICIT', 'ICICI'],
    'SBI':        ['SBIBK', 'SBIINB', 'SBI', 'STATEBK'],
    'Axis':       ['AXISBK', 'AXISBANK', 'AXIS'],
    'Kotak':      ['KOTAKB', 'KOTAK'],
    'Yes Bank':   ['YESBK', 'YESBANK'],
    'IndusInd':   ['INDUSBK', 'INDUSIND'],
    'IDFC':       ['IDFCBK', 'IDFCFB', 'IDFC FIRST', 'IDFCFIRST'],
    'PNB':        ['PNBSMS', 'PNBBANK', 'PNB'],
    'Paytm':      ['PAYTM', 'PYTM'],
    'PhonePe':    ['PHONPE', 'PHONEPE'],
    'Amazon Pay': ['AMAZONPAY', 'AMZNPAY'],
    'SBM':        ['SBMIND', 'SBMBANK', 'SBMB'],
    'Zomato':     ['ZOMATO'],
    'ITD':        ['ITDCPC'],                       # Income Tax Dept challan SMS
}

_PAYMENT_MODES = [
    ('UPI',         r'\bUPI\b|\bMandate\b'),
    ('NEFT',        r'\bNEFT\b'),
    ('IMPS',        r'\bIMPS\b'),
    ('RTGS',        r'\bRTGS\b'),
    # "spent using ICICI Bank Card" / "On HDFC Bank Card" / "using HDFC Credit Card"
    ('Credit Card', r'\bcredit\s+card\b|\busing\s+\w+(?:\s+bank)?\s+card\b|\bBank\s+Card\b'),
    ('Debit Card',  r'\bdebit\s+card\b'),
    ('ATM',         r'\bATM\b'),
    ('Net Banking', r'\bnet\s*banking\b|\bnetbanking\b'),
]

_MERCHANT_NORMALISE = {
    # E-commerce
    'AMAZONIN':          'Amazon India',
    'AMZNIN':            'Amazon India',
    'AMZNMKTP':          'Amazon',
    'AMAZON PAY IN G':   'Amazon Pay',
    'FLIPKART':          'Flipkart',
    'FIRSTCRY':          'FirstCry',
    'MYNTRA':            'Myntra',
    'NYKAA':             'Nykaa',
    # Food & delivery
    'SWIGGY':            'Swiggy',
    'ZOMATO':            'Zomato',
    'ZOMATO MONEY':      'Zomato',
    'DUNZO':             'Dunzo',
    # Grocery / quick commerce
    'BIGBASKET':         'BigBasket',
    'BLINKIT':           'Blinkit',
    'ZEPTO':             'Zepto',
    # Payments / wallets
    'PAYTMMALL':         'Paytm Mall',
    'GOOGLE PLAY':       'Google Play',
    # Finance / investments
    'INDMONEY':          'INDmoney',
    'INDSTOCKS':         'INDmoney',
    # Government
    'CHALLAN PAYMENT':   'Income Tax',
    # Local merchants (user-identified)
    'ARTICULTURAL FRU':  'Amma Shop',
    'PAPER AND PIE':     'Paper & Pie',
}

_MERCHANT_PATTERNS = [
    # HDFC card: "Spent Rs.X On HDFC Bank Card 8229 At ..MERCHANTNAME_"
    r'At\s+\.+([A-Z][A-Za-z0-9\s&\'\-]+?)(?:_|\s+On\s+\d{4})',
    # "Mandate Set Rs.X For MERCHANT From HDFC" (Google Play auto-pay etc.) — multiline SMS
    r'\bMandate\s+Set\b[\s\S]+?For\s+([A-Za-z][A-Za-z0-9\s]+?)\s+From\b',
    # "paid INR 271.00 at AMAZONIN through your Card" (SBM / card SMS)
    r'\bpaid\s+(?:INR|Rs\.?|₹)\s*[0-9,.]+\s+at\s+([A-Z][A-Za-z0-9]{2,30})\s+(?:through|via|using)\b',
    # "Rs. 25.88 added to Zomato Money" — wallet cashback / refund credits
    r'\badded\s+to\s+([A-Za-z]+(?:\s+Money|\s+Wallet)?)\b',
    # "Challan payment" → Income Tax
    r'\b(Challan\s+payment)\b',
    # "To INDmoney 06/04/26" or "To Swati Jha Ref"
    r'[Tt]o\s+([A-Z][A-Za-z][A-Za-z0-9\s&\-\.\']{1,38}?)(?:\s+[0-9]{2}/[0-9]{2}|\s+Ref\b|\s+Not\b|\s+UPI\b|\s+via\b|\.|$)',
    # "at/to MERCHANT" generic
    r'(?:at|to)\s+([A-Z][A-Za-z0-9\s&\-\.\']{2,40}?)(?:\s+at\b|\s+on\b|\s+for\b|\s+via\b|\s+Ref\b|\s+Info|\.|$)',
    # "spent using ICICI Bank Card XX3008 on 06-Apr-26 on AMAZON PAY IN G"
    r'on\s+[0-9]{2}-[A-Za-z]{3}-[0-9]{2}\s+on\s+([A-Z][A-Za-z0-9\s&/\.]{2,40}?)(?:\.\s+Avl\b|\.\s+If\b|$)',
    # "For INDmoney mandate" (E-Mandate confirmation)
    r'\bFor\s+([A-Z][A-Za-z0-9\s&\-\.]{2,40}?)\s+mandate\b',
    r'paid\s+to\s+([A-Za-z][A-Za-z0-9\s&\-\.\']{2,40}?)(?:\s+at\b|\s+via\b|\s+Ref\b|\s+UPI\b|\.|$)',
    r'VPA\s*[:\-]?\s*([^\s@]+@[^\s]+)',
    r'([A-Z][A-Za-z\s]{2,30}?)\s+credited\b',   # "Swati Jha credited"
]

_ACCOUNT_PATTERNS = [
    r'(?:a/c|acct?|account|card)\s*(?:no\.?|num(?:ber)?|ending|xx+)[\s:]*([0-9]{4})\b',
    r'(?:a/c|acct?|account|card)\s*\*+([0-9]{4})\b',
    r'\bXX([0-9]{4})\b',
    r'\bA/c\s+XX([0-9]{4})\b',
    r'\bA/c\s+([0-9]{4})\b',
    r'[Cc]ard\s+XX([0-9]{4})\b',
    r'\*+([0-9]{4})\b',
]

_REFERENCE_PATTERNS = [
    r'(?:Ref\.?(?:\s+No\.?)?|Reference\s+(?:No\.?|ID)?|Txn\.?\s*(?:No\.?|ID)?|UTR|RRN)\s*[:\-]?\s*([A-Z0-9]{8,20})',
    r'\bUPI[:\s]+([0-9]{12,15})\b',
    r'\bRRN\s+([0-9]{10,15})\b',
]

_CLAUDE_PARSE_PROMPT = """\
Extract transaction details from this Indian bank SMS. Return ONLY valid JSON with these fields:
- bank: bank name (string or null)
- amount: numeric amount in rupees (number or null)
- transaction_type: "debit" or "credit" or "unknown"
- merchant: recipient/merchant name (string or null)
- account_last4: last 4 digits of account (string or null)
- payment_mode: "UPI", "NEFT", "IMPS", "RTGS", "Credit Card", "Debit Card", "ATM", "Net Banking", or null

SMS: {body}

JSON:"""


class SMSParser:
    """Parses individual business SMS messages into structured Transaction objects."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key

    def parse(self, sms: SMSMessage, on_unknown_template=None) -> Optional[Transaction]:
        """Return a Transaction if the SMS looks like a financial transaction, else None."""
        body = sms.body

        if self._should_skip(body):
            return None

        amount = self._extract_amount(body)
        if amount is None:
            return None

        sender        = sms.sender or ""
        bank          = self._extract_bank(sender, body)
        merchant      = self._extract_merchant(body)
        payment_mode  = self._extract_payment_mode(body)
        account_last4 = self._extract_account(body)

        missing = [f for f, v in [("bank", bank), ("merchant", merchant)] if not v]
        needs_claude = bool(missing) or sender.lower() in ("unknown", "")

        if self._api_key and needs_claude:
            claude_data = self._claude_parse(body)
            if claude_data:
                bank          = bank          or claude_data.get("bank")
                merchant      = merchant      or claude_data.get("merchant")
                payment_mode  = payment_mode  or claude_data.get("payment_mode")
                account_last4 = account_last4 or claude_data.get("account_last4")

            if on_unknown_template and missing:
                try:
                    on_unknown_template(
                        body=body,
                        sender=sender,
                        bank=bank,
                        merchant=merchant,
                        missing_fields=missing,
                    )
                except Exception:
                    pass

        return Transaction(
            sms_id=sms.id,
            amount=amount,
            transaction_type=self._determine_type(body),
            timestamp=sms.timestamp,
            raw_sms=body,
            merchant=merchant,
            account_last4=account_last4,
            payment_mode=payment_mode,
            reference=self._extract_reference(body),
            bank=bank,
        )

    # ------------------------------------------------------------------
    # Claude fallback
    # ------------------------------------------------------------------

    def _claude_parse(self, body: str) -> Optional[dict]:
        """Call Claude Haiku to extract fields the regex couldn't find."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": _CLAUDE_PARSE_PROMPT.format(body=body),
                }],
            )
            text = response.content[0].text.strip()
            if "```" in text:
                m = re.search(r'\{.*\}', text, re.DOTALL)
                text = m.group(0) if m else text
            return json.loads(text)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Regex helpers
    # ------------------------------------------------------------------

    def _should_skip(self, text: str) -> bool:
        for pattern in _SKIP_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _extract_amount(self, text: str) -> Optional[float]:
        for pattern in _AMOUNT_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(',', ''))
                except ValueError:
                    continue
        return None

    def _determine_type(self, text: str) -> TransactionType:
        lower = text.lower()
        for kw in _DEBIT_KEYWORDS:
            if kw in lower:
                return TransactionType.DEBIT
        for kw in _CREDIT_KEYWORDS:
            if kw in lower:
                return TransactionType.CREDIT
        return TransactionType.UNKNOWN

    def _extract_merchant(self, text: str) -> Optional[str]:
        for pattern in _MERCHANT_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                merchant = m.group(1).strip().rstrip('.')
                # Strip HDFC card store/branch codes e.g. "FIRSTCRY 2004 DA" → "FIRSTCRY"
                merchant = re.sub(r'\s+\d{4}\s+[A-Z]{2,}$', '', merchant).strip()
                if 3 <= len(merchant) <= 50:
                    normalised = _MERCHANT_NORMALISE.get(merchant.upper())
                    return normalised if normalised else merchant
        return None

    def _extract_account(self, text: str) -> Optional[str]:
        for pattern in _ACCOUNT_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _extract_payment_mode(self, text: str) -> Optional[str]:
        for mode, pattern in _PAYMENT_MODES:
            if re.search(pattern, text, re.IGNORECASE):
                return mode
        return None

    def _extract_bank(self, sender: str, text: str) -> Optional[str]:
        combined = f"{sender} {text}"
        for bank, aliases in _BANK_SENDERS.items():
            for alias in aliases:
                if re.search(rf'\b{re.escape(alias)}\b', combined, re.IGNORECASE):
                    return bank
        return None

    def _extract_reference(self, text: str) -> Optional[str]:
        for pattern in _REFERENCE_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1)
        return None
