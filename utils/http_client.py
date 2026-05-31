"""HTTP client with retry, timeout and rate limiting support.

Reused from StreamRadar `utils/http_client.py` — User-Agent updated for BookRadar.
"""

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
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(DEFAULT_HEADERS)

    def _sleep_for_rate_limit(self) -> None:
        delay = random.uniform(
            APP_CONFIG.min_rate_limit_seconds,
            APP_CONFIG.max_rate_limit_seconds,
        )
        time.sleep(delay)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self._sleep_for_rate_limit()
        timeout = kwargs.pop("timeout", APP_CONFIG.request_timeout_seconds)
        return self.session.get(url, timeout=timeout, **kwargs)

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        self._sleep_for_rate_limit()
        timeout = kwargs.pop("timeout", APP_CONFIG.request_timeout_seconds)
        return self.session.head(url, timeout=timeout, allow_redirects=True, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        self._sleep_for_rate_limit()
        timeout = kwargs.pop("timeout", APP_CONFIG.request_timeout_seconds)
        return self.session.post(url, timeout=timeout, **kwargs)
