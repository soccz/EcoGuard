"""Strict UTF-8 JSON loading shared by the optional research boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_object(path: Path) -> dict[str, Any]:
    """Load one object while rejecting duplicate keys and non-finite numbers."""

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant in {path}: {value}")

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid strict UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload
