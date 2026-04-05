from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TransactionType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    UNKNOWN = "unknown"


@dataclass
class SMSMessage:
    id: str
    sender: str
    body: str
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "body": self.body,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Transaction:
    sms_id: str
    amount: float
    transaction_type: TransactionType
    timestamp: datetime
    raw_sms: str
    merchant: Optional[str] = None
    account_last4: Optional[str] = None
    payment_mode: Optional[str] = None  # UPI, NEFT, IMPS, Credit Card, Debit Card, ATM
    reference: Optional[str] = None
    bank: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "sms_id": self.sms_id,
            "amount": self.amount,
            "transaction_type": self.transaction_type.value,
            "timestamp": self.timestamp.isoformat(),
            "date": self.timestamp.date().isoformat(),
            "merchant": self.merchant,
            "account_last4": self.account_last4,
            "payment_mode": self.payment_mode,
            "reference": self.reference,
            "bank": self.bank,
            "raw_sms": self.raw_sms,
        }
