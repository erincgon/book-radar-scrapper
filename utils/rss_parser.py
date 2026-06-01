"""RSS feed parsing utilities.

Core logic adapted from StreamRadar `scrapers/rss_scraper.py` — movie/platform
filters removed; book/article metadata extraction retained.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import feedparser

from config.settings import APP_CONFIG, RSSFeedSource
from utils.attribution import source_from_url
from utils.html_cleaner import strip_html, strip_tracking_params
from utils.http_client import HTTPClient
from utils.image_utils import extract_rss_entry_images, is_bad_image_url
from utils.text_cleaner import clean_text, normalize_title, parse_release_date

logger = logging.getLogger(__name__)

BOOK_GENRE_CANDIDATES = (
    "Fiction",
    "Nonfiction",
    "Mystery",
    "Thriller",
    "Romance",
    "Science Fiction",
    "Fantasy",
    "Biography",
    "Memoir",
    "History",
    "Poetry",
    "Young Adult",
    "Children",
    "Self-Help",
    "Business",
    "Politics",
    "Essays",
    "Literary Fiction",
    "Horror",
    "Crime",
)


def _normalize_href(href: str) -> str | None:
    h = href.strip()
    if h.startswith("//"):
        h = "https:" + h
    if h.startswith(("http://", "https://")):
        return strip_tracking_params(h)
    return None


def _extract_author(entry: Any) -> str:
    author = getattr(entry, "author", None) or getattr(entry, "author_detail", None)
    if isinstance(author, str) and author.strip():
        return clean_text(author)
    if isinstance(author, dict):
        return clean_text(author.get("name"))
    authors = getattr(entry, "authors", None)
    if isinstance(authors, list):
        names = []
        for item in authors:
            if isinstance(item, dict):
                name = clean_text(item.get("name"))
            else:
                name = clean_text(item)
            if name:
                names.append(name)
        if names:
            return ", ".join(names)
    for tag in getattr(entry, "tags", []) or []:
        term = getattr(tag, "term", None) if not isinstance(tag, dict) else tag.get("term")
        if term and str(term).lower().startswith("author:"):
            return clean_text(str(term).split(":", 1)[-1])
    return ""


def _extract_media_url(entry: Any, raw_summary: str) -> str:
    image = extract_rss_entry_images(entry, raw_summary)
    if image and not is_bad_image_url(image):
        return image
    return ""


def _candidate_article_urls(entry: Any, raw_summary: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r'href=["\']([^"\']+)["\']', raw_summary or "", flags=re.I):
        norm = _normalize_href(match.group(1))
        if norm:
            found.append(norm)

    entry_id = getattr(entry, "id", "") or getattr(entry, "guid", "")
    if isinstance(entry_id, str) and entry_id.strip().startswith("http"):
        norm = _normalize_href(entry_id.strip())
        if norm:
            found.append(norm)

    links = getattr(entry, "links", None)
    if links and isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            href = link.get("href")
            if isinstance(href, str) and href.strip():
                norm = _normalize_href(href.strip())
                if norm:
                    found.append(norm)

    elink = getattr(entry, "link", "")
    if isinstance(elink, str):
        norm = _normalize_href(elink.strip())
        if norm:
            found.append(norm)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in found:
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def _pick_article_url(candidates: list[str]) -> str:
    for cand in candidates:
        parsed = urlparse(cand)
        if parsed.path.strip("/"):
            return cand
    return candidates[0] if candidates else ""


def _extract_genres(text: str) -> list[str]:
    lowered = text.lower()
    return [genre for genre in BOOK_GENRE_CANDIDATES if genre.lower() in lowered]


def _extract_categories(entry: Any, feed: RSSFeedSource) -> list[str]:
    categories: set[str] = {feed.category}
    tags = getattr(entry, "tags", None) or []
    for tag in tags:
        term = getattr(tag, "term", None) if not isinstance(tag, dict) else tag.get("term")
        if term:
            categories.add(clean_text(str(term)))
    return sorted(c for c in categories if c)


class RSSParser:
    """Fetch and parse RSS feeds into raw book/article dicts."""

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http_client = http_client or HTTPClient()

    def fetch_feed(self, feed_source: RSSFeedSource) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            response = self.http_client.get(feed_source.url, fast=True)
            if not response.ok:
                logger.warning(
                    "RSS fetch failed status=%s feed=%s url=%s",
                    response.status_code,
                    feed_source.name,
                    feed_source.url,
                )
                return results

            parsed = feedparser.parse(response.content)
            if getattr(parsed, "bozo", False):
                logger.warning(
                    "Malformed RSS feed feed=%s url=%s error=%s",
                    feed_source.name,
                    feed_source.url,
                    getattr(parsed, "bozo_exception", "unknown"),
                )

            cap = APP_CONFIG.max_items_per_feed
            for entry in getattr(parsed, "entries", [])[: cap * 3]:
                if len(results) >= cap:
                    break
                item = self._entry_to_raw(entry, feed_source)
                if item:
                    results.append(item)

            logger.info(
                "RSS success feed=%s source=%s entries=%s",
                feed_source.name,
                feed_source.publisher or feed_source.name,
                len(results),
            )
        except Exception as exc:
            logger.warning("RSS failure feed=%s url=%s error=%s", feed_source.name, feed_source.url, exc)
        return results

    def _entry_to_raw(self, entry: Any, feed: RSSFeedSource) -> dict[str, Any] | None:
        title = normalize_title(getattr(entry, "title", ""), fallback="")
        if not title:
            return None

        raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        description = strip_html(raw_summary)
        merged = f"{title} {description}".lower()

        if feed.include_keywords and not any(k in merged for k in feed.include_keywords):
            return None
        if feed.exclude_keywords and any(k in merged for k in feed.exclude_keywords):
            return None

        published = (
            getattr(entry, "published", None)
            or getattr(entry, "updated", None)
            or getattr(entry, "pubDate", None)
        )
        candidates = _candidate_article_urls(entry, raw_summary)
        article_url = _pick_article_url(candidates)
        if not article_url:
            return None

        thumbnail = _extract_media_url(entry, raw_summary) or ""
        author = _extract_author(entry)
        outlet = source_from_url(article_url) or feed.publisher or feed.name

        return {
            "title": title,
            "author": author,
            "description": description,
            "published_date": parse_release_date(published) or clean_text(str(published or "")),
            "published_raw": published,
            "thumbnail": thumbnail,
            "cover_large": thumbnail,
            "article_url": article_url,
            "source": outlet,
            "source_type": "rss",
            "publisher": "",
            "feed_publisher_hint": feed.publisher,
            "language": feed.language,
            "categories": _extract_categories(entry, feed),
            "genre": _extract_genres(merged),
            "tags": list(_extract_categories(entry, feed)),
            "feed_name": feed.name,
        }
