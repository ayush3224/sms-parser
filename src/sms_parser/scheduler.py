"""APScheduler-based scheduler for the daily 10 AM IST spend summary."""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from .agent import SMSSpendAgent

IST = pytz.timezone("Asia/Kolkata")
log = logging.getLogger(__name__)


def _run_daily_summary(agent: "SMSSpendAgent", on_summary=None) -> None:
    """Called by the scheduler at 10 AM IST. Generates yesterday's spend summary."""
    yesterday = (datetime.now(tz=IST) - timedelta(days=1)).date()
    log.info("Generating daily spend summary for %s", yesterday)
    try:
        summary = agent.get_daily_spend_summary(yesterday)
        if on_summary:
            on_summary(summary, yesterday)
        else:
            print(f"\n[Daily Summary — {yesterday}]\n{summary}\n")
    except Exception:
        log.exception("Failed to generate daily spend summary")


def start_daily_scheduler(
    agent: "SMSSpendAgent",
    on_summary=None,
) -> BackgroundScheduler:
    """
    Start a background scheduler that fires at 10:00 AM IST every day.

    Args:
        agent: The SMSSpendAgent instance to use.
        on_summary: Optional callback(summary: str, date: date) called with the result.
                    If None, the summary is printed to stdout.

    Returns:
        The started BackgroundScheduler (call .shutdown() to stop it).
    """
    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(
        _run_daily_summary,
        trigger=CronTrigger(hour=10, minute=0, second=0, timezone=IST),
        args=[agent, on_summary],
        id="daily_spend_summary",
        name="Daily Spend Summary (10 AM IST)",
        replace_existing=True,
    )
    scheduler.start()
    log.info("Daily spend summary scheduler started — fires at 10:00 AM IST")
    return scheduler
