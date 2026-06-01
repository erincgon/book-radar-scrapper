"""NYT Books, literary blogs, and general book RSS feeds."""

from __future__ import annotations

from config.settings import BOOK_FEEDS
from scrapers.base_scraper import RSSFeedScraper
from utils.http_client import HTTPClient


class RSSBooksScraper(RSSFeedScraper):
    scraper_name = "rss_books"

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        super().__init__(name=self.scraper_name, feeds=BOOK_FEEDS, http_client=http_client)
