"""Duplicate detection for book/article entries.

Adapted from StreamRadar dedupe patterns in `utils/pipeline.py` and
`utils/normalization.py` — uses title hash, URL hash, and title similarity.
"""

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
    sig = normalized_url_signature(url)
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()


def dedupe_key(item: dict[str, Any]) -> str:
    article_url = clean_text(item.get("article_url"))
    if article_url:
        return "url|" + url_hash(article_url)
    return "title|" + title_hash(clean_text(item.get("title")))


class DeduplicationService:
    """In-memory and persisted duplicate protection."""

    def __init__(self, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path or CACHE_DIR / "seen_entries.json"
        self._seen_keys: set[str] = set()
        self._seen_titles: list[str] = []
        self._load_cache()

    def _load_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            keys = data.get("keys", []) if isinstance(data, dict) else []
            titles = data.get("titles", []) if isinstance(data, dict) else []
            self._seen_keys = set(keys)
            self._seen_titles = list(titles)[-5000:]
        except Exception as exc:
            logger.warning("Could not load dedupe cache: %s", exc)

    def save_cache(self) -> None:
        payload = {
            "keys": sorted(self._seen_keys)[-10000:],
            "titles": self._seen_titles[-5000:],
        }
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_duplicate(self, item: dict[str, Any]) -> bool:
        key = dedupe_key(item)
        if key in self._seen_keys:
            logger.info(
                "Skipped duplicate key=%s title=%s",
                key[:16],
                item.get("title"),
            )
            return True

        title_sig = title_similarity_signature(clean_text(item.get("title")))
        for existing in self._seen_titles:
            if SequenceMatcher(None, title_sig, existing).ratio() >= SIMILARITY_THRESHOLD:
                logger.info(
                    "Skipped duplicate (title similarity) title=%s similar_to=%s",
                    item.get("title"),
                    existing,
                )
                return True
        return False

    def mark_seen(self, item: dict[str, Any]) -> None:
        self._seen_keys.add(dedupe_key(item))
        self._seen_titles.append(title_similarity_signature(clean_text(item.get("title"))))

    def filter_duplicates(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        for item in items:
            if self.is_duplicate(item):
                continue
            self.mark_seen(item)
            unique.append(item)
        return unique

    def cleanup_stale(self, max_keys: int = 8000) -> int:
        before = len(self._seen_keys)
        if before <= max_keys:
            return 0
        trimmed = sorted(self._seen_keys)[-max_keys:]
        self._seen_keys = set(trimmed)
        removed = before - len(self._seen_keys)
        logger.info("Duplicate cache cleanup removed %s keys", removed)
        return removed
