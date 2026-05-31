"""Book/article normalization pipeline.

Replaces StreamRadar movie normalization — standardizes categories, dates,
descriptions, thumbnails, and JSON-safe output.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from config.settings import APP_CONFIG
from models.book_model import BookItem, validate_book_schema
from utils.html_cleaner import strip_html, strip_tracking_params
from utils.http_client import HTTPClient
from utils.text_cleaner import (
    clamp_text,
    clean_text,
    looks_book_related,
    normalize_genres,
    normalize_pub_date_to_iso_z,
    normalize_title,
    utc_now_iso_z,
)

logger = logging.getLogger(__name__)

CATEGORY_ALIASES = {
    "books": "Books",
    "book": "Books",
    "reviews": "Reviews",
    "review": "Reviews",
    "publishers": "Publishers",
    "publisher": "Publishers",
    "fiction": "Fiction",
    "nonfiction": "Nonfiction",
    "literary": "Literary",
    "kindle": "Kindle",
    "articles": "Articles",
}

FALLBACK_THUMBNAIL = "https://via.placeholder.com/400x600/1a1a2e/eaeaea?text=Book"

_GENERIC_BAD_TITLES = {"breaking news", "news", "update", "latest updates", "untitled"}


class NormalizationService:
    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http_client = http_client or HTTPClient()
        self._thumbnail_fetch_budget = 12

    def normalize_raw_items(
        self,
        raw_items: list[dict[str, Any]],
        *,
        feed_name: str | None = None,
    ) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        for raw in raw_items[: APP_CONFIG.max_items_per_feed * 2]:
            try:
                item = self._normalize_one(raw, feed_name=feed_name)
                if item and validate_book_schema(item):
                    processed.append(item)
            except Exception as exc:
                logger.debug(
                    "Skipped malformed entry feed=%s title=%s error=%s",
                    feed_name,
                    raw.get("title"),
                    exc,
                )
        return processed[: APP_CONFIG.max_items_per_feed]

    def _normalize_one(self, raw: dict[str, Any], *, feed_name: str | None) -> dict[str, Any] | None:
        title = normalize_title(raw.get("title"))
        if title.lower() in _GENERIC_BAD_TITLES or len(title) < 6:
            return None

        description = clamp_text(
            strip_html(raw.get("description")),
            max_chars=APP_CONFIG.description_max_chars,
        )
        if not looks_book_related(title, description) and feed_name not in {"books", "reviews", "publishers"}:
            logger.debug("Skipping non-book row title=%s", title)
            return None

        article_url = strip_tracking_params(clean_text(raw.get("article_url")))
        if not article_url.startswith(("http://", "https://")):
            return None

        published = normalize_pub_date_to_iso_z(raw.get("published_raw") or raw.get("published_date"))
        published_date = published[:10] if published else clean_text(raw.get("published_date"))

        thumbnail = self._normalize_image(clean_text(raw.get("thumbnail")))
        cover_large = self._normalize_image(clean_text(raw.get("cover_large"))) or thumbnail

        if not thumbnail:
            thumbnail = self._fallback_thumbnail(title, article_url)
            cover_large = cover_large or thumbnail

        categories = self._normalize_categories(raw.get("categories"), feed_name)
        genre = normalize_genres(raw.get("genre") or raw.get("genres"))

        normalized_raw = {
            **raw,
            "title": title,
            "description": description,
            "article_url": article_url,
            "published_date": published_date,
            "thumbnail": thumbnail,
            "cover_large": cover_large or thumbnail,
            "categories": categories,
            "genre": genre,
            "author": self._normalize_author(raw),
            "publisher": clean_text(raw.get("publisher") or raw.get("source")),
            "language": clean_text(raw.get("language"), fallback="English"),
            "source_type": "rss",
            "updated_at": utc_now_iso_z(),
        }

        book = BookItem.from_raw(normalized_raw)
        return book.to_dict()

    def _normalize_author(self, raw: dict[str, Any]) -> str:
        author = clean_text(raw.get("author"))
        if author:
            author = re.sub(r"^by\s+", "", author, flags=re.I)
            return author
        title = clean_text(raw.get("title"))
        match = re.search(r"['\"]([^'\"]+)['\"]\s+by\s+([\w\s.'-]+)", title, flags=re.I)
        if match:
            return clean_text(match.group(2))
        return ""

    def _normalize_categories(self, value: Any, feed_name: str | None) -> list[str]:
        categories = normalize_genres(value)
        mapped = []
        for cat in categories:
            key = cat.lower().strip()
            mapped.append(CATEGORY_ALIASES.get(key, cat.title()))
        if feed_name:
            mapped.append(CATEGORY_ALIASES.get(feed_name, feed_name.title()))
        return sorted(set(mapped))

    def _normalize_image(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("http://"):
            url = "https://" + url[7:]
        if not url.startswith("https://"):
            return ""
        return strip_tracking_params(url)

    def _fallback_thumbnail(self, title: str, article_url: str) -> str:
        if self._thumbnail_fetch_budget <= 0:
            return FALLBACK_THUMBNAIL
        self._thumbnail_fetch_budget -= 1
        try:
            response = self.http_client.get(article_url)
            if response.ok and "html" in response.headers.get("Content-Type", "").lower():
                from utils.html_cleaner import extract_first_image_url

                image = extract_first_image_url(response.text)
                if image:
                    return image
        except Exception as exc:
            logger.debug("Thumbnail fallback fetch failed url=%s error=%s", article_url, exc)

        slug = urlparse(article_url).netloc.replace(".", "-")[:24]
        safe_title = re.sub(r"[^\w]+", "+", title)[:40]
        return f"{FALLBACK_THUMBNAIL}&source={slug}&t={safe_title}"
