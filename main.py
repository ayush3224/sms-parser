#!/usr/bin/env python3
"""
SMS Spend Agent
===============
• Provides a daily spend summary at 10 AM IST (background scheduler).
• Accepts natural-language queries about your business SMS / transactions.

Usage:
    python main.py                        # interactive mode (default data)
    python main.py --data path/to/sms     # custom SMS file (.json or Android .xml)
    python main.py --summary              # print yesterday's summary and exit
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
from src.sms_parser.scheduler import start_daily_scheduler
from src.sms_parser.sms_parser import SMSParser
from src.sms_parser.sms_reader import SMSReader

IST = pytz.timezone("Asia/Kolkata")
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_data(data_path: str):
    reader = SMSReader()
    parser = SMSParser()

    console.print(f"[dim]Loading SMS from {data_path} …[/dim]")
    sms_messages = reader.load(data_path)
    console.print(f"[green]✓ Loaded {len(sms_messages)} SMS messages[/green]")

    transactions = []
    for sms in sms_messages:
        txn = parser.parse(sms)
        if txn:
            transactions.append(txn)
    console.print(f"[green]✓ Parsed {len(transactions)} financial transactions[/green]\n")

    return sms_messages, transactions


def _on_scheduled_summary(summary: str, for_date: date) -> None:
    """Callback invoked by the background scheduler at 10 AM IST."""
    console.print(Rule(f"[bold yellow]Daily Spend Summary — {for_date}[/bold yellow]"))
    console.print(Panel(summary, border_style="yellow"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="SMS Spend Agent powered by Claude")
    ap.add_argument(
        "--data",
        default=os.getenv("SMS_DATA_PATH", "data/sample_sms.json"),
        help="Path to SMS data file (.json or Android backup .xml)",
    )
    ap.add_argument(
        "--summary",
        action="store_true",
        help="Print yesterday's spend summary and exit (no interactive mode)",
    )
    ap.add_argument(
        "--date",
        help="Date for summary in YYYY-MM-DD format (used with --summary; defaults to yesterday)",
    )
    ap.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))

    # Banner
    console.print(
        Panel.fit(
            "[bold blue]SMS Spend Agent[/bold blue]\n"
            "[dim]Powered by Claude Opus 4.6[/dim]",
        )
    )

    # API key check
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print(
            "[red]Error:[/red] ANTHROPIC_API_KEY environment variable is not set.\n"
            "Copy [bold].env.example[/bold] to [bold].env[/bold] and add your key."
        )
        return 1

    # Load data
    try:
        sms_messages, transactions = _load_data(args.data)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    agent = SMSSpendAgent(sms_messages, transactions, api_key)

    # ------------------------------------------------------------------
    # One-shot summary mode
    # ------------------------------------------------------------------
    if args.summary:
        if args.date:
            try:
                target_date = date.fromisoformat(args.date)
            except ValueError:
                console.print(f"[red]Invalid date format:[/red] {args.date}. Use YYYY-MM-DD.")
                return 1
        else:
            target_date = (datetime.now(tz=IST) - timedelta(days=1)).date()

        console.print(f"Generating spend summary for [bold]{target_date}[/bold] …\n")
        summary = agent.get_daily_spend_summary(target_date)
        console.print(Panel(summary, title=f"Spend Summary — {target_date}", border_style="green"))
        return 0

    # ------------------------------------------------------------------
    # Interactive mode
    # ------------------------------------------------------------------

    # Start background scheduler (10 AM IST daily)
    scheduler = start_daily_scheduler(agent, on_summary=_on_scheduled_summary)
    console.print("[dim]Daily summary scheduler started — fires at 10:00 AM IST[/dim]")

    console.print(
        "\n[bold]Ask me anything about your spending![/bold]  "
        "Type [bold cyan]exit[/bold cyan] to quit, [bold cyan]reset[/bold cyan] to clear history.\n"
    )
    console.print(
        "[dim]Examples:[/dim]\n"
        "  • What did I spend yesterday?\n"
        "  • Show me all UPI transactions this week\n"
        "  • Which merchant did I spend the most on in April?\n"
        "  • Did I get any credits this week?\n"
        "  • How much did I spend on food delivery?\n"
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

            if query.lower() in ("exit", "quit", "q", "bye"):
                break

            if query.lower() in ("reset", "clear"):
                agent.reset_conversation()
                console.print("[dim]Conversation history cleared.[/dim]")
                continue

            with console.status("[dim]Thinking…[/dim]"):
                try:
                    response = agent.answer_query(query)
                except Exception as exc:
                    console.print(f"[red]Error:[/red] {exc}")
                    continue

            console.print(
                Panel(response, title="[bold green]Agent[/bold green]", border_style="green")
            )
    finally:
        scheduler.shutdown(wait=False)
        console.print("\n[dim]Scheduler stopped. Goodbye![/dim]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
