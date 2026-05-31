"""Base scraper abstraction for BookRadar Engine.

Replaces StreamRadar `scrapers/base.py` — movie ContentItem removed.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from config.settings import RSSFeedSource
from utils.http_client import HTTPClient
from utils.rss_parser import RSSParser

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Each scraper returns a list of normalized raw book/article dicts."""

    scraper_name = "base"

    @abstractmethod
    def scrape(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class RSSFeedScraper(BaseScraper):
    """Shared RSS ingestion for book, publisher, and review feeds."""

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
        self.parser = RSSParser(http_client=http_client)

    def scrape(self) -> list[dict[str, Any]]:
        aggregate: list[dict[str, Any]] = []
        failed_feeds: list[str] = []

        for feed in self.feeds:
            try:
                items = self.parser.fetch_feed(feed)
                if not items:
                    failed_feeds.append(feed.name)
                aggregate.extend(items)
            except Exception as exc:
                logger.exception(
                    "Isolated feed failure scraper=%s feed=%s error=%s",
                    self.scraper_name,
                    feed.name,
                    exc,
                )
                failed_feeds.append(feed.name)

        if failed_feeds:
            logger.warning(
                "Scraper %s completed with failed feeds: %s",
                self.scraper_name,
                ", ".join(failed_feeds),
            )
        logger.info("Scraper %s produced %s raw items", self.scraper_name, len(aggregate))
        return aggregate
