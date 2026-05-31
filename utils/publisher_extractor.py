"""Extract book imprint / publisher from RSS text and article HTML."""

from __future__ import annotations

import json
import re
from typing import Any

from utils.html_cleaner import strip_html
from utils.text_cleaner import clean_text

# Common imprints — word-boundary matching to avoid false positives like "Tor" in "history".
KNOWN_IMPRINTS: tuple[str, ...] = (
    "Penguin Random House",
    "Random House",
    "HarperCollins",
    "Simon & Schuster",
    "Macmillan",
    "Hachette Book Group",
    "Hachette",
    "Scholastic",
    "W.W. Norton",
    "W. W. Norton",
    "Norton",
    "Knopf",
    "Doubleday",
    "Riverhead Books",
    "Riverhead",
    "Farrar, Straus and Giroux",
    "Farrar, Straus & Giroux",
    "Scribner",
    "Little, Brown",
    "Crown Publishing",
    "Crown",
    "Vintage Books",
    "Vintage",
    "Anchor Books",
    "Bloomsbury",
    "Tor Books",
    "Orbit",
    "Flatiron Books",
    "Henry Holt",
    "Picador",
    "Grove Press",
    "Graywolf Press",
    "Coffee House Press",
    "Ecco",
    "Mariner Books",
    "Hogarth Press",
    "Dial Press",
    "Dutton",
    "Putnam",
    "Ballantine Books",
    "Del Rey",
    "Ace Books",
    "Minotaur Books",
    "St. Martin's Press",
    "St Martin's Press",
    "Pantheon",
    "Kensington",
    "Sourcebooks",
    "Workman Publishing",
    "Chronicle Books",
    "Melville House",
    "Catapult",
    "One World",
    "MCD",
    "FSG",
    "Faber & Faber",
    "Canongate",
    "Verso Books",
    "Haymarket Books",
)

_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"published by ([A-Z][\w\s,&\.'-]{2,60}?)(?:\.|,|\s+on\b|\s+in\b|\s+\()", re.I),
    re.compile(r"from ([A-Z][\w\s,&\.'-]{2,50}?(?:Press|Books|Publishing|House|Publishers))(?:\.|,|\s)", re.I),
    re.compile(r"\(([A-Z][\w\s,&\.'-]{2,50}?(?:Press|Books|Publishing|Publishers))\)", re.I),
    re.compile(r"Publisher:\s*</?[^>]*>\s*([^<\n]{2,60})", re.I),
    re.compile(r"<b>Publisher:</b>\s*([^<\n]{2,60})", re.I),
)

_SKIP_VALUES = frozenset({"n/a", "none", "unknown", "na", "-", ""})


def _normalize_imprint(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"\s+", " ", text).strip(" .,;")
    if text.lower() in _SKIP_VALUES:
        return ""
    return text


def _find_known_imprint(blob: str) -> str:
    for imprint in sorted(KNOWN_IMPRINTS, key=len, reverse=True):
        pattern = rf"\b{re.escape(imprint)}\b"
        if re.search(pattern, blob, re.I):
            return imprint
    return ""


def extract_publisher_from_text(*parts: str) -> str:
    blob = " ".join(clean_text(p) for p in parts if p)
    if not blob:
        return ""

    for pattern in _TEXT_PATTERNS:
        match = pattern.search(blob)
        if match:
            candidate = _normalize_imprint(match.group(1))
            if candidate:
                return candidate

    return _find_known_imprint(blob)


def extract_publisher_from_html(html: str) -> str:
    if not html:
        return ""

    for pattern in _TEXT_PATTERNS:
        match = pattern.search(html)
        if match:
            candidate = _normalize_imprint(strip_html(match.group(1)))
            if candidate:
                return candidate

    for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            publisher = item.get("publisher")
            if isinstance(publisher, dict):
                name = _normalize_imprint(str(publisher.get("name", "")))
                if name:
                    return name
            elif isinstance(publisher, str):
                name = _normalize_imprint(publisher)
                if name:
                    return name

    meta = re.search(
        r'<meta[^>]+(?:property|name)=["\']book:publisher["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if meta:
        name = _normalize_imprint(meta.group(1))
        if name:
            return name

    return _find_known_imprint(strip_html(html))


def extract_book_publisher(raw: dict[str, Any], article_html: str = "") -> str:
    tags = raw.get("tags") or raw.get("categories") or []
    tag_text = " ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)

    from_html = extract_publisher_from_html(article_html)
    if from_html:
        return from_html

    from_text = extract_publisher_from_text(
        raw.get("title", ""),
        raw.get("description", ""),
        tag_text,
    )
    if from_text:
        return from_text

    # RSS-level publisher field is the feed outlet, not the book imprint — ignore unless
    # it looks like a real publishing house.
    feed_hint = clean_text(raw.get("feed_publisher_hint", ""))
    if feed_hint and _find_known_imprint(feed_hint):
        return _find_known_imprint(feed_hint)

    return ""
