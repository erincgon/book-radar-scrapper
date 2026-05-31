"""Metadata/versioning helpers for feed caching.

Reused from StreamRadar `utils/metadata.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_feed_hash(payload: list[dict[str, Any]]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_existing_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        return {}
    try:
        with meta_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Unable to read existing meta.json (%s). Recreating metadata.", exc)
        return {}


def build_meta_payload(
    feeds_payload: dict[str, list[dict[str, Any]]],
    previous_meta: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    previous_feeds = previous_meta.get("feeds", {}) if isinstance(previous_meta.get("feeds"), dict) else {}
    new_feeds: dict[str, dict[str, Any]] = {}
    changed = False

    for feed_name, payload in feeds_payload.items():
        feed_hash = compute_feed_hash(payload)
        count = len(payload)
        new_feeds[feed_name] = {"count": count, "hash": feed_hash}
        previous_hash = ((previous_feeds.get(feed_name) or {}).get("hash")) if isinstance(previous_feeds, dict) else None
        if previous_hash != feed_hash:
            changed = True

    previous_feed_names = set(previous_feeds.keys()) if isinstance(previous_feeds, dict) else set()
    if previous_feed_names != set(new_feeds.keys()):
        changed = True

    previous_version = int(previous_meta.get("version", 0) or 0)
    version = previous_version + 1 if changed else max(previous_version, 1)
    updated_at = _utc_iso_z() if changed else previous_meta.get("updated_at", _utc_iso_z())

    payload = {
        "version": version,
        "updated_at": updated_at,
        "engine": "bookradar",
        "feeds": new_feeds,
    }
    return payload, changed


def update_meta_file(meta_path: Path, feeds_payload: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    previous_meta = _read_existing_meta(meta_path)
    payload, changed = build_meta_payload(feeds_payload, previous_meta)

    if not changed and meta_path.exists():
        logger.info("meta.json unchanged. version=%s", payload["version"])
        return payload

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with meta_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    logger.info("Updated meta.json version=%s changed=%s", payload["version"], changed)
    return payload
