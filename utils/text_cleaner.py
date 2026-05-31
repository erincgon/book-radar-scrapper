"""Text normalization helpers.

Adapted from StreamRadar `utils/normalization.py` — movie/platform logic removed.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

SUMMARY_MAX_CHARS = 1200

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y-%m",
    "%Y",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text or fallback


def normalize_title(value: Any, fallback: str = "Untitled") -> str:
    text = clean_text(value, fallback=fallback)
    text = re.sub(r"\s*[-|–—]\s*(?:[A-Za-z][\w .&+:'/-]{1,60}|[\w.-]+\.[a-z]{2,})(?:\s*)$", "", text)
    text = re.sub(r"\s*[-|–—]\s*[\w.-]+\.[a-z]{2,}\s*$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -|")
    return text or fallback


def clamp_text(value: Any, *, max_chars: int = SUMMARY_MAX_CHARS, fallback: str = "") -> str:
    text = clean_text(value, fallback=fallback)
    if not text or len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    clipped = clipped.rstrip(" ,;:-–—")
    if not clipped.endswith((".", "!", "?")):
        clipped = f"{clipped}..."
    return clipped or fallback


def normalize_pub_date_to_iso_z(value: Any) -> str | None:
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc).replace(tzinfo=timezone.utc, microsecond=0)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    text = clean_text(value)
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass

    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        pass

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            parsed = datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
            return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def parse_release_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    iso = normalize_pub_date_to_iso_z(text)
    if iso:
        return iso[:10]
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue
    return ""


def normalize_genres(value: Any) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else re.split(r"[,/|]", str(value))
    return sorted({clean_text(item).title() for item in raw if clean_text(item)})


def title_similarity_signature(title: str) -> str:
    t = normalize_title(title).lower()
    t = re.sub(r"\b(?:the|a|an)\b", "", t)
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def looks_book_related(title: str, description: str) -> bool:
    text = f"{clean_text(title)} {clean_text(description)}".lower()
    allow = (
        "book",
        "novel",
        "author",
        "publisher",
        "literary",
        "fiction",
        "nonfiction",
        "memoir",
        "poetry",
        "essay",
        "review",
        "bestseller",
        "kindle",
        "audiobook",
        "reading",
        "library",
        "hardcover",
        "paperback",
        "isbn",
    )
    deny = (
        "stock",
        "crypto",
        "football",
        "basketball",
        "election",
        "airpods",
        "discount code",
    )
    if any(bad in text for bad in deny):
        return False
    return any(good in text for good in allow) or len(clean_text(title)) >= 12
