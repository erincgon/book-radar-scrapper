"""Book review and literary criticism RSS feeds."""

from __future__ import annotations

from config.settings import REVIEW_FEEDS
from scrapers.base_scraper import RSSFeedScraper


class RSSReviewsScraper(RSSFeedScraper):
    scraper_name = "rss_reviews"

    def __init__(self) -> None:
        super().__init__(name=self.scraper_name, feeds=REVIEW_FEEDS)
