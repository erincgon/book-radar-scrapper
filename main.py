"""BookRadar Engine entrypoint.

Migrated from StreamRadar `main.py` — movie/TV scrapers replaced with RSS-only
book/article ingestion. TMDB, platform scrapers, and Google News RSS removed.

Feed map: books, publishers, reviews (+ derived trending/new_releases/editor_picks).
"""

from __future__ import annotations

import argparse
import logging

from scrapers import RSSBooksScraper, RSSPublishersScraper, RSSReviewsScraper
from scheduler.runner import run_scheduler
from services.pipeline_service import PipelineService
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


def build_feed_map() -> dict:
    return {
        "books": RSSBooksScraper(),
        "publishers": RSSPublishersScraper(),
        "reviews": RSSReviewsScraper(),
    }


def _derive_curated_feeds(feeds: dict[str, list]) -> dict[str, list]:
    """Build mobile-facing collections from primary RSS feeds."""
    books = feeds.get("books", [])
    reviews = feeds.get("reviews", [])
    publishers = feeds.get("publishers", [])

    trending = sorted(
        books + reviews,
        key=lambda x: x.get("published_date", ""),
        reverse=True,
    )[:20]

    new_releases = sorted(
        publishers + books,
        key=lambda x: x.get("published_date", ""),
        reverse=True,
    )[:20]

    editor_picks = reviews[:15] if reviews else books[:15]

    return {
        **feeds,
        "trending": trending,
        "new_releases": new_releases,
        "editor_picks": editor_picks,
    }


def run_all() -> None:
    pipeline = PipelineService()
    feed_map = build_feed_map()
    primary = pipeline.run_all(feed_map)

    curated = _derive_curated_feeds(primary)
    from config.settings import OUTPUT_DIR
    from utils.json_export import write_json
    from utils.metadata import update_meta_file

    for name, payload in curated.items():
        if name not in primary:
            write_json(OUTPUT_DIR / f"{name}.json", payload)

    update_meta_file(OUTPUT_DIR / "meta.json", curated)

    try:
        pipeline.firebase.upload_feed_collections(curated)
    except Exception as exc:
        logger.exception("Firebase upload for curated feeds failed: %s", exc)


def run_once() -> None:
    setup_logging()
    run_all()


def main() -> None:
    parser = argparse.ArgumentParser(description="BookRadar Engine — RSS-first book ingestion")
    parser.add_argument(
        "--mode",
        choices=("once", "scheduler"),
        default="once",
        help="Run once or start background scheduler",
    )
    args = parser.parse_args()

    if args.mode == "scheduler":
        pipeline = PipelineService()
        feed_map = build_feed_map()
        run_scheduler(
            run_all=run_all,
            retry_failed=lambda: pipeline.retry_failed_scrapes(feed_map),
            weekly_cleanup=pipeline.weekly_cleanup,
            duplicate_cleanup=pipeline.duplicate_cleanup,
        )
    else:
        run_once()


if __name__ == "__main__":
    main()
