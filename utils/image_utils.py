"""Book cover and article image extraction."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from utils.html_cleaner import extract_first_image_url, strip_tracking_params

logger = logging.getLogger(__name__)

_PLACEHOLDER_SNIPPETS = (
    "placeholder",
    "1x1",
    "pixel.gif",
    "pixel.png",
    "npr-rss-pixel",
    "tracking",
    "spacer.gif",
    "blank.gif",
    "default-avatar",
    "no-image",
    "gravatar",
    "emoji",
)

_OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_IMAGE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
    re.I,
)
_TWITTER_IMAGE = re.compile(
    r'<meta[^>]+(?:name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']|content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\'])',
    re.I,
)


def is_bad_image_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return True
    lowered = url.lower()
    return any(snippet in lowered for snippet in _PLACEHOLDER_SNIPPETS)


def upgrade_image_url(url: str) -> str:
    """Request larger renditions from common book/news CDNs."""
    if not url:
        return url
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if "guim.co.uk" in host or "i.guim.co.uk" in host:
        qs = parse_qs(parsed.query)
        qs["width"] = ["700"]
        qs["quality"] = ["85"]
        new_query = urlencode({k: v[0] for k, v in qs.items()})
        return urlunparse(parsed._replace(query=new_query))

    if "cloudfront.net" in host and ".180x0_" in url:
        return url.replace(".180x0_", ".600x0_")

    if "nytimes.com" in host and "mediumSquareAt3X" not in url:
        return re.sub(r"-(?:mediumThreeByTwo|superJumbo|articleLarge)\.", "-mediumSquareAt3X.", url)

    return strip_tracking_params(url)


def _score_image(url: str, *, alt: str = "", width: int = 0) -> int:
    if is_bad_image_url(url):
        return -100
    score = 0
    lowered = url.lower()
    alt_lower = alt.lower()
    if any(k in alt_lower for k in ("book cover", "cover", "book jacket", "jacket")):
        score += 50
    if any(k in lowered for k in ("cover", "book", "jacket", "title/cover")):
        score += 25
    if width >= 600:
        score += 30
    elif width >= 300:
        score += 15
    elif width >= 140:
        score += 5
    if any(ext in lowered for ext in (".jpg", ".jpeg", ".png", ".webp")):
        score += 5
    if "avatar" in lowered or "author" in alt_lower:
        score -= 20
    if "logo" in lowered:
        score -= 30
    return score


def _images_from_html(html: str | None) -> list[tuple[str, str, int]]:
    if not html:
        return []
    found: list[tuple[str, str, int]] = []
    for match in re.finditer(r"<img[^>]+>", html, flags=re.I):
        tag = match.group(0)
        src_m = re.search(r'src=["\']([^"\']+)["\']', tag, re.I)
        if not src_m:
            src_m = re.search(r'data-src=["\']([^"\']+)["\']', tag, re.I)
        if not src_m:
            continue
        src = src_m.group(1).strip()
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith(("http://", "https://")):
            continue
        alt_m = re.search(r'alt=["\']([^"\']*)["\']', tag, re.I)
        alt = alt_m.group(1) if alt_m else ""
        width_m = re.search(r'width=["\'](\d+)["\']', tag, re.I)
        width = int(width_m.group(1)) if width_m else 0
        found.append((upgrade_image_url(strip_tracking_params(src)), alt, width))
    return found


def pick_best_image(candidates: list[tuple[str, str, int]]) -> str:
    best_url = ""
    best_score = -999
    for url, alt, width in candidates:
        if is_bad_image_url(url):
            continue
        score = _score_image(url, alt=alt, width=width)
        if score > best_score:
            best_score = score
            best_url = url
    return best_url


def extract_rss_entry_images(entry: Any, raw_html: str = "") -> str:
    """Collect images from all RSS entry fields and return the best cover candidate."""
    candidates: list[tuple[str, str, int]] = []

    for block in (
        raw_html,
        getattr(entry, "summary", "") or "",
        getattr(entry, "description", "") or "",
    ):
        candidates.extend(_images_from_html(block))

    content = getattr(entry, "content", None)
    if isinstance(content, list):
        for part in content:
            value = part.get("value") if isinstance(part, dict) else getattr(part, "value", "")
            candidates.extend(_images_from_html(value))

    media = getattr(entry, "media_content", None) or []
    if isinstance(media, list):
        for item in media:
            url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
            if not isinstance(url, str):
                continue
            width = 0
            try:
                width = int(item.get("width") or getattr(item, "width", 0) or 0)
            except (TypeError, ValueError):
                pass
            candidates.append((upgrade_image_url(strip_tracking_params(url)), "", width))

    thumbnails = getattr(entry, "media_thumbnail", None) or []
    if isinstance(thumbnails, list):
        for item in thumbnails:
            url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
            if isinstance(url, str):
                candidates.append((upgrade_image_url(strip_tracking_params(url)), "thumbnail", 200))

    image_link = getattr(entry, "image", None)
    if isinstance(image_link, dict):
        href = image_link.get("href") or image_link.get("url")
        if isinstance(href, str):
            candidates.append((upgrade_image_url(strip_tracking_params(href)), "", 300))

    if not candidates and raw_html:
        fallback = extract_first_image_url(raw_html)
        if fallback:
            candidates.append((upgrade_image_url(fallback), "", 0))

    return pick_best_image(candidates)


def extract_image_from_article_html(html: str) -> str:
    if not html:
        return ""
    for pattern in (_OG_IMAGE, _OG_IMAGE_ALT, _TWITTER_IMAGE):
        match = pattern.search(html)
        if match:
            url = (match.group(1) or match.group(2) or "").strip()
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith(("http://", "https://")) and not is_bad_image_url(url):
                return upgrade_image_url(strip_tracking_params(url))

    candidates = _images_from_html(html)
    return pick_best_image(candidates)
