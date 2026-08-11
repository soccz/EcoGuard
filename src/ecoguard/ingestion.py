"""Extract auditable field candidates from a synthetic OCR document bundle.

The adapter intentionally starts *after* image OCR.  Its input resembles the
line-oriented payload returned by an OCR/table extraction service: document
metadata, page and line numbers, raw text, and a line confidence.  Every
extracted candidate keeps a content hash and character span so downstream
normalization never loses the original evidence location.
"""

from __future__ import annotations

import json
import math
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from .preprocessing import ALIASES


ADAPTER_VERSION = "1.0.0"
BLANK_MARKERS = {"", "-", "n/a", "na", "[blank]", "(blank)", "공란", "미제출"}


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value


def _confidence(value: Any, location: str) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid line confidence at {location}") from exc
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError(f"line confidence must be within [0, 1] at {location}")
    return confidence


def _iter_lines(document: dict[str, Any]) -> Iterable[tuple[int, int, dict[str, Any]]]:
    seen_pages: set[int] = set()
    ordered_pages = sorted(
        document.get("pages", []), key=lambda item: int(item["page"])
    )
    for page in ordered_pages:
        page_number = int(page["page"])
        if page_number < 1 or page_number in seen_pages:
            raise ValueError(
                f"invalid or duplicate page {page_number} in {document['document_id']}"
            )
        seen_pages.add(page_number)
        seen_lines: set[int] = set()
        ordered_lines = sorted(
            page.get("lines", []), key=lambda item: int(item["line"])
        )
        for line in ordered_lines:
            line_number = int(line["line"])
            if line_number < 1 or line_number in seen_lines:
                raise ValueError(
                    "invalid or duplicate line "
                    f"{line_number} on {document['document_id']} page {page_number}"
                )
            seen_lines.add(line_number)
            yield page_number, line_number, line


def _match_alias(text: str) -> tuple[str, int, int] | None:
    """Return the longest known label occurring in a line.

    Longest-first matching prevents ``배출계수`` from shadowing
    ``실측 배출계수``.  The fixture deliberately keeps one field per OCR line;
    ambiguous multi-field lines are retained as unmatched evidence instead of
    guessing.
    """
    matches: list[tuple[str, int, int]] = []
    lowered = text.casefold()
    for alias in ALIASES:
        start = lowered.find(alias.casefold())
        if start >= 0:
            matches.append((alias, start, start + len(alias)))
    if not matches:
        return None
    matches.sort(key=lambda row: (-len(row[0]), row[1], row[0]))
    return matches[0]


def _raw_value(text: str, alias_end: int) -> tuple[str, int, int]:
    remainder = text[alias_end:]
    stripped = remainder.lstrip(" \t:：=|–—-")
    start = alias_end + len(remainder) - len(stripped)
    value = stripped.strip()
    if value.casefold() in BLANK_MARKERS:
        value = ""
    end = start + len(stripped.rstrip())
    return value, start, end


def extract_document_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a document-oriented OCR payload into candidate records."""
    case_id = _require_string(payload.get("case_id"), "case_id")
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("document bundle must contain at least one document")

    document_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    document_manifest: list[dict[str, Any]] = []
    line_count = 0

    ordered_documents = sorted(
        documents,
        key=lambda item: str(item.get("document_id", "")),
    )
    for document in ordered_documents:
        document_id = _require_string(document.get("document_id"), "document_id")
        document_type = _require_string(document.get("document_type"), "document_type")
        if document_id in document_ids:
            raise ValueError(f"duplicate document_id: {document_id}")
        document_ids.add(document_id)

        materialized_lines = list(_iter_lines(document))
        if not materialized_lines:
            raise ValueError(f"document has no OCR lines: {document_id}")
        canonical_text = "\n".join(
            f"{page}:{line_number}:{line['text']}"
            for page, line_number, line in materialized_lines
        )
        document_sha256 = _digest(canonical_text)
        matched_count = 0

        for page, line_number, line in materialized_lines:
            line_count += 1
            location = f"{document_id} page {page} line {line_number}"
            text = line.get("text")
            if not isinstance(text, str):
                raise ValueError(f"line text must be a string at {location}")
            confidence = _confidence(line.get("confidence"), location)
            line_sha256 = _digest(text)
            match = _match_alias(text)
            if match is None:
                unmatched.append(
                    {
                        "document_id": document_id,
                        "page": page,
                        "line": line_number,
                        "line_sha256": line_sha256,
                        "reason": "no configured field alias",
                        "text": text,
                    }
                )
                continue

            alias, alias_start, alias_end = match
            value, value_start, value_end = _raw_value(text, alias_end)
            matched_count += 1
            records.append(
                {
                    "record_id": "ev-"
                    + re.sub(r"[^a-z0-9]+", "-", document_id.casefold()).strip("-")
                    + f"-p{page:02d}-l{line_number:03d}",
                    "document": document_id,
                    "document_type": document_type,
                    "location": f"page {page} / line {line_number}",
                    "page": page,
                    "line": line_number,
                    "label": alias,
                    "value": value,
                    "confidence": confidence,
                    "extractor": "deterministic_alias_adapter_v1",
                    "source_span": {
                        "alias_start": alias_start,
                        "alias_end": alias_end,
                        "value_start": value_start,
                        "value_end": value_end,
                    },
                    "raw_line": text,
                    "line_sha256": line_sha256,
                    "document_sha256": document_sha256,
                }
            )

        document_manifest.append(
            {
                "document_id": document_id,
                "document_type": document_type,
                "language": document.get("language", "und"),
                "page_count": len({page for page, _, _ in materialized_lines}),
                "line_count": len(materialized_lines),
                "matched_line_count": matched_count,
                "sha256": document_sha256,
            }
        )

    return {
        "schema_version": "1.0.0",
        "adapter_version": ADAPTER_VERSION,
        "case_id": case_id,
        "notice": payload.get("notice", ""),
        "documents": document_manifest,
        "records": records,
        "unmatched_lines": unmatched,
        "summary": {
            "document_count": len(document_manifest),
            "line_count": line_count,
            "matched_line_count": len(records),
            "unmatched_line_count": len(unmatched),
            "extraction_coverage": round(len(records) / line_count, 4),
        },
    }


def extract_document_bundle_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return extract_document_bundle(json.load(handle))
