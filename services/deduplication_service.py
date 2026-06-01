"""Duplicate detection — per-feed scope so books never empties publishers/reviews."""

from __future__ import annotations

import hashlib
import json
import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from config.settings import CACHE_DIR
from utils.html_cleaner import strip_tracking_params
from utils.text_cleaner import clean_text, title_similarity_signature

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.92


def normalized_url_signature(url: str | None) -> str:
    if not url:
        return ""
    cleaned = strip_tracking_params(url.strip().lower().rstrip("/"))
    try:
        parsed = urlsplit(cleaned)
        qs = "&".join(sorted(f"{k}={v}" for k, v in parse_qsl(parsed.query)))
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{path}" + (f"?{qs}" if qs else "")
    except Exception:
        return cleaned


def title_hash(title: str) -> str:
    sig = title_similarity_signature(title)
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()


def url_hash(url: str) -> str:
    return hashlib.sha256(normalized_url_signature(url).encode("utf-8")).hexdigest()


def dedupe_key(item: dict[str, Any]) -> str:
    article_url = clean_text(item.get("article_url"))
    if article_url:
        return "url|" + url_hash(article_url)
    return "title|" + title_hash(clean_text(item.get("title")))


def scoped_key(feed_name: str, item: dict[str, Any]) -> str:
    return f"{feed_name}|{dedupe_key(item)}"


class DeduplicationService:
    """Per-feed dedupe: books, publishers, and reviews keep separate URL pools."""

    def __init__(self, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path or CACHE_DIR / "seen_entries.json"
        self._seen_keys: set[str] = set()
        self._load_cache()

    def _load_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            keys = data.get("keys", []) if isinstance(data, dict) else []
            # Only keep feed-scoped keys (ignore legacy global keys without "|")
            self._seen_keys = {k for k in keys if isinstance(k, str) and "|" in k}
        except Exception as exc:
            logger.warning("Could not load dedupe cache: %s", exc)

    def save_cache(self) -> None:
        payload = {"keys": sorted(self._seen_keys)[-15000:]}
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def filter_duplicates(
        self,
        items: list[dict[str, Any]],
        *,
        feed_name: str,
    ) -> list[dict[str, Any]]:
        batch_urls: set[str] = set()
        batch_titles: list[str] = []
        unique: list[dict[str, Any]] = []
        skipped = 0

        for item in items:
            key = dedupe_key(item)
            scope = scoped_key(feed_name, item)

            if key in batch_urls:
                skipped += 1
                continue
            if scope in self._seen_keys:
                skipped += 1
                continue

            title_sig = title_similarity_signature(clean_text(item.get("title")))
            if any(
                SequenceMatcher(None, title_sig, existing).ratio() >= SIMILARITY_THRESHOLD
                for existing in batch_titles
            ):
                skipped += 1
                continue

            batch_urls.add(key)
            batch_titles.append(title_sig)
            self._seen_keys.add(scope)
            unique.append(item)

        if skipped:
            logger.info(
                "Feed '%s' dedupe skipped %s duplicate(s), kept %s",
                feed_name,
                skipped,
                len(unique),
            )
        return unique

    def filter_cross_feed(self, items: list[dict[str, Any]], seen_urls: set[str]) -> list[dict[str, Any]]:
        """Optional: drop URLs already used in another curated list."""
        filtered: list[dict[str, Any]] = []
        for item in items:
            url = normalized_url_signature(item.get("article_url"))
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            filtered.append(item)
        return filtered

    def cleanup_stale(self, max_keys: int = 12000) -> int:
        before = len(self._seen_keys)
        if before <= max_keys:
            return 0
        self._seen_keys = set(sorted(self._seen_keys)[-max_keys:])
        removed = before - len(self._seen_keys)
        logger.info("Duplicate cache cleanup removed %s keys", removed)
        return removed
