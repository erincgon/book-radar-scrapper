"""Unified book/article schema for BookRadar Engine.

Replaces StreamRadar `ContentItem` (movie/TV fields) with book-centric metadata.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from utils.text_cleaner import clean_text, normalize_title, utc_now_iso, utc_now_iso_z


REQUIRED_KEYS = (
    "id",
    "title",
    "author",
    "description",
    "summary_ai",
    "categories",
    "genre",
    "language",
    "publisher",
    "published_date",
    "thumbnail",
    "cover_large",
    "article_url",
    "source",
    "source_type",
    "tags",
    "created_at",
    "updated_at",
)


def generate_book_id(title: str, article_url: str) -> str:
    """Stable document id from normalized title + URL."""
    payload = f"{normalize_title(title).lower()}|{article_url.strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _extract_author(raw: dict[str, Any]) -> str:
    for key in ("author", "authors", "dc_creator", "creator"):
        value = raw.get(key)
        if not value:
            continue
        if isinstance(value, list):
            parts = [clean_text(v) for v in value if clean_text(v)]
            if parts:
                return ", ".join(parts)
        text = clean_text(value)
        if text:
            return text
    return ""


def _extract_tags(raw: dict[str, Any]) -> list[str]:
    tags: set[str] = set()
    for key in ("tags", "keywords", "category"):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            tags.update(clean_text(v) for v in value if clean_text(v))
        else:
            for part in re.split(r"[,/|]", str(value)):
                t = clean_text(part)
                if t:
                    tags.add(t)
    return sorted(tags)


@dataclass
class BookItem:
    id: str
    title: str
    author: str
    description: str
    summary_ai: str
    categories: list[str]
    genre: list[str]
    language: str
    publisher: str
    published_date: str
    thumbnail: str
    cover_large: str
    article_url: str
    source: str
    source_type: str
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "BookItem":
        title = normalize_title(raw.get("title"), fallback="Untitled")
        article_url = clean_text(raw.get("article_url"))
        book_id = clean_text(raw.get("id")) or generate_book_id(title, article_url)
        now = utc_now_iso()
        now_z = utc_now_iso_z()

        thumbnail = clean_text(raw.get("thumbnail"))
        cover_large = clean_text(raw.get("cover_large")) or thumbnail

        return cls(
            id=book_id,
            title=title,
            author=_extract_author(raw),
            description=clean_text(raw.get("description")),
            summary_ai=clean_text(raw.get("summary_ai")),
            categories=list(raw.get("categories") or []),
            genre=list(raw.get("genre") or raw.get("genres") or []),
            language=clean_text(raw.get("language"), fallback="English"),
            publisher=clean_text(raw.get("publisher")),
            published_date=clean_text(raw.get("published_date")),
            thumbnail=thumbnail,
            cover_large=cover_large,
            article_url=article_url,
            source=clean_text(raw.get("source")),
            source_type=clean_text(raw.get("source_type"), fallback="rss"),
            tags=_extract_tags(raw),
            created_at=clean_text(raw.get("created_at"), fallback=now) or now,
            updated_at=clean_text(raw.get("updated_at"), fallback=now_z) or now_z,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "description": self.description,
            "summary_ai": self.summary_ai,
            "categories": self.categories,
            "genre": self.genre,
            "language": self.language,
            "publisher": self.publisher,
            "published_date": self.published_date,
            "thumbnail": self.thumbnail,
            "cover_large": self.cover_large,
            "article_url": self.article_url,
            "source": self.source,
            "source_type": self.source_type,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def validate_book_schema(item: dict[str, Any]) -> bool:
    if not item or not isinstance(item, dict):
        return False
    if set(REQUIRED_KEYS) - set(item.keys()):
        return False
    if not clean_text(item.get("title")):
        return False
    if not isinstance(item["categories"], list) or not isinstance(item["genre"], list):
        return False
    if not isinstance(item["tags"], list):
        return False
    return True
