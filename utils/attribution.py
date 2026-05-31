"""Source attribution from article URLs."""

from __future__ import annotations

from urllib.parse import urlsplit

def _simplify_host(host: str) -> str:
    h = host.strip().lower().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    return h


_DOMAIN_MAP: dict[str, str] = {
    "nytimes.com": "The New York Times",
    "theguardian.com": "The Guardian",
    "kirkusreviews.com": "Kirkus Reviews",
    "bookriot.com": "Book Riot",
    "lithub.com": "Literary Hub",
    "publishersweekly.com": "Publishers Weekly",
    "tor.com": "Tor.com",
    "electricliterature.com": "Electric Literature",
    "npr.org": "NPR Books",
    "feedburner.com": "The Book Smugglers",
}


def source_from_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        host = _simplify_host(urlsplit(url).netloc)
        for domain, label in _DOMAIN_MAP.items():
            if host == domain or host.endswith("." + domain):
                return label
        token = host.split(".")[0]
        return token.replace("-", " ").title()
    except Exception:
        return ""
