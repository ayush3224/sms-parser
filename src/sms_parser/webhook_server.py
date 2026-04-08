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
    on_summary: Optional[Callable] = None,
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
        import datetime
        return {
            "status": "ok",
            "utc_now": datetime.datetime.utcnow().isoformat() + "Z",
            "ist_now": datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }

    @app.post("/trigger-summary")
    async def trigger_summary(request: Request):
        """Fire today's or yesterday's summary email on demand (no laptop needed)."""
        if secret:
            if request.headers.get("X-Secret", "") != secret:
                raise HTTPException(status_code=401, detail="Invalid secret")
        if on_summary is None:
            raise HTTPException(status_code=503, detail="Summary callback not configured")
        import datetime as _dt
        # Default to yesterday IST; accept ?date=YYYY-MM-DD
        params    = request.query_params
        date_str  = params.get("date")
        if date_str:
            try:
                target = _dt.date.fromisoformat(date_str)
            except ValueError:
                raise HTTPException(status_code=400, detail="Bad date format, use YYYY-MM-DD")
        else:
            target = (_dt.datetime.now(tz=IST) - _dt.timedelta(days=1)).date()
        # Run in background so the HTTP response returns immediately
        import threading
        threading.Thread(target=on_summary, args=(target,), daemon=True).start()
        return {"status": "triggered", "date": str(target)}

    @app.post("/webhook/sms")
    async def receive_sms(request: Request):
        # --- optional secret check ---
        if secret:
            provided = request.headers.get("X-Secret", "")
            if provided != secret:
                raise HTTPException(status_code=401, detail="Invalid secret")

        # --- read raw bytes; always try JSON regardless of Content-Type ---
        raw_bytes = await request.body()
        decoded   = raw_bytes.decode("utf-8", errors="replace")

        raw = {}
        try:
            import json as _json
            raw = _json.loads(decoded)
        except Exception:
            # Not JSON — treat entire body as the SMS message
            raw = {"message": decoded}

        log.debug("SMS webhook payload: %s", raw)

        # --- normalise across known app/format variants ---
        if "phoneNumber" in raw:
            # SMS Gateway for Android (camelCase)
            sender  = str(raw.get("phoneNumber", "UNKNOWN"))
            body    = str(raw.get("message", ""))
            ts      = _parse_ts(raw.get("receivedAt"))
            sms_id  = str(raw.get("messageId") or _sms_id(sender, body, ts.isoformat()))
        elif "phone number" in raw:
            # MacroDroid default format (space-separated keys)
            sender  = str(raw.get("phone number", "UNKNOWN"))
            body    = str(raw.get("message", ""))
            ts      = _parse_ts(raw.get("received at"))
            sms_id  = _sms_id(sender, body, ts.isoformat())
        else:
            # Generic fallback
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
