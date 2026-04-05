#!/usr/bin/env python3
"""
Production server for cloud deployment (Railway / Render / etc).
Runs the webhook + scheduler only — no interactive CLI.
Railway automatically sets the PORT environment variable.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def _send_email_summary(summary: str, for_date) -> None:
    """Send daily summary via Gmail SMTP. Skips silently if not configured."""
    import smtplib
    from email.mime.text import MIMEText

    sender   = os.getenv("EMAIL_SENDER")    # your Gmail address
    password = os.getenv("EMAIL_PASSWORD")  # Gmail App Password
    receiver = os.getenv("EMAIL_RECEIVER")  # where to send (can be same as sender)

    if not (sender and password and receiver):
        return  # email not configured — skip silently

    subject = f"Daily Spend Summary — {for_date}"
    body    = f"Your spend summary for {for_date}:\n\n{summary}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = receiver

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, receiver, msg.as_string())
        log.info("Daily summary emailed to %s", receiver)
    except Exception as exc:
        log.warning("Failed to send summary email: %s", exc)


def main() -> None:
    # --- validate required env vars up front ---
    for var in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        if not os.getenv(var):
            raise SystemExit(f"ERROR: {var} environment variable is not set.")

    api_key        = os.environ["ANTHROPIC_API_KEY"]
    sb_url         = os.environ["SUPABASE_URL"]
    sb_key         = os.environ["SUPABASE_KEY"]
    webhook_secret = os.getenv("WEBHOOK_SECRET") or None
    port           = int(os.getenv("PORT", "8000"))   # Railway injects PORT

    # --- imports here so missing packages give a clear error ---
    import uvicorn
    from src.sms_parser.agent          import SMSSpendAgent
    from src.sms_parser.models         import SMSMessage
    from src.sms_parser.scheduler      import start_daily_scheduler
    from src.sms_parser.sms_parser     import SMSParser
    from src.sms_parser.supabase_store import SupabaseStore
    from src.sms_parser.webhook_server import create_app

    # --- Supabase ---
    store = SupabaseStore(sb_url, sb_key)
    log.info("Connected to Supabase")

    # --- load existing data ---
    parser       = SMSParser(api_key=api_key)
    sms_messages = store.load_all_sms()
    transactions = store.load_all_transactions()
    log.info("Loaded %d SMS / %d transactions", len(sms_messages), len(transactions))

    # --- agent ---
    agent = SMSSpendAgent(sms_messages, transactions, api_key)

    # --- daily summary callback: log it and email it ---
    def on_summary(summary: str, for_date) -> None:
        log.info("=== Daily Spend Summary (%s) ===\n%s", for_date, summary)
        _send_email_summary(summary, for_date)

    def on_storage_warning(message: str) -> None:
        log.warning("Storage cleanup: %s", message)

    # --- scheduler ---
    start_daily_scheduler(
        agent=agent,
        on_summary=on_summary,
        store=store,
        on_storage_warning=on_storage_warning,
    )
    log.info("Scheduler started — daily summary at 10:00 AM IST, storage check every 6 h")

    # --- SMS ingestion callback ---
    def on_sms(sms: SMSMessage) -> None:
        txn = parser.parse(sms)
        store.save(sms, txn)
        agent.ingest_sms(sms, txn)
        if txn:
            log.info("SMS ingested: ₹%.2f %s from %s", txn.amount,
                     txn.transaction_type.value, sms.sender)
        else:
            log.info("SMS received from %s (no transaction parsed)", sms.sender)

    # --- start webhook server (blocking — keeps the process alive) ---
    app = create_app(on_sms=on_sms, secret=webhook_secret)
    log.info("Starting webhook server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
