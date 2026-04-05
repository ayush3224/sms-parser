"""Parse business SMS messages to extract transaction details."""

import re
from typing import Optional

from .models import SMSMessage, Transaction, TransactionType

# Patterns to match currency amounts (handles Indian formatting like 1,23,456.78)
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
]

_BANK_SENDERS = {
    'HDFC': ['HDFCBK', 'HDFCBANK', 'HDFC'],
    'ICICI': ['ICICIB', 'ICICIBANK', 'ICICI'],
    'SBI': ['SBIBK', 'SBIINB', 'SBI', 'STATEBK'],
    'Axis': ['AXISBK', 'AXISBANK', 'AXIS'],
    'Kotak': ['KOTAKB', 'KOTAK'],
    'Yes Bank': ['YESBK', 'YESBANK'],
    'IndusInd': ['INDUSBK', 'INDUSIND'],
    'IDFC': ['IDFCBK', 'IDFCFB'],
    'Paytm': ['PAYTM', 'PYTM'],
    'PhonePe': ['PHONPE', 'PHONEPE'],
    'Amazon Pay': ['AMAZONPAY', 'AMZNPAY'],
}

_PAYMENT_MODES = [
    ('UPI', r'\bUPI\b'),
    ('NEFT', r'\bNEFT\b'),
    ('IMPS', r'\bIMPS\b'),
    ('RTGS', r'\bRTGS\b'),
    ('Credit Card', r'\bcredit\s+card\b'),
    ('Debit Card', r'\bdebit\s+card\b'),
    ('ATM', r'\bATM\b'),
    ('Net Banking', r'\bnet\s*banking\b|\bnetbanking\b'),
]

_MERCHANT_PATTERNS = [
    r'(?:at|to)\s+([A-Z][A-Za-z0-9\s&\-\.\']{2,40}?)(?:\s+at\b|\s+on\b|\s+for\b|\s+via\b|\s+Ref\b|\s+Info|\.|$)',
    r'paid\s+to\s+([A-Za-z][A-Za-z0-9\s&\-\.\']{2,40}?)(?:\s+at\b|\s+via\b|\s+Ref\b|\s+UPI\b|\.|$)',
    r'VPA\s*[:\-]?\s*([^\s@]+@[^\s]+)',
]

_ACCOUNT_PATTERNS = [
    r'(?:a/c|acct?|account|card)\s*(?:no\.?|num(?:ber)?|ending|xx+)[\s:]*([0-9]{4})\b',
    r'(?:a/c|acct?|account|card)\s*\*+([0-9]{4})\b',
    r'\bXX+([0-9]{4})\b',
    r'\*+([0-9]{4})\b',
]

_REFERENCE_PATTERNS = [
    r'(?:Ref\.?(?:\s+No\.?)?|Reference\s+(?:No\.?|ID)?|Txn\.?\s*(?:No\.?|ID)?|UTR)\s*[:\-]?\s*([A-Z0-9]{8,20})',
    r'\bUPI[:\s]+([0-9]{12,15})\b',
]


class SMSParser:
    """Parses individual business SMS messages into structured Transaction objects."""

    def parse(self, sms: SMSMessage) -> Optional[Transaction]:
        """Return a Transaction if the SMS looks like a financial transaction, else None."""
        body = sms.body

        amount = self._extract_amount(body)
        if amount is None:
            return None

        txn_type = self._determine_type(body)

        return Transaction(
            sms_id=sms.id,
            amount=amount,
            transaction_type=txn_type,
            timestamp=sms.timestamp,
            raw_sms=body,
            merchant=self._extract_merchant(body),
            account_last4=self._extract_account(body),
            payment_mode=self._extract_payment_mode(body),
            reference=self._extract_reference(body),
            bank=self._extract_bank(sms.sender, body),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
                if 3 <= len(merchant) <= 50:
                    return merchant
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
