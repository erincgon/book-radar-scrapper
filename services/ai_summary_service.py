"""Optional AI summary generation via OpenRouter.

Supports DeepSeek and Gemini Flash models configured through OPENROUTER_MODEL.
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import APP_CONFIG, OPENROUTER_CONFIG
from utils.http_client import HTTPClient
from utils.text_cleaner import clamp_text, clean_text

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "Summarize this book/article in 120 words.\n"
    "Mention genre/topic and target audience.\n"
    "Write concise SEO-friendly English.\n\n"
    "Title: {title}\n"
    "Author: {author}\n"
    "Description: {description}"
)

SUPPORTED_MODELS = (
    "google/gemini-flash-1.5",
    "google/gemini-2.0-flash-001",
    "deepseek/deepseek-chat",
    "deepseek/deepseek-r1",
)


class AISummaryService:
    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http_client = http_client or HTTPClient()
        self.enabled = OPENROUTER_CONFIG.enabled and bool(OPENROUTER_CONFIG.api_key)

    def generate_ai_summary(self, entry: dict[str, Any]) -> str:
        existing = clean_text(entry.get("summary_ai"))
        if existing:
            return existing

        if not self.enabled:
            return ""

        title = clean_text(entry.get("title"))
        author = clean_text(entry.get("author"), fallback="Unknown")
        description = clamp_text(entry.get("description"), max_chars=800)

        if not title or not description:
            return ""

        prompt = SUMMARY_PROMPT.format(title=title, author=author, description=description)
        try:
            summary = self._call_openrouter(prompt)
            if summary:
                logger.info("AI summary generated title=%s model=%s", title, OPENROUTER_CONFIG.model)
                return clamp_text(summary, max_chars=900)
            logger.warning("AI summary empty title=%s", title)
        except Exception as exc:
            logger.exception("AI summary generation failed title=%s error=%s", title, exc)
        return ""

    def enrich_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.enabled:
            return items
        enriched: list[dict[str, Any]] = []
        for item in items:
            copy = dict(item)
            summary = self.generate_ai_summary(copy)
            if summary:
                copy["summary_ai"] = summary
            enriched.append(copy)
        return enriched

    def _call_openrouter(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_CONFIG.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://bookradar.engine",
            "X-Title": "BookRadar Engine",
        }
        payload = {
            "model": OPENROUTER_CONFIG.model,
            "messages": [
                {"role": "system", "content": "You are a concise literary editor."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 220,
            "temperature": 0.4,
        }
        response = self.http_client.post(
            OPENROUTER_CONFIG.base_url,
            json=payload,
            headers=headers,
            timeout=45,
        )
        if not response.ok:
            logger.warning(
                "OpenRouter request failed status=%s body=%s",
                response.status_code,
                response.text[:300],
            )
            return ""

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        return clean_text(content)
