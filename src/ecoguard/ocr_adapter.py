"""Provider-neutral adapters and exact field scoring for external OCR output.

EcoGuard does not implement or own an OCR engine.  This module converts three
common, local interchange formats into the line-oriented document bundle
accepted by :mod:`ecoguard.ingestion`:

* Tesseract-compatible TSV (word rows are grouped into lines),
* a small provider-neutral JSON contract, and
* plain text such as the output of ``pdftotext``.

Only Python's standard library is used.  No function performs network I/O or
invokes an OCR executable.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .ingestion import extract_document_bundle
from .jsonio import strict_json_loads

OCR_ADAPTER_VERSION = "1.0.0"
FIELD_REFERENCE_SCHEMA_VERSION = "ocr-field-reference/1.0"
FIELD_BENCHMARK_SCHEMA_VERSION = "ocr-field-benchmark/1.0"
BENCHMARK_RUN_SCHEMA_VERSION = "ocr-benchmark-run/1.0"
DEFAULT_NOTICE = (
    "External OCR/text output adapted locally; EcoGuard did not perform image OCR. "
    "Review the source engine, settings and confidence semantics separately."
)
SUPPORTED_FORMATS = frozenset({"generic-json", "pdftotext", "tesseract-tsv"})
SCOPE_KEYS = {
    "classification",
    "fixture_provenance_verified",
    "ocr_engine_invoked_by_ecoguard",
    "ocr_model_accuracy_claim",
    "purpose",
}
NEUTRAL_BENCHMARK_SCOPE = {
    "classification": "caller_supplied_reference_unverified",
    "fixture_provenance_verified": False,
    "ocr_engine_invoked_by_ecoguard": False,
    "ocr_model_accuracy_claim": False,
    "purpose": "Compare adapted output with a caller-supplied exact-field reference.",
}
SYNTHETIC_BENCHMARK_SCOPE = {
    "classification": "team_authored_synthetic_error_fixture",
    "fixture_provenance_verified": True,
    "ocr_engine_invoked_by_ecoguard": False,
    "ocr_model_accuracy_claim": False,
    "purpose": (
        "Exercise adapter, alias extraction, and field-error accounting with "
        "intentional mismatch, missing, and spurious predictions."
    ),
}


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _parsed_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _parsed_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative integer")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return parsed


def _unit_confidence(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number within [0, 1]")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number within [0, 1]") from exc
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise ValueError(f"{name} must be a finite number within [0, 1]")
    return parsed


def _source_confidence(value: Any, scale: str, name: str) -> float:
    if scale not in {"unit", "percent"}:
        raise ValueError("confidence_scale must be 'unit' or 'percent'")
    if scale == "unit":
        return _unit_confidence(value, name)
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number within [0, 100]")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number within [0, 100]") from exc
    if not math.isfinite(parsed) or not 0 <= parsed <= 100:
        raise ValueError(f"{name} must be a finite number within [0, 100]")
    return parsed / 100


def _document_bundle(
    rows: Iterable[tuple[int, int, str, float]],
    *,
    case_id: str,
    document_id: str,
    document_type: str,
    language: str,
    notice: str,
) -> dict[str, Any]:
    metadata = {
        "case_id": _required_text(case_id, "case_id"),
        "document_id": _required_text(document_id, "document_id"),
        "document_type": _required_text(document_type, "document_type"),
        "language": _required_text(language, "language"),
        "notice": _required_text(notice, "notice"),
    }
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    for page, line, text, confidence in rows:
        page_number = _positive_int(page, "page")
        line_number = _positive_int(line, "line")
        if not isinstance(text, str):
            raise ValueError("line text must be a string")
        location = (page_number, line_number)
        if location in seen:
            raise ValueError(
                f"duplicate line coordinate: page {page_number}, line {line_number}"
            )
        seen.add(location)
        by_page[page_number].append(
            {
                "line": line_number,
                "text": text,
                "confidence": _unit_confidence(confidence, "confidence"),
            }
        )
    if not seen:
        raise ValueError("OCR input contains no adaptable lines")

    pages = [
        {"page": page, "lines": sorted(lines, key=lambda item: item["line"])}
        for page, lines in sorted(by_page.items())
    ]
    return {
        "schema_version": "ocr-document-bundle/1.0",
        "case_id": metadata["case_id"],
        "notice": metadata["notice"],
        "documents": [
            {
                "document_id": metadata["document_id"],
                "document_type": metadata["document_type"],
                "language": metadata["language"],
                "pages": pages,
            }
        ],
    }


def pdftotext_to_document_bundle(
    text: str,
    *,
    case_id: str,
    document_id: str,
    document_type: str,
    language: str = "und",
    fallback_confidence: float = 0.0,
    notice: str = DEFAULT_NOTICE,
) -> dict[str, Any]:
    """Adapt form-feed-separated plain text without inventing OCR confidence.

    Blank lines are ignored and remaining lines receive stable, one-based line
    numbers per page.  ``fallback_confidence`` defaults to zero because tools
    such as ``pdftotext`` do not expose OCR confidence.
    """
    if not isinstance(text, str):
        raise ValueError("pdftotext input must be a string")
    confidence = _unit_confidence(fallback_confidence, "fallback_confidence")
    rows: list[tuple[int, int, str, float]] = []
    for page_number, page_text in enumerate(text.split("\f"), start=1):
        materialized = [line for line in page_text.splitlines() if line.strip()]
        rows.extend(
            (page_number, line_number, line, confidence)
            for line_number, line in enumerate(materialized, start=1)
        )
    return _document_bundle(
        rows,
        case_id=case_id,
        document_id=document_id,
        document_type=document_type,
        language=language,
        notice=notice,
    )


def _generic_rows(
    payload: Mapping[str, Any] | list[Any],
    *,
    confidence_scale: str,
    default_confidence: float,
) -> list[tuple[int, int, str, float]]:
    if confidence_scale not in {"unit", "percent"}:
        raise ValueError("confidence_scale must be 'unit' or 'percent'")
    fallback = _unit_confidence(default_confidence, "default_confidence")
    if isinstance(payload, list):
        flat_lines = payload
        pages = None
    elif isinstance(payload, Mapping):
        flat_lines = payload.get("lines")
        pages = payload.get("pages")
        if flat_lines is not None and pages is not None:
            raise ValueError(
                "generic JSON must contain either pages or lines, not both"
            )
    else:
        raise ValueError("generic JSON must be an object or a list of line objects")

    if pages is not None:
        return _generic_page_rows(pages, confidence_scale, fallback)
    return _generic_flat_rows(flat_lines, confidence_scale, fallback)


def _generic_page_rows(
    pages: Any, confidence_scale: str, fallback: float
) -> list[tuple[int, int, str, float]]:
    if not isinstance(pages, list):
        raise ValueError("generic JSON pages must be a list")
    rows: list[tuple[int, int, str, float]] = []
    next_lines: Counter[int] = Counter()
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, Mapping):
            raise ValueError("generic JSON page must be an object")
        page_number = _parsed_positive_int(page.get("page", page_index), "page")
        lines = page.get("lines")
        if not isinstance(lines, list):
            raise ValueError("generic JSON page lines must be a list")
        for line in lines:
            if not isinstance(line, Mapping):
                raise ValueError("generic JSON line must be an object")
            if "page" in line:
                repeated_page = _parsed_positive_int(line["page"], "page")
                if repeated_page != page_number:
                    raise ValueError(
                        "generic JSON nested line page must match its parent page"
                    )
            line_number = _next_generic_line_number(
                line, page=page_number, next_lines=next_lines
            )
            rows.append(
                _generic_line(
                    line,
                    page_number=page_number,
                    line_number=line_number,
                    confidence_scale=confidence_scale,
                    fallback=fallback,
                )
            )
    return rows


def _generic_flat_rows(
    flat_lines: Any, confidence_scale: str, fallback: float
) -> list[tuple[int, int, str, float]]:
    if not isinstance(flat_lines, list):
        raise ValueError("generic JSON must contain a lines or pages list")
    rows: list[tuple[int, int, str, float]] = []
    next_lines: Counter[int] = Counter()
    for line in flat_lines:
        if not isinstance(line, Mapping):
            raise ValueError("generic JSON line must be an object")
        page_number = _parsed_positive_int(line.get("page", 1), "page")
        line_number = _next_generic_line_number(
            line, page=page_number, next_lines=next_lines
        )
        rows.append(
            _generic_line(
                line,
                page_number=page_number,
                line_number=line_number,
                confidence_scale=confidence_scale,
                fallback=fallback,
            )
        )
    return rows


def _next_generic_line_number(
    line: Mapping[str, Any], *, page: int, next_lines: Counter[int]
) -> int:
    if line.get("line") is None:
        next_lines[page] += 1
        return next_lines[page]
    number = _parsed_positive_int(line["line"], "line")
    next_lines[page] = max(next_lines[page], number)
    return number


def _generic_line(
    line: Mapping[str, Any],
    *,
    page_number: int,
    line_number: int,
    confidence_scale: str,
    fallback: float,
) -> tuple[int, int, str, float]:
    text = line.get("text")
    if not isinstance(text, str):
        raise ValueError("generic JSON line text must be a string")
    raw_confidence = line.get("confidence")
    confidence = (
        fallback
        if raw_confidence is None
        else _source_confidence(raw_confidence, confidence_scale, "confidence")
    )
    return page_number, line_number, text, confidence


def generic_json_to_document_bundle(
    payload: Mapping[str, Any] | list[Any],
    *,
    case_id: str,
    document_id: str,
    document_type: str,
    language: str = "und",
    confidence_scale: str = "unit",
    default_confidence: float = 0.0,
    notice: str = DEFAULT_NOTICE,
) -> dict[str, Any]:
    """Adapt the documented nested or flat provider-neutral JSON contract."""
    rows = _generic_rows(
        payload,
        confidence_scale=confidence_scale,
        default_confidence=default_confidence,
    )
    return _document_bundle(
        rows,
        case_id=case_id,
        document_id=document_id,
        document_type=document_type,
        language=language,
        notice=notice,
    )


_TESSERACT_COLUMNS = {
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
}


def tesseract_tsv_to_document_bundle(
    tsv: str,
    *,
    case_id: str,
    document_id: str,
    document_type: str,
    language: str = "und",
    notice: str = DEFAULT_NOTICE,
) -> dict[str, Any]:
    """Group Tesseract TSV word rows into canonical line records.

    The output line confidence is the arithmetic mean of word confidences.
    Tesseract's block/paragraph-local line numbers are replaced with stable,
    page-local sequential line numbers required by EcoGuard ingestion.
    """
    if not isinstance(tsv, str):
        raise ValueError("Tesseract TSV input must be a string")
    reader = csv.DictReader(tsv.lstrip("\ufeff").splitlines(), delimiter="\t")
    fieldnames = reader.fieldnames or []
    if len(fieldnames) != len(set(fieldnames)):
        raise ValueError("Tesseract TSV has duplicate column names")
    columns = set(fieldnames)
    missing = sorted(_TESSERACT_COLUMNS - columns)
    if missing:
        raise ValueError(f"Tesseract TSV missing columns: {', '.join(missing)}")

    grouped: dict[tuple[int, int, int, int], list[tuple[int, str, float]]] = (
        defaultdict(list)
    )
    seen_words: set[tuple[int, int, int, int, int]] = set()
    for row_number, row in enumerate(reader, start=2):
        try:
            level = int((row.get("level") or "").strip())
        except ValueError as exc:
            raise ValueError(
                f"invalid Tesseract level at TSV row {row_number}"
            ) from exc
        if level != 5:
            continue
        word = (row.get("text") or "").strip()
        if not word:
            continue
        page = _parsed_positive_int(
            row.get("page_num"), f"page_num at row {row_number}"
        )
        block = _parsed_positive_int(
            row.get("block_num"), f"block_num at row {row_number}"
        )
        paragraph = _parsed_positive_int(
            row.get("par_num"), f"par_num at row {row_number}"
        )
        line = _parsed_positive_int(
            row.get("line_num"), f"line_num at row {row_number}"
        )
        word_number = _parsed_positive_int(
            row.get("word_num"), f"word_num at row {row_number}"
        )
        _parsed_nonnegative_int(row.get("left"), f"left at row {row_number}")
        _parsed_nonnegative_int(row.get("top"), f"top at row {row_number}")
        _parsed_positive_int(row.get("width"), f"width at row {row_number}")
        _parsed_positive_int(row.get("height"), f"height at row {row_number}")
        word_key = (page, block, paragraph, line, word_number)
        if word_key in seen_words:
            raise ValueError(
                f"duplicate Tesseract word coordinate at TSV row {row_number}"
            )
        seen_words.add(word_key)
        confidence = _source_confidence(
            row.get("conf"), "percent", f"conf at row {row_number}"
        )
        grouped[word_key[:-1]].append((word_number, word, confidence))

    output_rows: list[tuple[int, int, str, float]] = []
    page_counts: Counter[int] = Counter()
    for group_key, words in sorted(grouped.items()):
        page = group_key[0]
        page_counts[page] += 1
        ordered_words = sorted(words)
        line_text = " ".join(word for _, word, _ in ordered_words)
        mean_confidence = round(
            sum(confidence for _, _, confidence in ordered_words) / len(ordered_words),
            6,
        )
        output_rows.append((page, page_counts[page], line_text, mean_confidence))

    return _document_bundle(
        output_rows,
        case_id=case_id,
        document_id=document_id,
        document_type=document_type,
        language=language,
        notice=notice,
    )


def adapt_ocr_file(
    path: str | Path,
    *,
    input_format: str,
    case_id: str,
    document_id: str,
    document_type: str,
    language: str = "und",
    confidence_scale: str = "unit",
    default_confidence: float = 0.0,
    notice: str = DEFAULT_NOTICE,
) -> dict[str, Any]:
    """Read a local interchange file and adapt it without subprocess/network I/O."""
    if input_format not in SUPPORTED_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        raise ValueError(f"unsupported OCR input format; choose one of: {supported}")
    source = Path(path).read_text(encoding="utf-8")
    common = {
        "case_id": case_id,
        "document_id": document_id,
        "document_type": document_type,
        "language": language,
        "notice": notice,
    }
    if input_format == "tesseract-tsv":
        return tesseract_tsv_to_document_bundle(source, **common)
    if input_format == "pdftotext":
        return pdftotext_to_document_bundle(
            source,
            fallback_confidence=default_confidence,
            **common,
        )

    try:
        payload = strict_json_loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid generic OCR JSON: {exc.msg}") from exc
    return generic_json_to_document_bundle(
        payload,
        confidence_scale=confidence_scale,
        default_confidence=default_confidence,
        **common,
    )


def _comparison_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _prediction_index(
    records: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str, int], dict[str, Any]]:
    materialized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("predicted field record must be an object")
        document = _required_text(record.get("document"), "prediction document")
        label = _required_text(record.get("label"), "prediction label")
        value = record.get("value")
        if not isinstance(value, str):
            raise ValueError("prediction value must be a string")
        page = _positive_int(record.get("page"), "prediction page")
        line = _positive_int(record.get("line"), "prediction line")
        confidence = _unit_confidence(record.get("confidence"), "prediction confidence")
        materialized.append(
            {
                "document": document,
                "label": label,
                "value": value,
                "page": page,
                "line": line,
                "confidence": confidence,
                "record_id": str(record.get("record_id", "")),
            }
        )
    materialized.sort(
        key=lambda item: (
            item["document"],
            item["label"],
            item["page"],
            item["line"],
            item["record_id"],
        )
    )
    occurrences: Counter[tuple[str, str]] = Counter()
    indexed: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in materialized:
        group = (item["document"], item["label"])
        occurrences[group] += 1
        indexed[(*group, occurrences[group])] = item
    return indexed


def _reference_index(
    reference: Mapping[str, Any],
) -> dict[tuple[str, str, int], dict[str, Any]]:
    if set(reference) != {"schema_version", "case_id", "notice", "fields"}:
        raise ValueError("field reference has missing or unsupported properties")
    if reference.get("schema_version") != FIELD_REFERENCE_SCHEMA_VERSION:
        raise ValueError(
            "unsupported field reference schema_version; expected "
            f"{FIELD_REFERENCE_SCHEMA_VERSION}"
        )
    _required_text(reference.get("case_id"), "reference case_id")
    _required_text(reference.get("notice"), "reference notice")
    fields = reference.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("reference fields must be a non-empty list")
    indexed: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in fields:
        if not isinstance(item, Mapping):
            raise ValueError("reference field must be an object")
        if set(item) != {"document", "label", "occurrence", "value"}:
            raise ValueError("reference field has missing or unsupported properties")
        document = _required_text(item.get("document"), "reference document")
        label = _required_text(item.get("label"), "reference label")
        occurrence = _positive_int(item.get("occurrence"), "reference occurrence")
        value = item.get("value")
        if not isinstance(value, str):
            raise ValueError("reference value must be a string")
        key = (document, label, occurrence)
        if key in indexed:
            raise ValueError(
                "duplicate reference field identity: "
                f"{document}/{label}/{occurrence}"
            )
        indexed[key] = {
            "document": document,
            "label": label,
            "occurrence": occurrence,
            "value": value,
        }
    return indexed


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _mean_confidence(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def benchmark_fields(
    predicted_records: Iterable[Mapping[str, Any]],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Score exact field identity/value matches with explicit error categories.

    A value mismatch contributes one false positive and one false negative.
    Comparison applies Unicode NFC and collapses whitespace, but remains
    case-sensitive and performs no numeric/unit correction.
    """
    if not isinstance(reference, Mapping):
        raise ValueError("field reference must be an object")
    predicted = _prediction_index(predicted_records)
    expected = _reference_index(reference)
    true_positive = 0
    value_mismatch: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    spurious: list[dict[str, Any]] = []
    correct_confidences: list[float] = []
    incorrect_confidences: list[float] = []

    for identity in sorted(set(predicted) | set(expected)):
        prediction = predicted.get(identity)
        target = expected.get(identity)
        identity_payload = {
            "document": identity[0],
            "label": identity[1],
            "occurrence": identity[2],
        }
        if prediction is None:
            missing.append({**identity_payload, "expected": target["value"]})
            continue
        if target is None:
            spurious.append(
                {
                    **identity_payload,
                    "predicted": prediction["value"],
                    "confidence": prediction["confidence"],
                }
            )
            incorrect_confidences.append(prediction["confidence"])
            continue
        if _comparison_text(prediction["value"]) == _comparison_text(target["value"]):
            true_positive += 1
            correct_confidences.append(prediction["confidence"])
            continue
        value_mismatch.append(
            {
                **identity_payload,
                "expected": target["value"],
                "predicted": prediction["value"],
                "confidence": prediction["confidence"],
            }
        )
        incorrect_confidences.append(prediction["confidence"])

    false_positive = len(value_mismatch) + len(spurious)
    false_negative = len(value_mismatch) + len(missing)
    predicted_count = len(predicted)
    expected_count = len(expected)
    precision = _ratio(true_positive, predicted_count)
    recall = _ratio(true_positive, expected_count)
    f1_denominator = 2 * true_positive + false_positive + false_negative
    f1 = round(2 * true_positive / f1_denominator, 6) if f1_denominator else None
    return {
        "schema_version": FIELD_BENCHMARK_SCHEMA_VERSION,
        "case_id": reference["case_id"],
        "comparison": "unicode_nfc_whitespace_collapsed_case_sensitive_exact_value",
        "counts": {
            "expected_fields": expected_count,
            "predicted_fields": predicted_count,
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
        },
        "metrics": {"precision": precision, "recall": recall, "f1": f1},
        "error_counts": {
            "value_mismatch": len(value_mismatch),
            "missing": len(missing),
            "spurious": len(spurious),
        },
        "errors": {
            "value_mismatch": value_mismatch,
            "missing": missing,
            "spurious": spurious,
        },
        "confidence_summary": {
            "correct_mean": _mean_confidence(correct_confidences),
            "incorrect_prediction_mean": _mean_confidence(incorrect_confidences),
            "missing_fields_have_no_confidence": True,
        },
    }


