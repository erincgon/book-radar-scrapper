"""Publisher announcement and literary magazine RSS feeds."""

from __future__ import annotations

from config.settings import PUBLISHER_FEEDS
from scrapers.base_scraper import RSSFeedScraper


class RSSPublishersScraper(RSSFeedScraper):
    scraper_name = "rss_publishers"

    def __init__(self) -> None:
        super().__init__(name=self.scraper_name, feeds=PUBLISHER_FEEDS)
