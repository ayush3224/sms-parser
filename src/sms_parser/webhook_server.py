"""
FastAPI webhook server that receives SMS forwarded from an Android phone.

Compatible with:
  • SMS Gateway for Android  (https://sms-gate.app)  — recommended, free
  • Any HTTP client that POSTs JSON with sender + body + timestamp fields
"""

import hashlib
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Optional

import pytz
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from .models import SMSMessage

log = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Timestamp normaliser
# ---------------------------------------------------------------------------

def _parse_ts(value: Any) -> datetime:
    """Accept epoch-ms (int/float) or ISO-8601 string; always return IST-aware datetime."""
    if not value:
        return datetime.now(tz=IST)
    if isinstance(value, (int, float)):
        epoch_s = value / 1000 if value > 1e10 else float(value)
        return datetime.fromtimestamp(epoch_s, tz=IST)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(IST) if dt.tzinfo else IST.localize(dt)
    except ValueError:
        return datetime.now(tz=IST)


def _sms_id(sender: str, body: str, ts: str) -> str:
    return "wh-" + hashlib.md5(f"{sender}|{body}|{ts}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    on_sms: Callable[[SMSMessage], None],
    secret: Optional[str] = None,
) -> FastAPI:
    """
    Build the FastAPI app.

    Args:
        on_sms:  Callback invoked for every valid incoming SMS.
        secret:  If set, requests must include `X-Secret: <secret>` header.
    """
    app = FastAPI(title="SMS Spend Agent — Webhook", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/webhook/sms")
    async def receive_sms(request: Request):
        # --- optional secret check ---
        if secret:
            provided = request.headers.get("X-Secret", "")
            if provided != secret:
                raise HTTPException(status_code=401, detail="Invalid secret")

        # --- read raw bytes first so we never crash on bad JSON ---
        raw_bytes = await request.body()
        content_type = request.headers.get("content-type", "")

        raw = {}
        if "application/json" in content_type:
            try:
                import json as _json
                raw = _json.loads(raw_bytes.decode("utf-8", errors="replace"))
            except Exception:
                # JSON is malformed — treat entire body as the SMS message
                raw = {"message": raw_bytes.decode("utf-8", errors="replace")}
        else:
            # form-encoded or plain text
            raw = {"message": raw_bytes.decode("utf-8", errors="replace")}

        log.debug("SMS webhook payload: %s", raw)

        # --- normalise across known app formats ---
        if "phoneNumber" in raw:
            sender  = str(raw.get("phoneNumber", "UNKNOWN"))
            body    = str(raw.get("message", ""))
            ts      = _parse_ts(raw.get("receivedAt"))
            sms_id  = str(raw.get("messageId") or _sms_id(sender, body, ts.isoformat()))
        else:
            sender  = str(raw.get("sender") or raw.get("from") or
                         raw.get("address") or "UNKNOWN")
            body    = str(raw.get("body") or raw.get("message") or
                         raw.get("text") or "")
            ts      = _parse_ts(raw.get("timestamp") or raw.get("date") or
                                raw.get("receivedAt"))
            sms_id  = str(raw.get("id") or _sms_id(sender, body, ts.isoformat()))

        if not body.strip():
            raise HTTPException(status_code=400, detail="Empty SMS body")

        sms = SMSMessage(id=sms_id, sender=sender, body=body, timestamp=ts)
        on_sms(sms)

        log.info("Ingested SMS id=%s sender=%s ts=%s", sms_id, sender, ts.isoformat())
        return {"status": "ok", "id": sms_id}

    return app


# ---------------------------------------------------------------------------
# Background thread wrapper
# ---------------------------------------------------------------------------

class WebhookServer:
    """Runs the FastAPI app in a daemon thread so it doesn't block the CLI."""

    def __init__(
        self,
        on_sms: Callable[[SMSMessage], None],
        host: str = "0.0.0.0",
        port: int = 8000,
        secret: Optional[str] = None,
    ) -> None:
        app = create_app(on_sms=on_sms, secret=secret)
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True, name="webhook")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True
