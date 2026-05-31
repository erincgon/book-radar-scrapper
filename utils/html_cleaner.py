"""HTML sanitization for RSS descriptions and article excerpts."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from utils.text_cleaner import clean_text

TRACKING_QUERY_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "igshid",
        "ref",
        "ref_src",
        "ref_url",
        "cmpid",
    }
)


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    try:
        soup = BeautifulSoup(value, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", unescape(value))
    return clean_text(text)


def strip_tracking_params(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return url
    try:
        parts = urlsplit(url)
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if k.lower() not in TRACKING_QUERY_PARAMS
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ""))
    except Exception:
        return url


def sanitize_malformed_html(value: str | None) -> str:
    """Best-effort cleanup for broken RSS HTML fragments."""
    if not value:
        return ""
    text = unescape(value)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<(?!br\s*/?)[^>]+>", " ", text, flags=re.I)
    return clean_text(text)


def extract_first_image_url(html: str | None) -> str | None:
    if not html:
        return None
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    if not match:
        match = re.search(
            r'<img[^>]+(?:data-src|srcset)=["\']([^"\']+)["\']',
            html,
            flags=re.I,
        )
    if not match:
        return None
    candidate = match.group(1).split(",")[0].strip().split(" ")[0]
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    if candidate.startswith(("http://", "https://")):
        return strip_tracking_params(candidate)
    return None
