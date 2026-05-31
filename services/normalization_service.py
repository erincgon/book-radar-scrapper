"""Book/article normalization pipeline.

Replaces StreamRadar movie normalization — standardizes categories, dates,
descriptions, thumbnails, and JSON-safe output.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from config.settings import APP_CONFIG
from models.book_model import BookItem, validate_book_schema
from utils.attribution import source_from_url
from utils.html_cleaner import strip_html, strip_tracking_params
from utils.http_client import HTTPClient
from utils.image_utils import extract_image_from_article_html, is_bad_image_url, upgrade_image_url
from utils.publisher_extractor import extract_book_publisher
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

_GENERIC_BAD_TITLES = {"breaking news", "news", "update", "latest updates", "untitled"}


class NormalizationService:
    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http_client = http_client or HTTPClient()
        self._article_cache: dict[str, str] = {}
        self._enrichment_budget = APP_CONFIG.max_items_per_feed

    def normalize_raw_items(
        self,
        raw_items: list[dict[str, Any]],
        *,
        feed_name: str | None = None,
    ) -> list[dict[str, Any]]:
        self._enrichment_budget = min(20, APP_CONFIG.max_items_per_feed)
        self._article_cache.clear()

        processed: list[dict[str, Any]] = []
        for raw in raw_items[: APP_CONFIG.max_items_per_feed * 3]:
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

        processed.sort(key=self._sort_priority, reverse=True)
        return processed[: APP_CONFIG.max_items_per_feed]

    def _sort_priority(self, item: dict[str, Any]) -> tuple[int, str]:
        thumb = item.get("thumbnail") or ""
        has_real_image = 1 if thumb and not is_bad_image_url(thumb) and "placeholder" not in thumb else 0
        return (has_real_image, item.get("published_date") or "")

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

        source = source_from_url(article_url) or clean_text(raw.get("source"))

        thumbnail = self._resolve_thumbnail(raw, article_url)
        article_html = ""
        if not thumbnail:
            article_html = self._fetch_article_html(article_url)
            thumbnail = self._resolve_thumbnail(raw, article_url, article_html)

        cover_large = upgrade_image_url(clean_text(raw.get("cover_large"))) or thumbnail

        book_publisher = extract_book_publisher(raw, article_html)
        if not book_publisher:
            book_publisher = source

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
            "publisher": book_publisher,
            "source": source,
            "language": clean_text(raw.get("language"), fallback="English"),
            "source_type": "rss",
            "updated_at": utc_now_iso_z(),
        }

        book = BookItem.from_raw(normalized_raw)
        return book.to_dict()

    def _resolve_thumbnail(
        self,
        raw: dict[str, Any],
        article_url: str,
        article_html: str = "",
    ) -> str:
        for key in ("thumbnail", "cover_large"):
            candidate = upgrade_image_url(self._normalize_image(clean_text(raw.get(key))))
            if candidate and not is_bad_image_url(candidate):
                return candidate

        if article_html:
            from_article = extract_image_from_article_html(article_html)
            if from_article and not is_bad_image_url(from_article):
                return from_article

        return ""

    def _fetch_article_html(self, article_url: str) -> str:
        if article_url in self._article_cache:
            return self._article_cache[article_url]
        if self._enrichment_budget <= 0:
            self._article_cache[article_url] = ""
            return ""

        self._enrichment_budget -= 1
        html = ""
        try:
            response = self.http_client.get(article_url)
            if response.ok and "html" in response.headers.get("Content-Type", "").lower():
                html = response.text[:600_000]
        except Exception as exc:
            logger.debug("Article enrichment failed url=%s error=%s", article_url, exc)

        self._article_cache[article_url] = html
        return html

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
