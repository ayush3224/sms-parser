"""Load SMS messages from various sources."""

import json
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List

import pytz

from .models import SMSMessage

IST = pytz.timezone("Asia/Kolkata")


class SMSReader:
    """Reads SMS messages from a file (JSON or Android XML backup)."""

    def load(self, path: str) -> List[SMSMessage]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"SMS data file not found: {path}")

        if p.suffix.lower() == ".xml":
            return self._load_android_xml(p)
        else:
            return self._load_json(p)

    # ------------------------------------------------------------------
    # JSON format: list of {id?, sender, body, timestamp}
    # ------------------------------------------------------------------

    def _load_json(self, path: Path) -> List[SMSMessage]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        messages = []
        for i, item in enumerate(data):
            ts_raw = item.get("timestamp") or item.get("date") or item.get("time")
            timestamp = self._parse_timestamp(ts_raw)
            messages.append(
                SMSMessage(
                    id=str(item.get("id", f"sms-{i}")),
                    sender=item.get("sender") or item.get("address") or "UNKNOWN",
                    body=item.get("body") or item.get("message") or item.get("text", ""),
                    timestamp=timestamp,
                )
            )
        return messages

    # ------------------------------------------------------------------
    # Android SMS Backup & Restore XML format
    # ------------------------------------------------------------------

    def _load_android_xml(self, path: Path) -> List[SMSMessage]:
        tree = ET.parse(path)
        root = tree.getroot()
        messages = []

        for sms in root.findall(".//sms"):
            address = sms.get("address", "UNKNOWN")
            body = sms.get("body", "")
            # Android backup stores epoch milliseconds in 'date'
            date_ms = sms.get("date", "0")
            try:
                ts = datetime.fromtimestamp(int(date_ms) / 1000, tz=IST)
            except (ValueError, OSError):
                ts = datetime.now(tz=IST)

            messages.append(
                SMSMessage(
                    id=str(uuid.uuid4()),
                    sender=address,
                    body=body,
                    timestamp=ts,
                )
            )
        return messages

    # ------------------------------------------------------------------
    # Timestamp parsing
    # ------------------------------------------------------------------

    def _parse_timestamp(self, value) -> datetime:
        if value is None:
            return datetime.now(tz=IST)

        # Epoch milliseconds (int or float)
        if isinstance(value, (int, float)):
            ts = value / 1000 if value > 1e10 else value
            return datetime.fromtimestamp(ts, tz=IST)

        # ISO 8601 string
        if isinstance(value, str):
            for fmt in (
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(value, fmt)
                    if dt.tzinfo is None:
                        dt = IST.localize(dt)
                    return dt
                except ValueError:
                    continue

        return datetime.now(tz=IST)
