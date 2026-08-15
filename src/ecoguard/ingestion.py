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
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from .jsonio import strict_json_file
from .preprocessing import (
    EXTRACTOR_ID,
    evidence_record_id,
    match_alias,
    raw_value,
)

ADAPTER_VERSION = "2.0.0"
DOCUMENT_BUNDLE_SCHEMA_VERSION = "ocr-document-bundle/1.0"
EXTRACTION_SCHEMA_VERSION = "2.0.0"


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _canonical_document_line(page: int, line: int, text: str, confidence: float) -> str:
    return json.dumps(
        [page, line, confidence, text],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value


def _confidence(value: Any, location: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"invalid line confidence at {location}")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid line confidence at {location}") from exc
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError(f"line confidence must be within [0, 1] at {location}")
    return confidence


def _positive_index(item: Any, key: str) -> int:
    if not isinstance(item, dict):
        raise ValueError(f"{key} entry must be an object")
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _reject_extra_keys(item: dict[str, Any], allowed: set[str], label: str) -> None:
    extras = sorted(set(item) - allowed)
    if extras:
        raise ValueError(f"unsupported {label} properties: {', '.join(extras)}")


def _iter_lines(document: dict[str, Any]) -> Iterable[tuple[int, int, dict[str, Any]]]:
    seen_pages: set[int] = set()
    pages = document.get("pages", [])
    if not isinstance(pages, list):
        raise ValueError(f"pages must be a list in {document['document_id']}")
    ordered_pages = sorted(pages, key=lambda item: _positive_index(item, "page"))
    for page in ordered_pages:
        _reject_extra_keys(page, {"page", "lines"}, "page")
        page_number = _positive_index(page, "page")
        if page_number in seen_pages:
            raise ValueError(
                f"invalid or duplicate page {page_number} in {document['document_id']}"
            )
        seen_pages.add(page_number)
        seen_lines: set[int] = set()
        lines = page.get("lines", [])
        if not isinstance(lines, list) or not lines:
            raise ValueError(
                "lines must be a non-empty list in "
                f"{document['document_id']} page {page_number}"
            )
        ordered_lines = sorted(lines, key=lambda item: _positive_index(item, "line"))
        for line in ordered_lines:
            _reject_extra_keys(line, {"line", "text", "confidence"}, "line")
            line_number = _positive_index(line, "line")
            if line_number in seen_lines:
                raise ValueError(
                    "invalid or duplicate line "
                    f"{line_number} on {document['document_id']} page {page_number}"
                )
            seen_lines.add(line_number)
            yield page_number, line_number, line


def extract_document_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a document-oriented OCR payload into candidate records."""
    if not isinstance(payload, dict):
        raise ValueError("document bundle must be an object")
    _reject_extra_keys(
        payload,
        {"schema_version", "case_id", "notice", "documents"},
        "document bundle",
    )
    if payload.get("schema_version") != DOCUMENT_BUNDLE_SCHEMA_VERSION:
        raise ValueError(
            "unsupported document bundle schema_version; expected "
            f"{DOCUMENT_BUNDLE_SCHEMA_VERSION}"
        )
    case_id = _require_string(payload.get("case_id"), "case_id")
    _require_string(payload.get("notice"), "notice")
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("document bundle must contain at least one document")

    document_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    document_manifest: list[dict[str, Any]] = []
    line_count = 0

    if any(not isinstance(document, dict) for document in documents):
        raise ValueError("document entry must be an object")
    ordered_documents = sorted(
        documents,
        key=lambda item: str(item.get("document_id", "")),
    )
    for document in ordered_documents:
        _reject_extra_keys(
            document,
            {"document_id", "document_type", "language", "pages"},
            "document",
        )
        document_id = _require_string(document.get("document_id"), "document_id")
        document_type = _require_string(document.get("document_type"), "document_type")
        _require_string(document.get("language"), "language")
        if document_id in document_ids:
            raise ValueError(f"duplicate document_id: {document_id}")
        document_ids.add(document_id)

        materialized_lines = list(_iter_lines(document))
        if not materialized_lines:
            raise ValueError(f"document has no OCR lines: {document_id}")
        canonical_rows = []
        for page, line_number, line in materialized_lines:
            location = f"{document_id} page {page} line {line_number}"
            text = line.get("text")
            if not isinstance(text, str):
                raise ValueError(f"line text must be a string at {location}")
            confidence = _confidence(line.get("confidence"), location)
            canonical_rows.append(
                _canonical_document_line(page, line_number, text, confidence)
            )
        canonical_text = "\n".join(canonical_rows)
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
            match, unmatched_reason = match_alias(text)
            if match is None:
                unmatched.append(
                    {
                        "document_id": document_id,
                        "page": page,
                        "line": line_number,
                        "line_sha256": line_sha256,
                        "confidence": confidence,
                        "reason": unmatched_reason,
                        "text": text,
                    }
                )
                continue

            alias, alias_start, alias_end = match
            value, value_start, value_end = raw_value(text, alias_end)
            matched_count += 1
            records.append(
                {
                    "record_id": evidence_record_id(document_id, page, line_number),
                    "document": document_id,
                    "document_type": document_type,
                    "location": f"page {page} / line {line_number}",
                    "page": page,
                    "line": line_number,
                    "label": alias,
                    "value": value,
                    "confidence": confidence,
                    "extractor": EXTRACTOR_ID,
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
        "schema_version": EXTRACTION_SCHEMA_VERSION,
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
    return extract_document_bundle(strict_json_file(path))
