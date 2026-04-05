#!/usr/bin/env python3
"""
SMS Spend Agent
===============
Reads live SMS from your Android phone via a webhook, stores them in Supabase,
and answers natural-language spending queries powered by Claude Opus 4.6.

Daily spend summary fires automatically at 10 AM IST.

Usage
-----
  python main.py                          # interactive mode
  python main.py --summary                # print yesterday's summary and exit
  python main.py --summary --date DATE    # summary for a specific YYYY-MM-DD
  python main.py --port 9000              # change webhook port (default 8000)
  python main.py --import-file sms.json  # one-time bulk import from a file
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

import pytz
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule

load_dotenv()

from src.sms_parser.agent import SMSSpendAgent
from src.sms_parser.models import SMSMessage, Transaction
from src.sms_parser.scheduler import start_daily_scheduler
from src.sms_parser.sms_parser import SMSParser
from src.sms_parser.sms_reader import SMSReader

IST = pytz.timezone("Asia/Kolkata")
console = Console()


# ---------------------------------------------------------------------------
# Optional Supabase helpers (only imported when credentials are present)
# ---------------------------------------------------------------------------

def _try_import_supabase():
    """Return SupabaseStore class or None if supabase-py is not installed."""
    try:
        from src.sms_parser.supabase_store import SupabaseStore
        return SupabaseStore
    except ImportError:
        return None


def _try_import_webhook():
    try:
        from src.sms_parser.webhook_server import WebhookServer
        return WebhookServer
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Callbacks for the scheduler
# ---------------------------------------------------------------------------

def _on_summary(summary: str, for_date: date) -> None:
    console.print(Rule(f"[bold yellow]Daily Spend Summary — {for_date}[/bold yellow]"))
    console.print(Panel(summary, border_style="yellow"))


def _on_storage_warning(message: str) -> None:
    console.print(f"\n[bold yellow]⚠ Storage cleanup:[/bold yellow] {message}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # If running in Railway/cloud, use server mode
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_NAME"):
        import importlib
        server_mod = importlib.import_module("server")
        server_mod.main()
        return 0

    ap = argparse.ArgumentParser(description="SMS Spend Agent — powered by Claude")
    ap.add_argument("--summary", action="store_true",
                    help="Print yesterday's summary and exit")
    ap.add_argument("--date", help="Date for --summary in YYYY-MM-DD format")
    ap.add_argument("--import-file", metavar="PATH",
                    help="Bulk-import SMS from a JSON or Android XML file into Supabase, then exit")
    ap.add_argument("--port", type=int, default=int(os.getenv("WEBHOOK_PORT", "8000")),
                    help="Webhook server port (default 8000)")
    ap.add_argument("--no-webhook", action="store_true",
                    help="Disable the webhook server (interactive / summary only)")
    ap.add_argument("--log-level", default="WARNING",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))

    console.print(Panel.fit(
        "[bold blue]SMS Spend Agent[/bold blue]\n[dim]Powered by Claude Opus 4.6[/dim]"
    ))

    # --- API key ---
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is not set in .env")
        return 1

    # --- Supabase (optional) ---
    sb_url = os.getenv("SUPABASE_URL", "")
    sb_key = os.getenv("SUPABASE_KEY", "")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "")

    store = None
    SupabaseStore = _try_import_supabase()
    if SupabaseStore and sb_url and sb_key:
        try:
            store = SupabaseStore(sb_url, sb_key)
            console.print("[green]✓ Connected to Supabase[/green]")
        except Exception as exc:
            console.print(f"[yellow]Warning:[/yellow] Could not connect to Supabase — {exc}")
            store = None
    else:
        if not sb_url or not sb_key:
            console.print("[dim]Supabase not configured — running in file-only mode[/dim]")

    # ---------------------------------------------------------------------------
    # BULK IMPORT mode
    # ---------------------------------------------------------------------------
    if args.import_file:
        if not store:
            console.print("[red]--import-file requires Supabase credentials in .env[/red]")
            return 1
        _bulk_import(args.import_file, store)
        return 0

    # ---------------------------------------------------------------------------
    # Load SMS + transactions
    # ---------------------------------------------------------------------------
    parser = SMSParser()
    sms_messages = []
    transactions = []

    if store:
        console.print("[dim]Loading data from Supabase …[/dim]")
        sms_messages  = store.load_all_sms()
        transactions  = store.load_all_transactions()
        console.print(
            f"[green]✓ {len(sms_messages)} SMS / {len(transactions)} transactions from Supabase[/green]"
        )
    else:
        # Fall back to sample data file
        data_path = os.getenv("SMS_DATA_PATH", "data/sample_sms.json")
        console.print(f"[dim]Loading SMS from {data_path} …[/dim]")
        try:
            sms_messages = SMSReader().load(data_path)
        except FileNotFoundError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            return 1
        transactions = [t for t in (parser.parse(s) for s in sms_messages) if t]
        console.print(
            f"[green]✓ {len(sms_messages)} SMS / {len(transactions)} transactions from file[/green]"
        )

    agent = SMSSpendAgent(sms_messages, transactions, api_key)

    # ---------------------------------------------------------------------------
    # SUMMARY mode (one-shot, no interactive loop)
    # ---------------------------------------------------------------------------
    if args.summary:
        if args.date:
            try:
                target = date.fromisoformat(args.date)
            except ValueError:
                console.print(f"[red]Bad date format:[/red] {args.date}  (use YYYY-MM-DD)")
                return 1
        else:
            target = (datetime.now(tz=IST) - timedelta(days=1)).date()

        console.print(f"\nGenerating summary for [bold]{target}[/bold] …\n")
        summary = agent.get_daily_spend_summary(target)
        console.print(Panel(summary, title=f"Spend Summary — {target}", border_style="green"))
        return 0

    # ---------------------------------------------------------------------------
    # Webhook server (live SMS ingestion)
    # ---------------------------------------------------------------------------
    webhook_server = None
    if store and not args.no_webhook:
        WebhookServer = _try_import_webhook()
        if WebhookServer:
            def _on_sms(sms: SMSMessage) -> None:
                txn = parser.parse(sms)
                store.save(sms, txn)            # persist to Supabase
                agent.ingest_sms(sms, txn)      # update in-memory store
                status = f"₹{txn.amount:,.2f} {txn.transaction_type.value}" if txn else "no transaction parsed"
                console.print(f"\n[dim]New SMS from {sms.sender} — {status}[/dim]")

            webhook_server = WebhookServer(
                on_sms=_on_sms,
                port=args.port,
                secret=webhook_secret or None,
            )
            webhook_server.start()
            console.print(
                f"[green]✓ Webhook server listening on port {args.port}[/green]\n"
                f"  [dim]Android app → POST http://<your-ip>:{args.port}/webhook/sms[/dim]"
            )
        else:
            console.print("[dim]fastapi/uvicorn not installed — webhook disabled[/dim]")

    # ---------------------------------------------------------------------------
    # Scheduler
    # ---------------------------------------------------------------------------
    scheduler = start_daily_scheduler(
        agent=agent,
        on_summary=_on_summary,
        store=store,
        on_storage_warning=_on_storage_warning,
    )
    console.print("[dim]Scheduler started — daily summary at 10:00 AM IST"
                  + (", storage check every 6 h" if store else "") + "[/dim]")

    # ---------------------------------------------------------------------------
    # Interactive loop
    # ---------------------------------------------------------------------------
    console.print(
        "\n[bold]Ask me about your spending![/bold]  "
        "Type [cyan]exit[/cyan] to quit, [cyan]reset[/cyan] to clear history.\n"
    )
    console.print(
        "[dim]Try:[/dim]\n"
        "  • What did I spend yesterday?\n"
        "  • Show all UPI transactions this week\n"
        "  • How much did I spend on food delivery?\n"
        "  • Which bank had the most transactions?\n"
    )

    try:
        while True:
            try:
                query = Prompt.ask("\n[bold cyan]You[/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                break

            query = query.strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                break
            if query.lower() in ("reset", "clear"):
                agent.reset_conversation()
                console.print("[dim]Conversation cleared.[/dim]")
                continue

            with console.status("[dim]Thinking …[/dim]"):
                try:
                    response = agent.answer_query(query)
                except Exception as exc:
                    console.print(f"[red]Error:[/red] {exc}")
                    continue

            console.print(Panel(response, title="[bold green]Agent[/bold green]", border_style="green"))

    finally:
        scheduler.shutdown(wait=False)
        if webhook_server:
            webhook_server.stop()
        console.print("\n[dim]Goodbye![/dim]")

    return 0


# ---------------------------------------------------------------------------
# Bulk import helper
# ---------------------------------------------------------------------------

def _bulk_import(path: str, store) -> None:
    """Import all SMS from a file into Supabase (skips duplicates)."""
    parser = SMSParser()
    console.print(f"[dim]Importing from {path} …[/dim]")
    try:
        sms_list = SMSReader().load(path)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    saved = 0
    for sms in sms_list:
        txn = parser.parse(sms)
        try:
            store.save(sms, txn)
            saved += 1
        except Exception as exc:
            console.print(f"[yellow]Skip {sms.id}:[/yellow] {exc}")

    console.print(f"[green]✓ Imported {saved}/{len(sms_list)} SMS into Supabase[/green]")


if __name__ == "__main__":
    sys.exit(main())
