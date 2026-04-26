"""
FastAPI webhook server that receives SMS forwarded from an Android phone.

Compatible with:
  • MacroDroid (Android) — default JSON format with "phone number" / "received at"
  • SMS Gateway for Android (https://sms-gate.app) — camelCase "phoneNumber" format
  • Any HTTP client that POSTs JSON with sender + body + timestamp fields
"""

import asyncio
import hashlib
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
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
# Async scheduler loops (run inside uvicorn's event loop — reliable on Railway)
# ---------------------------------------------------------------------------

async def _daily_summary_loop(on_summary: Callable) -> None:
    """Fire on_summary(date) every day at 10:00 AM IST. Runs in uvicorn's asyncio loop."""
    while True:
        now      = datetime.now(tz=IST)
        next_run = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait_secs = (next_run - now).total_seconds()
        log.info("Next daily summary at %s (in %.0f s / %.1f h)",
                 next_run.strftime("%Y-%m-%d %H:%M:%S IST"),
                 wait_secs, wait_secs / 3600)
        await asyncio.sleep(wait_secs)

        yesterday = (datetime.now(tz=IST) - timedelta(days=1)).date()
        log.info("Daily summary loop: firing for %s", yesterday)
        try:
            # on_summary does blocking I/O (Supabase + Claude) — run in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, on_summary, yesterday)
        except Exception:
            log.exception("Daily summary loop: on_summary raised an exception")


async def _storage_check_loop(on_storage_check: Callable) -> None:
    """Call on_storage_check() every 6 hours. Runs in uvicorn's asyncio loop."""
    while True:
        await asyncio.sleep(6 * 3600)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, on_storage_check)
        except Exception:
            log.exception("Storage check loop raised an exception")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    on_sms: Callable[[SMSMessage], None],
    secret: Optional[str] = None,
    on_summary: Optional[Callable] = None,
    on_storage_check: Optional[Callable] = None,
) -> FastAPI:
    """
    Build the FastAPI app.

    Args:
        on_sms:            Callback invoked for every valid incoming SMS.
        secret:            If set, requests must include X-Secret: <secret> header.
        on_summary:        Called with (date) at 10 AM IST daily.
        on_storage_check:  Called every 6 hours for Supabase storage cleanup.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if on_summary:
            tasks.append(asyncio.create_task(_daily_summary_loop(on_summary)))
            log.info("Daily summary loop started (fires at 10:00 AM IST)")
        if on_storage_check:
            tasks.append(asyncio.create_task(_storage_check_loop(on_storage_check)))
            log.info("Storage check loop started (every 6 h)")
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(
        title="SMS Spend Agent — Webhook",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "utc_now": datetime.utcnow().isoformat() + "Z",
            "ist_now": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }

    @app.post("/trigger-summary")
    async def trigger_summary(request: Request):
        """Trigger the daily summary email on demand — no laptop needed."""
        if secret and request.headers.get("X-Secret", "") != secret:
            raise HTTPException(status_code=401, detail="Invalid secret")
        if on_summary is None:
            raise HTTPException(status_code=503, detail="Summary callback not configured")

        date_str = request.query_params.get("date")
        if date_str:
            try:
                from datetime import date
                target = date.fromisoformat(date_str)
            except ValueError:
                raise HTTPException(status_code=400, detail="Bad date, use YYYY-MM-DD")
        else:
            target = (datetime.now(tz=IST) - timedelta(days=1)).date()

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, on_summary, target)
        return {"status": "triggered", "date": str(target)}

    @app.post("/webhook/sms")
    async def receive_sms(request: Request):
        if secret:
            if request.headers.get("X-Secret", "") != secret:
                raise HTTPException(status_code=401, detail="Invalid secret")

        raw_bytes = await request.body()
        decoded   = raw_bytes.decode("utf-8", errors="replace")

        raw = {}
        try:
            import json as _json
            raw = _json.loads(decoded)
        except Exception:
            raw = {"message": decoded}

        log.debug("SMS webhook payload: %s", raw)

        if "phoneNumber" in raw:
            # SMS Gateway for Android (camelCase)
            sender = str(raw.get("phoneNumber", "UNKNOWN"))
            body   = str(raw.get("message", ""))
            ts     = _parse_ts(raw.get("receivedAt"))
            sms_id = str(raw.get("messageId") or _sms_id(sender, body, ts.isoformat()))
        elif "phone number" in raw:
            # MacroDroid default format (space-separated keys)
            sender = str(raw.get("phone number", "UNKNOWN"))
            body   = str(raw.get("message", ""))
            ts     = _parse_ts(raw.get("received at"))
            sms_id = _sms_id(sender, body, ts.isoformat())
        else:
            sender = str(raw.get("sender") or raw.get("from") or
                        raw.get("address") or "UNKNOWN")
            body   = str(raw.get("body") or raw.get("message") or
                        raw.get("text") or "")
            ts     = _parse_ts(raw.get("timestamp") or raw.get("date") or
                               raw.get("receivedAt"))
            sms_id = str(raw.get("id") or _sms_id(sender, body, ts.isoformat()))

        if not body.strip():
            raise HTTPException(status_code=400, detail="Empty SMS body")

        sms = SMSMessage(id=sms_id, sender=sender, body=body, timestamp=ts)
        on_sms(sms)

        log.info("Ingested SMS id=%s sender=%s ts=%s", sms_id, sender, ts.isoformat())
        return {"status": "ok", "id": sms_id}

    return app


# ---------------------------------------------------------------------------
# Background thread wrapper (used by CLI only)
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
