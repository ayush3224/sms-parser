"""Supabase persistence layer for SMS messages and transactions."""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pytz
from supabase import create_client, Client

from .models import SMSMessage, Transaction, TransactionType

log = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# Supabase free-tier database cap
FREE_TIER_BYTES = 500 * 1024 * 1024   # 500 MB
WARN_THRESHOLD  = 0.80                 # start cleanup at 80 %
TARGET_USAGE    = 0.65                 # clean down to 65 %
MIN_KEEP_DAYS   = 30                   # always retain the most-recent 30 days


class SupabaseStore:
    """
    Thin wrapper around the Supabase Python client.

    All timestamps are stored as ISO-8601 strings with timezone offset so that
    Postgres keeps them as TIMESTAMPTZ (full precision, no information loss).
    """

    def __init__(self, url: str, key: str) -> None:
        self._db: Client = create_client(url, key)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_sms(self, sms: SMSMessage) -> None:
        """Insert or ignore a raw SMS (idempotent on id)."""
        self._db.table("sms_messages").upsert(
            {
                "id":        sms.id,
                "sender":    sms.sender,
                "body":      sms.body,
                "timestamp": sms.timestamp.isoformat(),   # keeps tz offset → TIMESTAMPTZ
            },
            on_conflict="id",
        ).execute()

    def upsert_transaction(self, txn: Transaction) -> None:
        """Insert or update a parsed transaction (idempotent on sms_id)."""
        self._db.table("transactions").upsert(
            {
                "sms_id":           txn.sms_id,
                "amount":           float(txn.amount),
                "transaction_type": txn.transaction_type.value,
                "timestamp":        txn.timestamp.isoformat(),
                "merchant":         txn.merchant,
                "account_last4":    txn.account_last4,
                "payment_mode":     txn.payment_mode,
                "reference":        txn.reference,
                "bank":             txn.bank,
                "raw_sms":          txn.raw_sms,
            },
            on_conflict="sms_id",
        ).execute()

    def save(self, sms: SMSMessage, txn: Optional[Transaction]) -> None:
        """Persist an SMS and its transaction (if parsed successfully)."""
        self.upsert_sms(sms)
        if txn:
            self.upsert_transaction(txn)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_all_sms(self) -> List[SMSMessage]:
        rows = (
            self._db.table("sms_messages")
            .select("*")
            .order("timestamp")
            .execute()
        )
        return [self._row_to_sms(r) for r in rows.data]

    def load_all_transactions(self) -> List[Transaction]:
        rows = (
            self._db.table("transactions")
            .select("*")
            .order("timestamp")
            .execute()
        )
        return [self._row_to_txn(r) for r in rows.data]

    # ------------------------------------------------------------------
    # Storage monitoring & auto-cleanup
    # ------------------------------------------------------------------

    def get_usage_pct(self) -> float:
        """
        Return current DB usage as a fraction (0.0 – 1.0).
        Requires the get_db_size_bytes() function to exist in Supabase
        (see supabase/schema.sql).
        """
        try:
            result = self._db.rpc("get_db_size_bytes").execute()
            return result.data / FREE_TIER_BYTES
        except Exception:
            log.exception("Could not read DB size — defaulting to 0%%")
            return 0.0

    def cleanup_if_needed(self) -> Tuple[bool, str]:
        """
        If storage > WARN_THRESHOLD, delete the oldest records in batches
        until usage drops to TARGET_USAGE.  Records within the last
        MIN_KEEP_DAYS days are never deleted.

        Returns (cleanup_happened, human_readable_message).
        """
        usage = self.get_usage_pct()

        if usage < WARN_THRESHOLD:
            msg = f"Storage at {usage:.1%} — within safe limits."
            log.debug(msg)
            return False, msg

        log.warning("Storage at %.1f%% — starting cleanup", usage * 100)

        # Hard floor: never delete records newer than MIN_KEEP_DAYS days ago
        keep_after = (datetime.now(tz=IST) - timedelta(days=MIN_KEEP_DAYS)).isoformat()

        total_deleted = 0
        for _ in range(20):                        # safety cap on iterations
            rows = (
                self._db.table("transactions")
                .select("sms_id")
                .lt("timestamp", keep_after)
                .order("timestamp")                # oldest first
                .limit(200)
                .execute()
            )
            if not rows.data:
                break

            ids = [r["sms_id"] for r in rows.data]
            # transactions → cascade-delete via FK removes sms_messages rows too
            self._db.table("transactions").delete().in_("sms_id", ids).execute()
            self._db.table("sms_messages").delete().in_("id", ids).execute()
            total_deleted += len(ids)

            if self.get_usage_pct() < TARGET_USAGE:
                break

        final_usage = self.get_usage_pct()
        msg = (
            f"Cleanup removed {total_deleted} records. "
            f"Storage now at {final_usage:.1%}."
        )
        log.info(msg)
        return True, msg

    # ------------------------------------------------------------------
    # Internal converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_sms(row: dict) -> SMSMessage:
        ts = datetime.fromisoformat(row["timestamp"])
        if ts.tzinfo is None:
            ts = IST.localize(ts)
        return SMSMessage(
            id=row["id"],
            sender=row["sender"],
            body=row["body"],
            timestamp=ts,
        )

    @staticmethod
    def _row_to_txn(row: dict) -> Transaction:
        ts = datetime.fromisoformat(row["timestamp"])
        if ts.tzinfo is None:
            ts = IST.localize(ts)
        return Transaction(
            sms_id=row["sms_id"],
            amount=float(row["amount"]),
            transaction_type=TransactionType(row["transaction_type"]),
            timestamp=ts,
            raw_sms=row.get("raw_sms", ""),
            merchant=row.get("merchant"),
            account_last4=row.get("account_last4"),
            payment_mode=row.get("payment_mode"),
            reference=row.get("reference"),
            bank=row.get("bank"),
        )
