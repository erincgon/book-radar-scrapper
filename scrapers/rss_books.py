"""NYT Books, literary blogs, and general book RSS feeds."""

from __future__ import annotations

from config.settings import BOOK_FEEDS
from scrapers.base_scraper import RSSFeedScraper


class RSSBooksScraper(RSSFeedScraper):
    scraper_name = "rss_books"

    def __init__(self) -> None:
        super().__init__(name=self.scraper_name, feeds=BOOK_FEEDS)
