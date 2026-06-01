"""Base scraper abstraction for BookRadar Engine."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from config.settings import APP_CONFIG, RSSFeedSource
from utils.http_client import HTTPClient
from utils.parallel import parallel_map
from utils.rss_parser import RSSParser

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    scraper_name = "base"

    @abstractmethod
    def scrape(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class RSSFeedScraper(BaseScraper):
    """Shared RSS ingestion — feeds fetched in parallel."""

    scraper_name = "rss_feed"

    def __init__(
        self,
        *,
        name: str,
        feeds: list[RSSFeedSource],
        http_client: HTTPClient | None = None,
    ) -> None:
        self.scraper_name = name
        self.feeds = feeds
        self.http_client = http_client or HTTPClient()
        self.parser = RSSParser(http_client=self.http_client)

    def _fetch_one(self, feed: RSSFeedSource) -> tuple[str, list[dict[str, Any]]]:
        try:
            items = self.parser.fetch_feed(feed)
            return feed.name, items
        except Exception as exc:
            logger.warning("Feed failed scraper=%s feed=%s error=%s", self.scraper_name, feed.name, exc)
            return feed.name, []

    def scrape(self) -> list[dict[str, Any]]:
        if not self.feeds:
            return []

        if len(self.feeds) == 1:
            _, items = self._fetch_one(self.feeds[0])
            logger.info("Scraper %s produced %s raw items", self.scraper_name, len(items))
            return items

        results = parallel_map(
            self._fetch_one,
            self.feeds,
            max_workers=APP_CONFIG.rss_fetch_workers,
        )
        aggregate: list[dict[str, Any]] = []
        failed: list[str] = []
        for name, items in results:
            if items:
                aggregate.extend(items)
            else:
                failed.append(name)

        if failed:
            logger.warning("Scraper %s failed feeds: %s", self.scraper_name, ", ".join(failed))
        logger.info("Scraper %s produced %s raw items", self.scraper_name, len(aggregate))
        return aggregate
