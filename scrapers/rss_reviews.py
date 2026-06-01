"""Book review and literary criticism RSS feeds."""

from __future__ import annotations

from config.settings import REVIEW_FEEDS
from scrapers.base_scraper import RSSFeedScraper
from utils.http_client import HTTPClient


class RSSReviewsScraper(RSSFeedScraper):
    scraper_name = "rss_reviews"

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        super().__init__(name=self.scraper_name, feeds=REVIEW_FEEDS, http_client=http_client)