def benchmark_document_bundle(
    document_bundle: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run EcoGuard alias extraction and field scoring on an adapted bundle."""
    if not isinstance(document_bundle, dict):
        raise ValueError("document bundle must be an object")
    if not isinstance(reference, Mapping):
        raise ValueError("field reference must be an object")
    if document_bundle.get("case_id") != reference.get("case_id"):
        raise ValueError("document bundle and field reference case_id must match")
    scope = dict(NEUTRAL_BENCHMARK_SCOPE if scope is None else scope)
    if set(scope) != SCOPE_KEYS:
        raise ValueError("benchmark scope has missing or unsupported properties")
    for field in ("classification", "purpose"):
        _required_text(scope.get(field), f"benchmark scope {field}")
    for field in (
        "fixture_provenance_verified",
        "ocr_engine_invoked_by_ecoguard",
        "ocr_model_accuracy_claim",
    ):
        if not isinstance(scope.get(field), bool):
            raise ValueError(f"benchmark scope {field} must be boolean")
    extraction = extract_document_bundle(document_bundle)
    return {
        "schema_version": BENCHMARK_RUN_SCHEMA_VERSION,
        "adapter_version": OCR_ADAPTER_VERSION,
        "case_id": extraction["case_id"],
        "scope": scope,
        "extraction_summary": extraction["summary"],
        "field_evaluation": benchmark_fields(extraction["records"], reference),
    }
