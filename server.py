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


def _send_email_summary(email_data, for_date) -> None:
    """Send daily summary as an HTML email via Gmail SMTP. Skips silently if not configured."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from src.sms_parser.email_template import render_html_email

    sender   = os.getenv("EMAIL_SENDER")    # your Gmail address
    password = os.getenv("EMAIL_PASSWORD")  # Gmail App Password
    receiver = os.getenv("EMAIL_RECEIVER")  # where to send (can be same as sender)

    if not (sender and password and receiver):
        return  # email not configured — skip silently

    subject  = f"Daily Spend Summary — {for_date}"
    html_body = render_html_email(email_data)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(html_body, "html", "utf-8"))

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

    # --- daily summary callback: build HTML email and send it ---
    def on_summary(for_date) -> None:
        log.info("Daily summary job fired for %s", for_date)
        try:
            from src.sms_parser.email_template import build_email_data
            receiver   = os.getenv("EMAIL_RECEIVER", "")
            fresh_txns = store.load_all_transactions()
            log.info("Loaded %d transactions for email", len(fresh_txns))
            email_data = build_email_data(fresh_txns, for_date, receiver_email=receiver, api_key=api_key)
            log.info("Email data built: ₹%.0f across %d txns", email_data.total_debit, email_data.txn_count)
            email_data.one_line_summary = agent.get_one_line_summary(email_data)
            _send_email_summary(email_data, for_date)
            log.info("Daily summary for %s completed successfully", for_date)
        except Exception:
            log.exception("CRITICAL: on_summary failed for %s — see traceback above", for_date)

    def on_storage_check() -> None:
        try:
            cleaned, msg = store.cleanup_if_needed()
            if cleaned:
                log.warning("Storage cleanup: %s", msg)
            else:
                log.debug("Storage check: %s", msg)
        except Exception:
            log.exception("Storage check failed")

    # --- SMS ingestion callback ---
    def on_sms(sms: SMSMessage) -> None:
        txn = parser.parse(sms, on_unknown_template=store.save_unknown_template)
        store.save(sms, txn)
        agent.ingest_sms(sms, txn)
        if txn:
            log.info("SMS ingested: ₹%.2f %s from %s", txn.amount,
                     txn.transaction_type.value, sms.sender)
        else:
            log.info("SMS received from %s (no transaction parsed)", sms.sender)

    # --- start webhook server (blocking — scheduling runs inside uvicorn's event loop) ---
    app = create_app(
        on_sms=on_sms,
        secret=webhook_secret,
        on_summary=on_summary,
        on_storage_check=on_storage_check,
    )
    log.info("Starting webhook server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
