"""BookRadar Engine scheduler.

Preserves StreamRadar cron-style orchestration with hourly RSS refresh,
failed scrape retry, weekly cleanup, and duplicate cleanup jobs.
"""

from __future__ import annotations

import logging
import signal
import sys
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import SCHEDULER_CONFIG
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


def create_scheduler(
    *,
    run_all: Callable[[], None],
    retry_failed: Callable[[], None],
    weekly_cleanup: Callable[[], None],
    duplicate_cleanup: Callable[[], None],
) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        run_all,
        trigger=IntervalTrigger(hours=SCHEDULER_CONFIG.rss_refresh_hours),
        id="hourly_rss_refresh",
        name="Hourly RSS refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        retry_failed,
        trigger=IntervalTrigger(minutes=SCHEDULER_CONFIG.retry_failed_minutes),
        id="failed_scrape_retry",
        name="Failed scrape retry",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        weekly_cleanup,
        trigger=CronTrigger(
            day_of_week=SCHEDULER_CONFIG.weekly_cleanup_day,
            hour=SCHEDULER_CONFIG.weekly_cleanup_hour,
            minute=0,
        ),
        id="weekly_cleanup",
        name="Weekly cleanup",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        duplicate_cleanup,
        trigger=IntervalTrigger(hours=SCHEDULER_CONFIG.duplicate_cleanup_hours),
        id="duplicate_cleanup",
        name="Duplicate cleanup",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    return scheduler


def run_scheduler(
    *,
    run_all: Callable[[], None],
    retry_failed: Callable[[], None],
    weekly_cleanup: Callable[[], None],
    duplicate_cleanup: Callable[[], None],
) -> None:
    setup_logging()
    scheduler = create_scheduler(
        run_all=run_all,
        retry_failed=retry_failed,
        weekly_cleanup=weekly_cleanup,
        duplicate_cleanup=duplicate_cleanup,
    )

    def _shutdown(signum: int, _frame: object) -> None:
        logger.info("Shutdown signal received signum=%s", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("BookRadar scheduler started")
    run_all()
    scheduler.start()
