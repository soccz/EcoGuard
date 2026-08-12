"""Strict JSON decoding shared by every public input boundary."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number is outside the supported finite range")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is not allowed: {key}")
        result[key] = value
    return result


def strict_json_loads(source: str | bytes) -> Any:
    """Decode UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""
    if isinstance(source, bytes):
        try:
            source = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("JSON input must be valid UTF-8") from exc
    elif not isinstance(source, str):
        raise TypeError("JSON input must be text or UTF-8 bytes")
    return json.loads(
        source,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
        object_pairs_hook=_unique_object,
    )


def strict_json_file(path: str | Path) -> Any:
    """Read and strictly decode one UTF-8 JSON file."""
    return strict_json_loads(Path(path).read_text(encoding="utf-8"))
