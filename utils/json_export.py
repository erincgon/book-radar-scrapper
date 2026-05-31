"""JSON export and validation helpers.

Adapted from StreamRadar `utils/json_utils.py` for BookRadar schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models.book_model import REQUIRED_KEYS, validate_book_schema

_KEY_ORDER_INDEX = {name: idx for idx, name in enumerate(REQUIRED_KEYS)}


def sort_keys_canonical(payload: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    remainder = sorted(
        [(k, v) for k, v in payload.items() if k not in _KEY_ORDER_INDEX],
        key=lambda kv: kv[0],
    )
    for name in REQUIRED_KEYS:
        if name in payload:
            ordered[name] = payload[name]
    for k, v in remainder:
        ordered[k] = v
    return ordered


def write_json(path: Path, payload: list[dict[str, Any]] | dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, list):
        canon = [sort_keys_canonical(row) if isinstance(row, dict) else row for row in payload]
    else:
        canon = sort_keys_canonical(payload) if isinstance(payload, dict) else payload
    with path.open("w", encoding="utf-8") as file:
        json.dump(canon, file, ensure_ascii=False, indent=2)
        file.write("\n")


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def filter_valid_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if validate_book_schema(item)]
