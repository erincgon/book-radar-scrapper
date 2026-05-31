"""BookRadar scraper registry."""

from scrapers.rss_books import RSSBooksScraper
from scrapers.rss_publishers import RSSPublishersScraper
from scrapers.rss_reviews import RSSReviewsScraper

__all__ = [
    "RSSBooksScraper",
    "RSSPublishersScraper",
    "RSSReviewsScraper",
]
