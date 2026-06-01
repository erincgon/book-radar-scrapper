"""BookRadar ingestion pipeline orchestration."""

from __future__ import annotations

import logging
import time
from typing import Any

from config.settings import APP_CONFIG, OUTPUT_DIR
from services.ai_summary_service import AISummaryService
from services.deduplication_service import DeduplicationService
from services.firebase_service import FirebaseService
from services.normalization_service import NormalizationService
from utils.http_client import HTTPClient
from utils.json_export import write_json
from utils.metadata import update_meta_file
from utils.parallel import parallel_map

logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http_client = http_client or HTTPClient()
        self.normalizer = NormalizationService(self.http_client)
        self.deduper = DeduplicationService()
        self.ai_service = AISummaryService(self.http_client)
        self.firebase = FirebaseService()

    def run_feed(self, feed_name: str, scraper: Any) -> list[dict[str, Any]]:
        logger.info("Running feed '%s' scraper=%s", feed_name, getattr(scraper, "scraper_name", "unknown"))
        try:
            raw_items = scraper.scrape()
        except Exception as exc:
            logger.exception("Scraper failed feed=%s error=%s", feed_name, exc)
            raw_items = []

        normalized = self.normalizer.normalize_raw_items(raw_items, feed_name=feed_name)
        deduped = self.deduper.filter_duplicates(normalized, feed_name=feed_name)
        enriched = self.ai_service.enrich_batch(deduped)

        logger.info(
            "Feed '%s' prepared raw=%s normalized=%s deduped=%s",
            feed_name,
            len(raw_items),
            len(normalized),
            len(enriched),
        )
        return enriched[: APP_CONFIG.max_items_per_feed]

    def run_all(self, feed_map: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        started = time.time()
        self.deduper.begin_fresh_run()

        def _scrape_normalize(pair: tuple[str, Any]) -> tuple[str, list[dict[str, Any]]]:
            name, scraper = pair
            try:
                raw_items = scraper.scrape()
            except Exception as exc:
                logger.exception("Scraper failed feed=%s error=%s", name, exc)
                raw_items = []
            normalized = self.normalizer.normalize_raw_items(raw_items, feed_name=name)
            return name, normalized

        pairs = list(feed_map.items())
        if len(pairs) <= 1:
            staged = [_scrape_normalize(pairs[0])] if pairs else []
        else:
            staged = parallel_map(_scrape_normalize, pairs, max_workers=APP_CONFIG.feed_workers)

        final_feeds: dict[str, list[dict[str, Any]]] = {}
        for name, normalized in staged:
            deduped = self.deduper.filter_duplicates(normalized, feed_name=name)
            enriched = self.ai_service.enrich_batch(deduped)
            payload = enriched[: APP_CONFIG.max_items_per_feed]
            write_json(OUTPUT_DIR / f"{name}.json", payload)
            final_feeds[name] = payload
            logger.info("Feed '%s' ready items=%s", name, len(payload))

        update_meta_file(OUTPUT_DIR / "meta.json", final_feeds)
        self.deduper.save_cache()

        elapsed = round(time.time() - started, 2)
        logger.info("Completed all feeds in %s seconds", elapsed)
        return final_feeds

    def retry_failed_scrapes(self, feed_map: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        retried: dict[str, list[dict[str, Any]]] = {}
        for feed_name, scraper in feed_map.items():
            path = OUTPUT_DIR / f"{feed_name}.json"
            if path.exists() and path.stat().st_size > 4:
                continue
            logger.info("Retrying empty feed=%s", feed_name)
            retried[feed_name] = self.run_feed(feed_name, scraper)
            write_json(path, retried[feed_name])
        return retried

    def weekly_cleanup(self) -> None:
        removed = self.deduper.cleanup_stale()
        logger.info("Weekly cleanup complete dedupe_keys_removed=%s", removed)

    def duplicate_cleanup(self) -> None:
        self.deduper.save_cache()
        logger.info("Duplicate cleanup persisted cache keys=%s", len(self.deduper._seen_keys))
