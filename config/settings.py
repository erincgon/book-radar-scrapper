"""BookRadar Engine configuration.

Migrated from StreamRadar `config.py` — paths and runtime knobs preserved;
movie/platform feeds replaced with book RSS feed registry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
CACHE_DIR = BASE_DIR / "cache"


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration values used across modules."""

    request_timeout_seconds: int = 12
    request_retries: int = 2
    backoff_factor: float = 0.5
    # RSS feeds: minimal delay (parallel fetch handles politeness)
    rss_rate_limit_seconds: float = 0.05
    # Optional article-page fetches for missing thumbnails
    min_rate_limit_seconds: float = 0.1
    max_rate_limit_seconds: float = 0.25
    max_items_per_feed: int = 30
    raw_scan_multiplier: float = 1.5
    description_max_chars: int = 1200
    ai_summary_max_words: int = 120
    article_enrichment_max: int = field(
        default_factory=lambda: int(os.getenv("ARTICLE_ENRICHMENT_MAX", "6"))
    )
    article_fetch_workers: int = field(
        default_factory=lambda: int(os.getenv("ARTICLE_FETCH_WORKERS", "8"))
    )
    rss_fetch_workers: int = field(default_factory=lambda: int(os.getenv("RSS_FETCH_WORKERS", "6")))
    feed_workers: int = field(default_factory=lambda: int(os.getenv("FEED_WORKERS", "3")))


APP_CONFIG = AppConfig()


@dataclass(frozen=True)
class RSSFeedSource:
    """Single RSS feed definition."""

    url: str
    name: str
    category: str
    publisher: str = ""
    language: str = "English"
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()


def _env_feeds(prefix: str, defaults: list[RSSFeedSource]) -> list[RSSFeedSource]:
    """Optional comma-separated RSS URLs from env override defaults."""
    raw = os.getenv(prefix, "").strip()
    if not raw:
        return defaults
    feeds: list[RSSFeedSource] = []
    for idx, url in enumerate(raw.split(",")):
        url = url.strip()
        if url:
            feeds.append(
                RSSFeedSource(
                    url=url,
                    name=f"custom_{idx + 1}",
                    category="general",
                )
            )
    return feeds or defaults


# Default RSS sources — override via BOOK_RSS_FEEDS, PUBLISHER_RSS_FEEDS, REVIEW_RSS_FEEDS
DEFAULT_BOOK_FEEDS: list[RSSFeedSource] = [
    RSSFeedSource(
        url="https://rss.nytimes.com/services/xml/rss/nyt/Books.xml",
        name="nyt_books",
        category="books",
        publisher="The New York Times",
    ),
    RSSFeedSource(
        url="https://www.theguardian.com/books/rss",
        name="guardian_books",
        category="books",
        publisher="The Guardian",
    ),
    RSSFeedSource(
        url="https://feeds.feedburner.com/TheBookSmugglers",
        name="book_smugglers",
        category="books",
        publisher="The Book Smugglers",
        exclude_keywords=(
            "trailer",
            "spinoff",
            "x-men",
            "streaming",
            "tiny desk",
            "concert",
            "tv ",
            "film ",
            "movie ",
            "box office",
        ),
    ),
    RSSFeedSource(
        url="https://www.kirkusreviews.com/feeds/rss/",
        name="kirkus",
        category="books",
        publisher="Kirkus Reviews",
    ),
]

DEFAULT_PUBLISHER_FEEDS: list[RSSFeedSource] = [
    RSSFeedSource(
        url="https://www.publishersweekly.com/pw/feeds/recent/index.xml",
        name="publishers_weekly",
        category="publishers",
        publisher="Publishers Weekly",
    ),
    RSSFeedSource(
        url="https://www.tor.com/feed/",
        name="tor_com",
        category="publishers",
        publisher="Tor.com",
    ),
    RSSFeedSource(
        url="https://electricliterature.com/feed/",
        name="electric_literature",
        category="publishers",
        publisher="Electric Literature",
    ),
]

DEFAULT_REVIEW_FEEDS: list[RSSFeedSource] = [
    RSSFeedSource(
        url="https://feeds.npr.org/1039/rss.xml",
        name="npr_books",
        category="reviews",
        publisher="NPR Books",
        exclude_keywords=(
            "tiny desk",
            "jazz",
            "trumpet",
            "album",
            "drake",
            "concert",
            "grammy",
            "billboard",
        ),
    ),
    RSSFeedSource(
        url="https://lithub.com/feed/",
        name="lithub",
        category="reviews",
        publisher="Literary Hub",
    ),
    RSSFeedSource(
        url="https://bookriot.com/feed/",
        name="book_riot",
        category="reviews",
        publisher="Book Riot",
    ),
]

BOOK_FEEDS = _env_feeds("BOOK_RSS_FEEDS", DEFAULT_BOOK_FEEDS)
PUBLISHER_FEEDS = _env_feeds("PUBLISHER_RSS_FEEDS", DEFAULT_PUBLISHER_FEEDS)
REVIEW_FEEDS = _env_feeds("REVIEW_RSS_FEEDS", DEFAULT_REVIEW_FEEDS)


@dataclass(frozen=True)
class FirebaseConfig:
    credentials_path: str = field(default_factory=lambda: os.getenv("FIREBASE_CREDENTIALS_PATH", ""))
    project_id: str = field(default_factory=lambda: os.getenv("FIREBASE_PROJECT_ID", ""))
    enabled: bool = field(
        default_factory=lambda: os.getenv("FIREBASE_ENABLED", "false").lower() in {"1", "true", "yes"}
    )


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5"))
    enabled: bool = field(
        default_factory=lambda: os.getenv("AI_SUMMARY_ENABLED", "false").lower() in {"1", "true", "yes"}
    )
    base_url: str = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class SchedulerConfig:
    rss_refresh_hours: int = field(default_factory=lambda: int(os.getenv("RSS_REFRESH_HOURS", "1")))
    retry_failed_minutes: int = field(default_factory=lambda: int(os.getenv("RETRY_FAILED_MINUTES", "30")))
    weekly_cleanup_day: str = field(default_factory=lambda: os.getenv("WEEKLY_CLEANUP_DAY", "sun"))
    weekly_cleanup_hour: int = field(default_factory=lambda: int(os.getenv("WEEKLY_CLEANUP_HOUR", "3")))
    duplicate_cleanup_hours: int = field(
        default_factory=lambda: int(os.getenv("DUPLICATE_CLEANUP_HOURS", "24"))
    )


FIREBASE_CONFIG = FirebaseConfig()
OPENROUTER_CONFIG = OpenRouterConfig()
SCHEDULER_CONFIG = SchedulerConfig()

# Firebase collection names (shared pattern for future *Radar engines)
COLLECTION_BOOKS = "books"
COLLECTION_TRENDING = "trending"
COLLECTION_NEW_RELEASES = "new_releases"
COLLECTION_EDITOR_PICKS = "editor_picks"
COLLECTION_CATEGORIES = "categories"
