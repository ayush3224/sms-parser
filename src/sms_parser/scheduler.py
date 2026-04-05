"""
APScheduler jobs:
  1. Daily spend summary        — 10:00 AM IST
  2. Storage usage check        — every 6 hours
"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from .agent import SMSSpendAgent
    from .supabase_store import SupabaseStore

IST = pytz.timezone("Asia/Kolkata")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job: daily spend summary
# ---------------------------------------------------------------------------

def _run_daily_summary(
    agent: "SMSSpendAgent",
    on_summary: Optional[Callable] = None,
) -> None:
    yesterday = (datetime.now(tz=IST) - timedelta(days=1)).date()
    log.info("Generating daily spend summary for %s", yesterday)
    try:
        summary = agent.get_daily_spend_summary(yesterday)
        if on_summary:
            on_summary(summary, yesterday)
        else:
            print(f"\n[Daily Summary — {yesterday}]\n{summary}\n")
    except Exception:
        log.exception("Daily spend summary failed")


# ---------------------------------------------------------------------------
# Job: Supabase storage check & auto-cleanup
# ---------------------------------------------------------------------------

def _check_storage(
    store: "SupabaseStore",
    on_warning: Optional[Callable[[str], None]] = None,
) -> None:
    log.debug("Checking Supabase storage usage …")
    try:
        cleaned, msg = store.cleanup_if_needed()
        if cleaned:
            log.warning("Storage cleanup triggered: %s", msg)
            if on_warning:
                on_warning(msg)
        else:
            log.debug(msg)
    except Exception:
        log.exception("Storage check failed")


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def start_daily_scheduler(
    agent: "SMSSpendAgent",
    on_summary: Optional[Callable] = None,
    store: Optional["SupabaseStore"] = None,
    on_storage_warning: Optional[Callable[[str], None]] = None,
) -> BackgroundScheduler:
    """
    Start the background scheduler.

    Args:
        agent:              The SMSSpendAgent to use for daily summaries.
        on_summary:         Called with (summary_text, date) at 10 AM IST.
                            Defaults to printing to stdout.
        store:              SupabaseStore instance; if provided, enables the
                            6-hourly storage-usage check.
        on_storage_warning: Called with a message string when cleanup runs.

    Returns:
        The started BackgroundScheduler (call .shutdown() to stop it).
    """
    scheduler = BackgroundScheduler(timezone=IST)

    # 1. Daily summary — 10:00 AM IST
    scheduler.add_job(
        _run_daily_summary,
        trigger=CronTrigger(hour=10, minute=0, second=0, timezone=IST),
        args=[agent, on_summary],
        id="daily_spend_summary",
        name="Daily Spend Summary (10 AM IST)",
        replace_existing=True,
    )

    # 2. Storage check — every 6 hours (only when Supabase is configured)
    if store is not None:
        scheduler.add_job(
            _check_storage,
            trigger=IntervalTrigger(hours=6, timezone=IST),
            args=[store, on_storage_warning],
            id="storage_check",
            name="Supabase Storage Check (every 6h)",
            replace_existing=True,
        )

    scheduler.start()
    log.info("Scheduler started — daily summary at 10 AM IST%s",
             ", storage check every 6h" if store else "")
    return scheduler
