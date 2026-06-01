"""HTTP client with retry, timeout and optional rate limiting."""

from __future__ import annotations

import random
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import APP_CONFIG

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 BookRadarBot/1.0"
    )
}


class HTTPClient:
    """Shared HTTP client with defensive networking defaults."""

    def __init__(self) -> None:
        self.session = requests.Session()
        retry = Retry(
            total=APP_CONFIG.request_retries,
            connect=APP_CONFIG.request_retries,
            read=APP_CONFIG.request_retries,
            status=APP_CONFIG.request_retries,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            backoff_factor=APP_CONFIG.backoff_factor,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(DEFAULT_HEADERS)

    def _sleep(self, *, fast: bool) -> None:
        if fast:
            if APP_CONFIG.rss_rate_limit_seconds > 0:
                time.sleep(APP_CONFIG.rss_rate_limit_seconds)
            return
        delay = random.uniform(
            APP_CONFIG.min_rate_limit_seconds,
            APP_CONFIG.max_rate_limit_seconds,
        )
        time.sleep(delay)

    def get(self, url: str, *, fast: bool = False, **kwargs: Any) -> requests.Response:
        self._sleep(fast=fast)
        timeout = kwargs.pop("timeout", APP_CONFIG.request_timeout_seconds)
        return self.session.get(url, timeout=timeout, **kwargs)

    def head(self, url: str, *, fast: bool = False, **kwargs: Any) -> requests.Response:
        self._sleep(fast=fast)
        timeout = kwargs.pop("timeout", APP_CONFIG.request_timeout_seconds)
        return self.session.head(url, timeout=timeout, allow_redirects=True, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        self._sleep(fast=False)
        timeout = kwargs.pop("timeout", APP_CONFIG.request_timeout_seconds)
        return self.session.post(url, timeout=timeout, **kwargs)

    def fetch_html_snippet(self, url: str, *, max_bytes: int = 120_000) -> str:
        """Lightweight HTML fetch for og:image only (first chunk)."""
        try:
            response = self.get(
                url,
                fast=False,
                timeout=min(8, APP_CONFIG.request_timeout_seconds),
                stream=True,
            )
            if not response.ok:
                return ""
            ctype = response.headers.get("Content-Type", "").lower()
            if "html" not in ctype:
                return ""
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=32_768):
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size >= max_bytes:
                    break
            response.close()
            return b"".join(chunks).decode("utf-8", errors="replace")
        except Exception:
            return ""
