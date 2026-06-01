"""BookRadar Engine entrypoint."""

from __future__ import annotations

import argparse
import logging
import time

from pathlib import Path

from scrapers import RSSBooksScraper, RSSPublishersScraper, RSSReviewsScraper
from services.pipeline_service import PipelineService
from utils.http_client import HTTPClient
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


def build_feed_map(http_client: HTTPClient) -> dict:
    return {
        "books": RSSBooksScraper(http_client=http_client),
        "publishers": RSSPublishersScraper(http_client=http_client),
        "reviews": RSSReviewsScraper(http_client=http_client),
    }


def _derive_curated_feeds(feeds: dict[str, list]) -> dict[str, list]:
    from services.deduplication_service import normalized_url_signature

    books = feeds.get("books", [])
    reviews = feeds.get("reviews", [])
    publishers = feeds.get("publishers", [])

    # Editor picks first — must not share seen_urls with trending (reviews would be empty)
    editor_source = reviews if reviews else books
    editor_picks = sorted(
        editor_source,
        key=lambda x: x.get("published_date", ""),
        reverse=True,
    )[:15]

    seen_urls: set[str] = set()
    for item in editor_picks:
        url = normalized_url_signature(item.get("article_url"))
        if url:
            seen_urls.add(url)

    trending_pool = _dedupe_curated_list(books + reviews, seen_urls)
    trending = sorted(
        trending_pool,
        key=lambda x: x.get("published_date", ""),
        reverse=True,
    )[:20]

    new_pool = _dedupe_curated_list(publishers + books, seen_urls)
    new_releases = sorted(
        new_pool,
        key=lambda x: x.get("published_date", ""),
        reverse=True,
    )[:20]

    return {
        **feeds,
        "trending": trending,
        "new_releases": new_releases,
        "editor_picks": editor_picks,
    }


def _dedupe_curated_list(items: list, seen_urls: set[str]) -> list:
    from services.deduplication_service import normalized_url_signature

    out: list = []
    for item in items:
        url = normalized_url_signature(item.get("article_url"))
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        out.append(item)
    return out


def run_all(*, fresh: bool = False) -> None:
    started = time.time()
    if fresh:
        cache_path = Path(__file__).resolve().parent / "cache" / "seen_entries.json"
        if cache_path.exists():
            cache_path.unlink()
            logger.info("Cleared dedupe cache (--fresh)")

    http_client = HTTPClient()
    pipeline = PipelineService(http_client=http_client)
    feed_map = build_feed_map(http_client)

    primary = pipeline.run_all(feed_map)
    curated = _derive_curated_feeds(primary)

    from config.settings import OUTPUT_DIR
    from utils.json_export import write_json
    from utils.metadata import update_meta_file

    for name, payload in curated.items():
        write_json(OUTPUT_DIR / f"{name}.json", payload)

    logger.info(
        "Curated feeds: trending=%s new_releases=%s editor_picks=%s",
        len(curated.get("trending", [])),
        len(curated.get("new_releases", [])),
        len(curated.get("editor_picks", [])),
    )

    update_meta_file(OUTPUT_DIR / "meta.json", curated)

    try:
        pipeline.firebase.upload_feed_collections(curated)
    except Exception as exc:
        logger.exception("Firebase upload failed: %s", exc)

    elapsed = round(time.time() - started, 2)
    logger.info("BookRadar run finished in %s seconds", elapsed)


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
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Clear dedupe cache before scrape (same as deleting cache/seen_entries.json)",
    )
    args = parser.parse_args()

    if args.mode == "scheduler":
        try:
            from scheduler.runner import run_scheduler
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Scheduler dependencies missing. Run:\n"
                "  python3 -m venv venv && source venv/bin/activate\n"
                "  pip install -r requirements.txt"
            ) from exc
        http_client = HTTPClient()
        pipeline = PipelineService(http_client=http_client)
        feed_map = build_feed_map(http_client)
        run_scheduler(
            run_all=run_all,
            retry_failed=lambda: pipeline.retry_failed_scrapes(feed_map),
            weekly_cleanup=pipeline.weekly_cleanup,
            duplicate_cleanup=pipeline.duplicate_cleanup,
        )
    else:
        setup_logging()
        run_all(fresh=args.fresh)


if __name__ == "__main__":
    main()
