"""Book/article normalization pipeline."""

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
from utils.parallel import parallel_map
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

    def normalize_raw_items(
        self,
        raw_items: list[dict[str, Any]],
        *,
        feed_name: str | None = None,
    ) -> list[dict[str, Any]]:
        scan_limit = int(APP_CONFIG.max_items_per_feed * APP_CONFIG.raw_scan_multiplier)
        processed: list[dict[str, Any]] = []

        for raw in raw_items[:scan_limit]:
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
        trimmed = processed[: APP_CONFIG.max_items_per_feed]
        return self._enrich_missing_thumbnails(trimmed)

    def _enrich_missing_thumbnails(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        need: list[tuple[int, str]] = []
        for idx, item in enumerate(items):
            thumb = item.get("thumbnail") or ""
            if not thumb or is_bad_image_url(thumb):
                url = item.get("article_url")
                if url:
                    need.append((idx, str(url)))

        if not need:
            return items

        budget = APP_CONFIG.article_enrichment_max
        to_fetch = need[:budget]
        if len(need) > budget:
            logger.info(
                "Thumbnail enrichment capped %s/%s (set ARTICLE_ENRICHMENT_MAX to raise)",
                budget,
                len(need),
            )

        urls = [url for _, url in to_fetch]

        def _fetch(url: str) -> tuple[str, str]:
            html = self.http_client.fetch_html_snippet(url)
            image = extract_image_from_article_html(html) if html else ""
            return url, image

        fetched = parallel_map(_fetch, urls, max_workers=APP_CONFIG.article_fetch_workers)
        url_to_image = {url: img for url, img in fetched if img and not is_bad_image_url(img)}

        for idx, url in to_fetch:
            image = url_to_image.get(url)
            if not image:
                continue
            items[idx]["thumbnail"] = image
            items[idx]["cover_large"] = image

        return items

    def _sort_priority(self, item: dict[str, Any]) -> tuple[int, str]:
        thumb = item.get("thumbnail") or ""
        has_real_image = 1 if thumb and not is_bad_image_url(thumb) else 0
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
            return None

        article_url = strip_tracking_params(clean_text(raw.get("article_url")))
        if not article_url.startswith(("http://", "https://")):
            return None

        published = normalize_pub_date_to_iso_z(raw.get("published_raw") or raw.get("published_date"))
        published_date = published[:10] if published else clean_text(raw.get("published_date"))

        source = source_from_url(article_url) or clean_text(raw.get("source"))
        thumbnail = self._thumbnail_from_rss(raw)
        cover_large = upgrade_image_url(clean_text(raw.get("cover_large"))) or thumbnail

        book_publisher = extract_book_publisher(raw, "")
        if not book_publisher:
            book_publisher = source

        normalized_raw = {
            **raw,
            "title": title,
            "description": description,
            "article_url": article_url,
            "published_date": published_date,
            "thumbnail": thumbnail,
            "cover_large": cover_large or thumbnail,
            "categories": self._normalize_categories(raw.get("categories"), feed_name),
            "genre": normalize_genres(raw.get("genre") or raw.get("genres")),
            "author": self._normalize_author(raw),
            "publisher": book_publisher,
            "source": source,
            "language": clean_text(raw.get("language"), fallback="English"),
            "source_type": "rss",
            "updated_at": utc_now_iso_z(),
        }

        return BookItem.from_raw(normalized_raw).to_dict()

    def _thumbnail_from_rss(self, raw: dict[str, Any]) -> str:
        for key in ("thumbnail", "cover_large"):
            candidate = upgrade_image_url(self._normalize_image(clean_text(raw.get(key))))
            if candidate and not is_bad_image_url(candidate):
                return candidate
        return ""

    def _normalize_author(self, raw: dict[str, Any]) -> str:
        author = clean_text(raw.get("author"))
        if author:
            return re.sub(r"^by\s+", "", author, flags=re.I)
        title = clean_text(raw.get("title"))
        match = re.search(r"['\"]([^'\"]+)['\"]\s+by\s+([\w\s.'-]+)", title, flags=re.I)
        if match:
            return clean_text(match.group(2))
        return ""

    def _normalize_categories(self, value: Any, feed_name: str | None) -> list[str]:
        categories = normalize_genres(value)
        mapped = [CATEGORY_ALIASES.get(cat.lower().strip(), cat.title()) for cat in categories]
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
