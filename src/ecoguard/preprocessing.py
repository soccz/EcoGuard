"""Normalize OCR candidates while preserving selection and evidence lineage."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from hashlib import sha256
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .jsonio import strict_json_file

ALIASES = {
    "총 출하 중량": "shipment_mass_t",
    "NET WT": "shipment_mass_t",
    "출하량": "shipment_mass_t",
    "M5 순중량": "m5_mass_t",
    "M12 순중량": "m12_mass_t",
    "CN code": "cn_code",
    "실측 배출계수": "actual_intensity_tco2e_per_t",
    "배출계수": "actual_intensity_tco2e_per_t",
    "M5 SEE": "m5_intensity_tco2e_per_t",
    "M12 SEE": "m12_intensity_tco2e_per_t",
    "M5 공정 직접배출": "m5_process_direct_intensity_tco2e_per_t",
    "M5 공정 간접배출": "m5_process_indirect_intensity_tco2e_per_t",
    "M5 전구물질 직접배출": "m5_precursor_direct_intensity_tco2e_per_t",
    "M5 전구물질 간접배출": "m5_precursor_indirect_intensity_tco2e_per_t",
    "M12 공정 직접배출": "m12_process_direct_intensity_tco2e_per_t",
    "M12 공정 간접배출": "m12_process_indirect_intensity_tco2e_per_t",
    "M12 전구물질 직접배출": "m12_precursor_direct_intensity_tco2e_per_t",
    "M12 전구물질 간접배출": "m12_precursor_indirect_intensity_tco2e_per_t",
    "M5 설비 ID": "m5_installation_id",
    "M12 설비 ID": "m12_installation_id",
    "M5 생산공정": "m5_production_process",
    "M12 생산공정": "m12_production_process",
    "EU 기본값": "default_intensity_tco2e_per_t",
    "CBAM 인증서 가격": "certificate_price_eur_per_tco2e",
    "시나리오 노출계수": "scenario_exposure_factor",
    "노출도 적용계수": "scenario_exposure_factor",
    "원산지 탄소가격": "carbon_price_paid_eur_per_tco2e",
    "검증서 번호": "verification_reference",
    "전기사용량": "electricity_kwh",
    "LNG 사용량": "lng_nm3",
}
BLANK_MARKERS = {"", "-", "n/a", "na", "[blank]", "(blank)", "공란", "미제출"}
SUPPORTED_FIELDS = frozenset(ALIASES.values())
EXTRACTOR_ID = "deterministic_alias_adapter_v2"


def _is_word_character(character: str) -> bool:
    return character.isalnum() or character == "_"


def _has_word_boundaries(text: str, start: int, end: int) -> bool:
    if start > 0 and _is_word_character(text[start - 1]):
        return False
    if end < len(text) and _is_word_character(text[end]):
        return False
    return True


def match_alias(text: str) -> tuple[tuple[str, int, int] | None, str]:
    """Return one unambiguous configured label at the start of an OCR line."""
    matches: list[tuple[str, int, int]] = []
    for alias in ALIASES:
        for occurrence in re.finditer(re.escape(alias), text, flags=re.IGNORECASE):
            start, end = occurrence.span()
            if _has_word_boundaries(text, start, end):
                matches.append((alias, start, end))
    leading_matches = [match for match in matches if not text[: match[1]].strip()]
    if not leading_matches:
        return None, "no configured field alias"
    leading_matches.sort(key=lambda row: (-len(row[0]), row[1], row[0]))
    selected = leading_matches[0]
    independent = [
        match
        for match in matches
        if match != selected
        and not (selected[1] <= match[1] and match[2] <= selected[2])
    ]
    if independent:
        return None, "multiple configured field aliases"
    return selected, ""


def raw_value(text: str, alias_end: int) -> tuple[str, int, int]:
    """Keep dashes as possible numeric signs while trimming label separators."""
    remainder = text[alias_end:]
    stripped = remainder.lstrip(" \t:：=|")
    start = alias_end + len(remainder) - len(stripped)
    value = stripped.strip()
    if value.casefold() in BLANK_MARKERS:
        value = ""
    end = start + len(stripped.rstrip())
    return value, start, end


def evidence_record_id(document_id: str, page: int, line: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", document_id.casefold()).strip("-")
    return f"ev-{slug}-p{page:02d}-l{line:03d}"


ITEM_COMPONENTS = (
    "process_direct",
    "process_indirect",
    "precursor_direct",
    "precursor_indirect",
)
ITEM_IDS = ("m5", "m12")

REQUIRED_FIELDS = {
    "shipment_mass_t",
    "cn_code",
    "actual_intensity_tco2e_per_t",
    "default_intensity_tco2e_per_t",
    "certificate_price_eur_per_tco2e",
    "scenario_exposure_factor",
    "carbon_price_paid_eur_per_tco2e",
    "verification_reference",
}
for _item in ITEM_IDS:
    REQUIRED_FIELDS.update(
        {
            f"{_item}_mass_t",
            f"{_item}_intensity_tco2e_per_t",
            f"{_item}_installation_id",
            f"{_item}_production_process",
            *(
                f"{_item}_{component}_intensity_tco2e_per_t"
                for component in ITEM_COMPONENTS
            ),
        }
    )


SELECTION_STRATEGY = "validity > document authority > confidence > stable input order"
EXTRACTION_SCHEMA_VERSION = "2.0.0"
NORMALIZED_SCHEMA_VERSION = "3.0.0"


DEFAULT_POLICY: dict[str, Any] = {
    "policy_id": "ecoguard-normalization-v2",
    "selection_strategy": SELECTION_STRATEGY,
    "default_source_authority": 10,
    "source_authority": {
        "scenario_assumptions": 100,
        "cbam_product_sheet": 95,
        "commercial_invoice": 90,
        "packing_list": 85,
        "supplier_declaration": 85,
        "energy_memo": 45,
        "operator_memo": 20,
        "unknown": 10,
    },
    "field_overrides": {
        "shipment_mass_t": {
            "absolute_conflict_tolerance": "0.1",
            "source_authority": {
                "commercial_invoice": 100,
                "packing_list": 90,
                "operator_memo": 20,
            },
        },
        "actual_intensity_tco2e_per_t": {
            "absolute_conflict_tolerance": "0.001",
            "source_authority": {
                "cbam_product_sheet": 100,
                "operator_memo": 20,
            },
        },
    },
}


@dataclass(frozen=True)
class Candidate:
    sequence: int
    record_id: str
    field: str
    raw_label: str
    raw_line: str | None
    normalized_value: str | None
    unit: str | None
    transformation: str
    raw_value: str
    confidence: float
    authority_rank: int
    document: str
    document_type: str
    location: str
    page: int | None
    line: int | None
    source_span: dict[str, int] | None
    line_sha256: str | None
    document_sha256: str | None
    extractor: str


def load_policy(path: str | Path) -> dict[str, Any]:
    policy = strict_json_file(path)
    _validate_policy(policy)
    return policy


_POLICY_KEYS = {
    "policy_id",
    "selection_strategy",
    "default_source_authority",
    "source_authority",
    "field_overrides",
}
_FIELD_OVERRIDE_KEYS = {"absolute_conflict_tolerance", "source_authority"}


def _require_exact_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(value))
    extras = sorted(set(value) - required)
    if missing:
        raise ValueError(f"{label} is missing: {', '.join(missing)}")
    if extras:
        raise ValueError(f"unsupported {label} properties: {', '.join(extras)}")


def _validate_authority_map(value: Any, label: str) -> None:
    if not isinstance(value, dict) or any(
        isinstance(rank, bool) or not isinstance(rank, int) or rank < 0
        for rank in value.values()
    ):
        raise ValueError(f"{label} values must be non-negative integers")


def _validate_field_override(field: str, config: Any) -> None:
    if field not in SUPPORTED_FIELDS:
        raise ValueError(f"unsupported normalization field override: {field}")
    if not isinstance(config, dict):
        raise ValueError(f"field override must be an object: {field}")
    extras = sorted(set(config) - _FIELD_OVERRIDE_KEYS)
    if extras:
        raise ValueError(
            f"unsupported field override properties for {field}: {', '.join(extras)}"
        )
    _validate_authority_map(
        config.get("source_authority", {}), f"field source_authority: {field}"
    )
    tolerance = config.get("absolute_conflict_tolerance", "0")
    if (
        not isinstance(tolerance, str)
        or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", tolerance) is None
    ):
        raise ValueError(f"invalid conflict tolerance for {field}")


def _validate_policy(policy: dict[str, Any]) -> None:
    if not isinstance(policy, dict):
        raise ValueError("normalization policy must be an object")
    _require_exact_keys(policy, _POLICY_KEYS, "normalization policy")
    if not isinstance(policy.get("policy_id"), str) or not policy["policy_id"].strip():
        raise ValueError("normalization policy requires policy_id")
    strategy = policy.get("selection_strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        raise ValueError("normalization policy requires selection_strategy")
    if strategy != SELECTION_STRATEGY:
        raise ValueError(f"unsupported normalization selection_strategy: {strategy}")
    default_authority = policy.get("default_source_authority", 0)
    if (
        isinstance(default_authority, bool)
        or not isinstance(default_authority, int)
        or default_authority < 0
    ):
        raise ValueError("default_source_authority must be a non-negative integer")
    _validate_authority_map(policy["source_authority"], "source_authority")
    overrides = policy["field_overrides"]
    if not isinstance(overrides, dict):
        raise ValueError("field_overrides must be an object")
    for field, config in overrides.items():
        _validate_field_override(field, config)


_NUMBER_GRAMMAR = r"[-+]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
_NUMBER_PATTERN = re.compile(_NUMBER_GRAMMAR)
_NUMERIC_TOKEN_BODY = r"(?:[0-9][0-9A-Za-z.,+-]*|\.[0-9][0-9A-Za-z.,+-]*)"
_NUMERIC_TOKEN_PATTERN = re.compile(
    r"(?<![0-9A-Za-z.,+-])"
    rf"(?:[-+][ \t]*)?{_NUMERIC_TOKEN_BODY}"
    r"(?![0-9A-Za-z.,+-])"
)
_ACCOUNTING_NUMBER_PATTERN = re.compile(
    rf"(?<![0-9A-Za-z.,+-])\([ \t]*{_NUMBER_GRAMMAR}[ \t]*\)" r"(?![0-9A-Za-z.,+-])"
)
_CN_CODE_PATTERN = re.compile(
    r"(?:[0-9]{8}|[0-9]{4}(?P<separator>[ .-])[0-9]{2}(?P=separator)[0-9]{2})"
)
_MASS_UNIT_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?:kg(?:s)?|mt|t|tonnes?|metric\s+tons?)"
    r"(?![0-9A-Za-z])|톤(?![가-힣])",
    re.IGNORECASE,
)
_NON_METRIC_TON_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:us|short|long|imperial)\s+(?:tons?|tonnes?)(?![A-Za-z])",
    re.IGNORECASE,
)
_CURRENCY_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:AUD|CAD|CHF|CNY|DKK|EUR|GBP|HKD|INR|JPY|KRW|NOK|"
    r"NZD|PLN|RMB|RUB|SEK|SGD|TRY|USD|ZAR)(?![A-Za-z])|[€$£¥￥₩]",
    re.IGNORECASE,
)
_INTENSITY_UNIT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:kg|t)\s*co2e?\s*(?:/|per\s*)" r"(?:tonne|ton|kg|t)(?![A-Za-z])",
    re.IGNORECASE,
)
_CARBON_PRICE_UNIT_PATTERN = re.compile(
    r"(?:/|(?<![A-Za-z])per)\s*(?:tonne|ton|kg|t)\s*co2e(?![A-Za-z])",
    re.IGNORECASE,
)
_ENERGY_UNIT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:[kmgt]?wh|[kmgt]?w|[kmgt]?j|btu)(?![A-Za-z])",
    re.IGNORECASE,
)
_GAS_VOLUME_UNIT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:nm[3³]|sm[3³]|m[3³])(?![0-9A-Za-z])",
    re.IGNORECASE,
)
_NEGATED_VALUE_PATTERN = re.compile(
    r"\bnot\b|해당\s*없음|아님|미적용|제외",
    re.IGNORECASE,
)
_BOUND_VALUE_PATTERN = re.compile(
    r"[<>≤≥]|(?<![A-Za-z])(?:"
    r"at\s+most|at\s+least|at\s+or\s+(?:below|above)|up\s+to|"
    r"no\s+(?:more|less)\s+than|(?:less|more|greater)\s+than|"
    r"under|over|above|below|(?:upper|lower)\s+limit|not\s+exceed(?:ing)?|"
    r"maximum|minimum|max|min"
    r")(?![A-Za-z])|이하|이상|미만|초과|최대|최소|넘지\s*않|상한|하한",
    re.IGNORECASE,
)
_NEGATIVE_WORD_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:minus|negative)(?![A-Za-z])|마이너스|음수",
    re.IGNORECASE,
)
_SCALE_VALUE_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:thousand|million|billion|k)(?![A-Za-z])|"
    r"(?<![가-힣])(?:백만|천|만)(?![가-힣])",
    re.IGNORECASE,
)
_SLASH_EQUIVALENTS = {"∕", "⁄", "⧸"}


def _canonical_numeric_view(value: str) -> str:
    """Build a parse-only NFKC view and canonicalize Unicode minus signs."""
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(
        (
            "/"
            if character in _SLASH_EQUIVALENTS
            else (
                "-"
                if unicodedata.category(character) == "Pd"
                or "MINUS SIGN" in unicodedata.name(character, "")
                else character
            )
        )
        for character in normalized
    )


def _has_compound_unit_tail(raw_tail: str) -> bool:
    """Fail closed on an explicit second-dimension delimiter after a unit.

    Slash, hyphen, and ``per`` are structural signals rather than natural-
    language unit names. Once one follows the recognized unit, reject the
    value even when the remainder is empty, whitespace, or malformed.
    """
    tail = _canonical_numeric_view(raw_tail).lstrip()
    return tail.startswith(("/", "-")) or tail.casefold().startswith("per")


def _has_unsupported_compatibility_number(value: str) -> bool:
    allowed_positions = {
        match.end() - 1
        for match in _GAS_VOLUME_UNIT_PATTERN.finditer(value)
        if match.group(0).casefold() == "nm³"
    }
    return any(
        unicodedata.category(character) == "No" and index not in allowed_positions
        for index, character in enumerate(value)
    )


def _number(value: str) -> Decimal:
    """Parse exactly one conservative decimal token from OCR-after text.

    Accepted syntax is ``[+-]?(DIGITS|D{1,3}(,DDD)+)(.DIGITS)?``.  The
    candidate scanner deliberately keeps malformed numeric-looking tokens
    whole, so leading-decimal and exponent notation cannot be partially
    reinterpreted as an unrelated integer. Explicit comparison and limit
    expressions are rejected because treating a bound as an exact value would
    change its meaning; this guards structural phrases instead of attempting
    to enumerate arbitrary surrounding prose.
    """
    if _has_unsupported_compatibility_number(value):
        raise ValueError(f"unsupported compatibility numeric token: {value!r}")
    parse_value = _canonical_numeric_view(value)
    semantic_markers = (
        (_NEGATED_VALUE_PATTERN, "negated"),
        (_BOUND_VALUE_PATTERN, "bounded"),
        (_NEGATIVE_WORD_PATTERN, "word-signed"),
        (_SCALE_VALUE_PATTERN, "scaled"),
    )
    for pattern, classification in semantic_markers:
        if pattern.search(parse_value) is not None:
            raise ValueError(
                f"unsupported {classification} numeric evidence: {value!r}"
            )
    if _ACCOUNTING_NUMBER_PATTERN.search(parse_value) is not None:
        raise ValueError(f"unsupported accounting-style numeric token: {value!r}")
    tokens = [match.group(0) for match in _NUMERIC_TOKEN_PATTERN.finditer(parse_value)]
    if not tokens:
        raise ValueError(f"numeric value not found: {value!r}")
    unsupported = [
        token for token in tokens if _NUMBER_PATTERN.fullmatch(token) is None
    ]
    if unsupported:
        raise ValueError(
            f"unsupported numeric token {unsupported[0]!r} in value: {value!r}"
        )
    if len(tokens) != 1:
        raise ValueError(f"ambiguous numeric value: {value!r}")
    return Decimal(tokens[0].replace(",", ""))


def _cn_code(value: str) -> str:
    """Accept one 8-digit CN code, optionally grouped as 4-2-2."""
    stripped = " ".join(value.strip().split())
    if _CN_CODE_PATTERN.fullmatch(stripped) is None:
        raise ValueError(f"invalid or ambiguous CN code: {value!r}")
    return re.sub(r"[^0-9]", "", stripped)


def _single_recognized_token(
    raw: str,
    pattern: re.Pattern[str],
    label: str,
    *,
    reject_compound_tail: bool = True,
) -> str:
    matches = list(pattern.finditer(raw))
    if not matches:
        raise ValueError(f"unsupported or missing {label}: {raw!r}")
    if len(matches) != 1:
        raise ValueError(f"ambiguous {label}: {raw!r}")
    match = matches[0]
    if re.search(r"\bnot\s*$", raw[: match.start()], re.IGNORECASE):
        raise ValueError(f"negated {label}: {raw!r}")
    if reject_compound_tail and _has_compound_unit_tail(raw[match.end() :]):
        raise ValueError(f"compound {label} is unsupported: {raw!r}")
    return re.sub(r"\s+", "", match.group(0)).casefold()


def _provenance_span_error(record: dict[str, Any]) -> str | None:
    raw_line = record["raw_line"]
    span = record["source_span"]
    if not isinstance(raw_line, str) or not isinstance(span, dict):
        return "adapter raw line and source span have invalid types"
    span_fields = ("alias_start", "alias_end", "value_start", "value_end")
    if any(
        isinstance(span.get(field), bool) or not isinstance(span.get(field), int)
        for field in span_fields
    ):
        return "adapter source span must contain integer offsets"
    alias_start, alias_end, value_start, value_end = (
        span[field] for field in span_fields
    )
    if not (0 <= alias_start < alias_end <= value_start <= value_end <= len(raw_line)):
        return "adapter source span is outside the raw line"
    if (
        raw_line[alias_start:alias_end].casefold()
        != str(record.get("label", "")).casefold()
    ):
        return "adapter alias span does not match the extracted label"
    raw_value = str(record.get("value", ""))
    spanned_value = raw_line[value_start:value_end]
    if raw_value:
        if spanned_value != raw_value:
            return "adapter value span does not match the extracted value"
    elif spanned_value.strip().casefold() not in BLANK_MARKERS:
        return "adapter blank value does not match a blank marker"
    expected_line_hash = sha256(raw_line.encode("utf-8")).hexdigest()
    if record["line_sha256"] != expected_line_hash:
        return "adapter line hash does not match the raw line"
    if not re.fullmatch(r"[0-9a-f]{64}", str(record["document_sha256"])):
        return "adapter document hash must be a lowercase SHA-256"
    return None


def _provenance_document_error(
    record: dict[str, Any],
    document_hashes: dict[str, str] | None,
    invalid_documents: set[str],
) -> str | None:
    if document_hashes is None:
        return None
    document = str(record.get("document", ""))
    if document not in document_hashes:
        return "adapter evidence document is absent from the document manifest"
    if document in invalid_documents:
        return "adapter document content does not reproduce the document manifest"
    if record["document_sha256"] != document_hashes[document]:
        return "adapter document hash does not match the document manifest"
    return None


def _provenance_error(
    record: dict[str, Any],
    document_hashes: dict[str, str] | None,
    invalid_documents: set[str],
) -> str | None:
    """Validate adapter provenance when any adapter lineage field is supplied."""
    lineage_fields = ("raw_line", "source_span", "line_sha256", "document_sha256")
    if not any(field in record for field in lineage_fields):
        return None
    if any(field not in record for field in lineage_fields):
        return "adapter provenance must include raw line, span, and both hashes"
    return _provenance_span_error(record) or _provenance_document_error(
        record, document_hashes, invalid_documents
    )


DOCUMENT_MANIFEST_KEYS = {
    "document_id",
    "document_type",
    "language",
    "page_count",
    "line_count",
    "matched_line_count",
    "sha256",
}


def _validate_document_manifest(document: dict[str, Any]) -> tuple[str, str]:
    if set(document) != DOCUMENT_MANIFEST_KEYS:
        raise ValueError("source document manifest has unsupported properties")
    document_id = document.get("document_id")
    document_type = document.get("document_type")
    language = document.get("language")
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("source document manifest requires document_id")
    if not isinstance(document_type, str) or not document_type.strip():
        raise ValueError(f"source document manifest requires type: {document_id}")
    if not isinstance(language, str) or not language.strip():
        raise ValueError(f"source document manifest requires language: {document_id}")
    counts = (
        document.get("page_count"),
        document.get("line_count"),
        document.get("matched_line_count"),
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
        raise ValueError(f"source document manifest has invalid counts: {document_id}")
    page_count, line_count, matched_line_count = counts
    if page_count < 1 or line_count < 1 or not 0 <= matched_line_count <= line_count:
        raise ValueError(f"source document manifest has invalid counts: {document_id}")
    digest = document.get("sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
        raise ValueError(f"invalid source document manifest hash: {document_id}")
    return document_id, str(digest)


def _manifest_hashes(documents: list[Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("source document manifest entries must be objects")
        document_id, digest = _validate_document_manifest(document)
        if document_id in hashes:
            raise ValueError(f"duplicate source document manifest id: {document_id}")
        hashes[document_id] = digest
    return hashes


def _line_inventory(
    payload: dict[str, Any],
) -> dict[str, list[tuple[Any, Any, Any, Any]]]:
    lines_by_document: dict[str, list[tuple[Any, Any, Any, Any]]] = {}

    def add_line(entry: Any, document_key: str, text_key: str) -> None:
        if not isinstance(entry, dict):
            return
        required = (document_key, "page", "line", text_key, "confidence")
        if not all(key in entry for key in required):
            return
        lines_by_document.setdefault(str(entry[document_key]), []).append(
            (entry["page"], entry["line"], entry[text_key], entry["confidence"])
        )

    for record in payload.get("records", []):
        add_line(record, "document", "raw_line")
    for line in payload.get("unmatched_lines", []):
        add_line(line, "document_id", "text")
    return lines_by_document


def _source_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep the synthetic OCR lines needed to re-check lineage downstream."""
    lines: list[dict[str, Any]] = []
    for record in payload.get("records", []):
        if not isinstance(record, dict) or "raw_line" not in record:
            continue
        lines.append(
            {
                "document_id": record.get("document"),
                "page": record.get("page"),
                "line": record.get("line"),
                "text": record.get("raw_line"),
                "line_sha256": record.get("line_sha256"),
                "confidence": record.get("confidence"),
            }
        )
    for unmatched in payload.get("unmatched_lines", []):
        if not isinstance(unmatched, dict) or "text" not in unmatched:
            continue
        lines.append(
            {
                "document_id": unmatched.get("document_id"),
                "page": unmatched.get("page"),
                "line": unmatched.get("line"),
                "text": unmatched.get("text"),
                "line_sha256": unmatched.get("line_sha256"),
                "confidence": unmatched.get("confidence"),
            }
        )
    return sorted(
        lines,
        key=lambda item: (
            str(item.get("document_id", "")),
            item.get("page", 0),
            item.get("line", 0),
        ),
    )


def _document_content_matches(
    lines: list[tuple[Any, Any, Any, Any]],
    manifest: dict[str, Any],
    expected_hash: str,
) -> bool:
    invalid_line_shape = any(
        isinstance(page, bool)
        or isinstance(line, bool)
        or not isinstance(page, int)
        or not isinstance(line, int)
        or page < 1
        or line < 1
        or not isinstance(text, str)
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
        for page, line, text, confidence in lines
    )
    if len(lines) != manifest.get("line_count") or invalid_line_shape:
        return False
    coordinates = [(page, line) for page, line, _text, _confidence in lines]
    if len(coordinates) != len(set(coordinates)):
        return False
    canonical_text = "\n".join(
        json.dumps(
            [page, line, confidence, text],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for page, line, text, confidence in sorted(lines)
    )
    return sha256(canonical_text.encode("utf-8")).hexdigest() == expected_hash


def _document_integrity(
    payload: dict[str, Any],
) -> tuple[dict[str, str] | None, set[str]]:
    documents = payload.get("documents")
    if documents is None:
        return None, set()
    if not isinstance(documents, list):
        raise ValueError("source document manifest must be a list")
    hashes = _manifest_hashes(documents)
    lines_by_document = _line_inventory(payload)

    manifest_by_id = {document["document_id"]: document for document in documents}
    invalid_documents = {
        document_id
        for document_id, expected_hash in hashes.items()
        if not _document_content_matches(
            lines_by_document.get(document_id, []),
            manifest_by_id[document_id],
            expected_hash,
        )
    }
    return hashes, invalid_documents


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _normalize_mass(raw: str, value: Decimal) -> tuple[str, str, str]:
    if _NON_METRIC_TON_PATTERN.search(raw) is not None:
        raise ValueError(f"unsupported non-metric mass unit: {raw!r}")
    unit = _single_recognized_token(raw, _MASS_UNIT_PATTERN, "mass unit")
    if unit in {"kg", "kgs"}:
        value /= Decimal("1000")
        transformation = "kg_to_t"
    else:
        transformation = "identity_tonnes"
    return _plain(value), "t", transformation


def _normalize_intensity(raw: str, value: Decimal) -> tuple[str, str, str]:
    unit = _single_recognized_token(
        raw, _INTENSITY_UNIT_PATTERN, "emission-intensity unit"
    )
    if re.fullmatch(r"tco2e?(?:/(?:t|ton|tonne)|per(?:t|ton|tonne))", unit) is None:
        raise ValueError(f"unsupported emission-intensity unit: {raw!r}")
    return _plain(value), "tCO2e/t", "normalize_emission_intensity_unit"


def _normalize_carbon_price(raw: str, value: Decimal) -> tuple[str, str, str]:
    currency = _single_recognized_token(
        raw,
        _CURRENCY_PATTERN,
        "currency",
        reject_compound_tail=False,
    )
    if currency not in {"eur", "€"}:
        raise ValueError(f"unsupported carbon-price currency: {raw!r}")
    unit = _single_recognized_token(
        raw, _CARBON_PRICE_UNIT_PATTERN, "carbon-price unit"
    )
    if (
        re.fullmatch(
            r"(?:/|per)(?:t|ton|tonne)co2e",
            unit,
        )
        is None
    ):
        raise ValueError(f"unsupported carbon-price unit: {raw!r}")
    return _plain(value), "EUR/tCO2e", "normalize_eur_per_tco2e"


def _normalize_ratio(raw: str, value: Decimal) -> tuple[str, str, str]:
    if "%" in raw:
        value /= Decimal("100")
        transformation = "percent_to_ratio"
    else:
        transformation = "identity_ratio"
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError("scenario exposure factor must be within [0, 1]")
    return _plain(value), "ratio", transformation


def _normalize(field: str, raw: str) -> tuple[str | None, str | None, str]:
    stripped = " ".join(raw.strip().split())
    if field == "verification_reference":
        return (stripped or None), None, "trim_blank_to_null"
    if field.endswith("_installation_id") or field.endswith("_production_process"):
        if not stripped:
            return None, None, "trim_blank_to_null"
        return stripped.upper(), None, "trim_and_uppercase"
    if field == "cn_code":
        return _cn_code(raw), None, "strip_non_digits"

    value = _number(raw)
    if field.endswith("_mass_t"):
        return _normalize_mass(raw, value)
    if field.endswith("_intensity_tco2e_per_t"):
        return _normalize_intensity(raw, value)
    if field in {"certificate_price_eur_per_tco2e", "carbon_price_paid_eur_per_tco2e"}:
        return _normalize_carbon_price(raw, value)
    if field == "scenario_exposure_factor":
        return _normalize_ratio(raw, value)
    if field == "electricity_kwh":
        unit = _single_recognized_token(raw, _ENERGY_UNIT_PATTERN, "electricity unit")
        if unit != "kwh":
            raise ValueError(f"unsupported electricity unit: {raw!r}")
        return _plain(value), "kWh", "normalize_kwh"
    if field == "lng_nm3":
        unit = _single_recognized_token(
            raw, _GAS_VOLUME_UNIT_PATTERN, "gas-volume unit"
        )
        if unit not in {"nm3", "nm³"}:
            raise ValueError(f"unsupported gas-volume unit: {raw!r}")
        return _plain(value), "Nm3", "normalize_nm3"
    raise KeyError(field)


def _authority(policy: dict[str, Any], field: str, document_type: str) -> int:
    override = policy.get("field_overrides", {}).get(field, {})
    field_authority = override.get("source_authority", {})
    if document_type in field_authority:
        return int(field_authority[document_type])
    return int(
        policy.get("source_authority", {}).get(
            document_type,
            policy.get("default_source_authority", 0),
        )
    )


def _selection_key(candidate: Candidate) -> tuple[bool, int, float, int]:
    return (
        candidate.normalized_value is not None,
        candidate.authority_rank,
        candidate.confidence,
        -candidate.sequence,
    )


def _tolerance(policy: dict[str, Any], field: str) -> Decimal:
    raw = (
        policy.get("field_overrides", {})
        .get(field, {})
        .get("absolute_conflict_tolerance", "0")
    )
    return Decimal(str(raw))


def _difference(left: str, right: str) -> Decimal | None:
    try:
        return abs(Decimal(left) - Decimal(right))
    except InvalidOperation:
        return None


def _candidate_from_record(
    record: dict[str, Any],
    index: int,
    policy: dict[str, Any],
    document_hashes: dict[str, str] | None,
    invalid_documents: set[str],
) -> tuple[Candidate | None, list[dict[str, Any]]]:
    label = record["label"]
    if label not in ALIASES:
        return None, [
            {
                "code": "unknown_label",
                "severity": "review",
                "message": f"정규화 규칙이 없는 라벨: {label}",
                "source": {
                    "document": record["document"],
                    "location": record["location"],
                },
            }
        ]

    field = ALIASES[label]
    record_id = str(record.get("record_id", f"record-{index:03d}"))
    candidate_issues: list[dict[str, Any]] = []
    try:
        value, unit, transformation = _normalize(field, str(record["value"]))
    except ValueError as exc:
        value, unit, transformation = None, None, "parse_failed"
        candidate_issues.append(
            {
                "code": "parse_failure",
                "severity": "review",
                "field": field,
                "message": str(exc),
                "source": {
                    "document": record["document"],
                    "location": record["location"],
                    "record_id": record_id,
                },
            }
        )

    provenance_error = _provenance_error(
        record,
        document_hashes,
        invalid_documents,
    )
    if provenance_error is not None:
        value, unit, transformation = None, None, "provenance_failed"
        candidate_issues.append(
            {
                "code": "provenance_integrity_failure",
                "severity": "high",
                "field": field,
                "message": provenance_error,
                "source": {
                    "document": record["document"],
                    "location": record["location"],
                    "record_id": record_id,
                },
            }
        )

    try:
        confidence = (
            float("nan")
            if isinstance(record["confidence"], bool)
            else float(record["confidence"])
        )
    except (TypeError, ValueError):
        confidence = float("nan")
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        candidate_issues.append(
            {
                "code": "invalid_confidence",
                "severity": "review",
                "field": field,
                "message": "신뢰도는 0과 1 사이의 유한한 값이어야 합니다.",
                "source": {
                    "document": record["document"],
                    "location": record["location"],
                },
            }
        )
        confidence = 0.0
        if value is not None:
            value, unit, transformation = None, None, "confidence_invalid"

    document_type = str(record.get("document_type", "unknown"))
    return (
        Candidate(
            sequence=index,
            record_id=record_id,
            field=field,
            raw_label=label,
            raw_line=record.get("raw_line"),
            normalized_value=value,
            unit=unit,
            transformation=transformation,
            raw_value=str(record["value"]),
            confidence=confidence,
            authority_rank=_authority(policy, field, document_type),
            document=str(record["document"]),
            document_type=document_type,
            location=str(record["location"]),
            page=record.get("page"),
            line=record.get("line"),
            source_span=record.get("source_span"),
            line_sha256=record.get("line_sha256"),
            document_sha256=record.get("document_sha256"),
            extractor=str(record.get("extractor", "ocr_adapter_boundary")),
        ),
        candidate_issues,
    )


def _partition_alternatives(
    selected: Candidate, ranked: list[Candidate], tolerance: Decimal
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    material: list[dict[str, Any]] = []
    equivalent: list[dict[str, Any]] = []
    if selected.normalized_value is None:
        return material, equivalent

    for candidate in ranked:
        if (
            candidate.record_id == selected.record_id
            or candidate.normalized_value is None
            or candidate.normalized_value == selected.normalized_value
        ):
            continue
        delta = _difference(selected.normalized_value, candidate.normalized_value)
        comparison = {
            "record_id": candidate.record_id,
            "value": candidate.normalized_value,
            "document": candidate.document,
            "absolute_difference": str(delta) if delta is not None else None,
        }
        target = equivalent if delta is not None and delta <= tolerance else material
        target.append(comparison)
    return material, equivalent


def _record_input_status(
    records: list[Any],
    issues: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    if records:
        checks.append(
            {
                "check_id": "input.non_empty",
                "status": "pass",
                "observed": len(records),
            }
        )
        return
    issues.append(
        {
            "code": "empty_input",
            "severity": "high",
            "message": "정규화할 입력 레코드가 없습니다.",
        }
    )
    checks.append(
        {
            "check_id": "input.non_empty",
            "status": "fail",
            "message": "No candidate records were supplied.",
        }
    )


def normalize_records(
    payload: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return selected values, every candidate, lineage, and a validation ledger."""
    adapter_keys = {"adapter_version", "documents", "unmatched_lines", "schema_version"}
    if adapter_keys.intersection(payload) and payload.get("schema_version") != (
        EXTRACTION_SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported extracted evidence schema_version; expected "
            f"{EXTRACTION_SCHEMA_VERSION}"
        )
    active_policy = DEFAULT_POLICY if policy is None else policy
    _validate_policy(active_policy)
    grouped: dict[str, list[Candidate]] = {}
    issues: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise ValueError("candidate records must be a list")
    document_hashes, invalid_documents = _document_integrity(payload)
    _record_input_status(records, issues, checks)

    record_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"candidate record {index} must be an object")
        record_id = str(record.get("record_id", f"record-{index:03d}"))
        if not record_id.strip():
            raise ValueError("record_id must be a non-blank string")
        if record_id in record_ids:
            raise ValueError(f"duplicate record_id: {record_id}")
        record_ids.add(record_id)
        candidate, candidate_issues = _candidate_from_record(
            record,
            index,
            active_policy,
            document_hashes,
            invalid_documents,
        )
        issues.extend(candidate_issues)
        if candidate is None:
            rejected_records.append(dict(record))
            continue
        grouped.setdefault(candidate.field, []).append(candidate)

    fields: dict[str, Any] = {}
    for field, candidates in sorted(grouped.items()):
        ranked = sorted(candidates, key=_selection_key, reverse=True)
        selected = ranked[0]
        serialized_candidates = []
        for rank, candidate in enumerate(ranked, start=1):
            serialized = asdict(candidate)
            serialized["selection_rank"] = rank
            serialized["selected"] = candidate.record_id == selected.record_id
            serialized_candidates.append(serialized)
        selected_source = {
            "document": selected.document,
            "document_type": selected.document_type,
            "location": selected.location,
            "page": selected.page,
            "line": selected.line,
            "record_id": selected.record_id,
            "raw_label": selected.raw_label,
            "raw_value": selected.raw_value,
            "confidence": selected.confidence,
            "authority_rank": selected.authority_rank,
            "extractor": selected.extractor,
            "source_span": selected.source_span,
            "line_sha256": selected.line_sha256,
            "document_sha256": selected.document_sha256,
        }
        fields[field] = {
            "value": selected.normalized_value,
            "unit": selected.unit,
            "transformation": selected.transformation,
            "selected_from": selected_source,
            "selection": {
                "policy_id": active_policy["policy_id"],
                "strategy": active_policy.get("selection_strategy"),
                "reason": (
                    "highest-ranked parseable candidate by document authority; "
                    "confidence and stable input order break ties"
                ),
                "candidate_count": len(candidates),
            },
            "candidates": serialized_candidates,
        }

        tolerance = _tolerance(active_policy, field)
        material_alternatives, equivalent_alternatives = _partition_alternatives(
            selected, ranked, tolerance
        )
        if material_alternatives:
            issues.append(
                {
                    "code": "cross_document_conflict",
                    "severity": "review",
                    "field": field,
                    "selected": selected.normalized_value,
                    "tolerance": str(tolerance),
                    "alternatives": material_alternatives,
                    "message": "허용오차를 넘는 문서 간 값 차이가 있어 원본 확인이 필요합니다.",
                }
            )
            checks.append(
                {
                    "check_id": f"consistency.{field}",
                    "status": "review",
                    "selected": selected.normalized_value,
                    "tolerance": str(tolerance),
                    "material_alternative_count": len(material_alternatives),
                }
            )
        else:
            checks.append(
                {
                    "check_id": f"consistency.{field}",
                    "status": "pass",
                    "candidate_count": len(candidates),
                    "tolerance": str(tolerance),
                }
            )
        if equivalent_alternatives:
            observations.append(
                {
                    "code": "within_tolerance_variance",
                    "field": field,
                    "selected": selected.normalized_value,
                    "tolerance": str(tolerance),
                    "alternatives": equivalent_alternatives,
                    "message": "다른 표기값이 허용오차 안에 있어 선택값과 동등하게 처리했습니다.",
                }
            )
        if selected.normalized_value is None and field in REQUIRED_FIELDS:
            issues.append(
                {
                    "code": "missing_required_evidence",
                    "severity": "high",
                    "field": field,
                    "message": "필수 증빙 값이 비어 있습니다.",
                }
            )

    for field in sorted(REQUIRED_FIELDS):
        details = fields.get(field)
        present = details is not None and details["value"] is not None
        checks.append(
            {
                "check_id": f"required.{field}",
                "status": "pass" if present else "fail",
                "required": True,
            }
        )
        if details is None:
            issues.append(
                {
                    "code": "missing_required_field",
                    "severity": "high",
                    "field": field,
                    "message": "필수 필드 후보가 입력에 없습니다.",
                }
            )

    severity_counts = {
        severity: sum(issue["severity"] == severity for issue in issues)
        for severity in ("high", "review")
    }
    return {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "case_id": payload.get("case_id", "UNKNOWN"),
        "notice": payload.get("notice", ""),
        "policy": json.loads(json.dumps(active_policy, ensure_ascii=False)),
        "source_documents": payload.get("documents", []),
        "source_lines": _source_lines(payload),
        "ingestion_summary": payload.get("summary"),
        "fields": fields,
        "issues": issues,
        "observations": observations,
        "validation_ledger": checks,
        "rejected_records": rejected_records,
        "summary": {
            "field_count": len(fields),
            "required_field_count": len(REQUIRED_FIELDS),
            "issue_count": len(issues),
            "observation_count": len(observations),
            "high_issue_count": severity_counts["high"],
            "review_issue_count": severity_counts["review"],
            "status": "review" if issues else "pass",
        },
    }


SOURCE_REFERENCE_KEYS = {
    "document",
    "document_type",
    "location",
    "page",
    "line",
    "record_id",
    "raw_label",
    "raw_value",
    "confidence",
    "authority_rank",
    "extractor",
    "source_span",
    "line_sha256",
    "document_sha256",
}
NORMALIZED_PAYLOAD_KEYS = {
    "schema_version",
    "case_id",
    "notice",
    "policy",
    "source_documents",
    "source_lines",
    "ingestion_summary",
    "fields",
    "issues",
    "observations",
    "validation_ledger",
    "rejected_records",
    "summary",
}
NORMALIZED_FIELD_KEYS = {
    "value",
    "unit",
    "transformation",
    "selected_from",
    "selection",
    "candidates",
}
SELECTION_METADATA_KEYS = {"policy_id", "strategy", "reason", "candidate_count"}
SOURCE_LINE_KEYS = {
    "document_id",
    "page",
    "line",
    "text",
    "confidence",
    "line_sha256",
}
CANDIDATE_KEYS = {
    *Candidate.__dataclass_fields__,
    "selection_rank",
    "selected",
}


def _validated_line_index(documents: list[Any], source_lines: list[Any]) -> tuple[
    dict[str, str],
    dict[str, dict[str, Any]],
    dict[tuple[str, int, int], dict[str, Any]],
]:
    document_hashes = _manifest_hashes(documents)
    manifests = {document["document_id"]: document for document in documents}
    line_index: dict[tuple[str, int, int], dict[str, Any]] = {}
    lines_by_document: dict[str, list[tuple[int, int, str, float]]] = {}
    for source_line in source_lines:
        if not isinstance(source_line, dict) or set(source_line) != SOURCE_LINE_KEYS:
            raise ValueError("normalized source line entries must be objects")
        document_id = source_line.get("document_id")
        page = source_line.get("page")
        line = source_line.get("line")
        text = source_line.get("text")
        digest = source_line.get("line_sha256")
        confidence = source_line.get("confidence")
        if (
            not isinstance(document_id, str)
            or document_id not in document_hashes
            or isinstance(page, bool)
            or not isinstance(page, int)
            or isinstance(line, bool)
            or not isinstance(line, int)
            or not isinstance(text, str)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise ValueError(
                "normalized source line has invalid coordinates, text or confidence"
            )
        if digest != sha256(text.encode("utf-8")).hexdigest():
            raise ValueError("normalized source line hash does not match its text")
        key = (document_id, page, line)
        if key in line_index:
            raise ValueError(f"duplicate normalized source line: {key}")
        line_index[key] = source_line
        lines_by_document.setdefault(document_id, []).append(
            (page, line, text, float(confidence))
        )

    for document_id, digest in document_hashes.items():
        if not _document_content_matches(
            lines_by_document.get(document_id, []), manifests[document_id], digest
        ):
            raise ValueError(
                "normalized source lines do not reproduce document hash: "
                f"{document_id}"
            )
    return document_hashes, manifests, line_index


def _expected_candidate_index(
    manifests: dict[str, dict[str, Any]],
    line_index: dict[tuple[str, int, int], dict[str, Any]],
) -> dict[tuple[str, int, int], dict[str, Any]]:
    expected: dict[tuple[str, int, int], dict[str, Any]] = {}
    matched_by_document: Counter[str] = Counter()
    pages_by_document: dict[str, set[int]] = {}
    lines_by_document: Counter[str] = Counter()
    for coordinate, source_line in sorted(line_index.items()):
        document_id, page, line = coordinate
        pages_by_document.setdefault(document_id, set()).add(page)
        lines_by_document[document_id] += 1
        match, _reason = match_alias(source_line["text"])
        if match is None:
            continue
        alias, alias_start, alias_end = match
        value, value_start, value_end = raw_value(source_line["text"], alias_end)
        matched_by_document[document_id] += 1
        expected[coordinate] = {
            "field": ALIASES[alias],
            "record_id": evidence_record_id(document_id, page, line),
            "raw_label": alias,
            "raw_value": value,
            "extractor": EXTRACTOR_ID,
            "source_span": {
                "alias_start": alias_start,
                "alias_end": alias_end,
                "value_start": value_start,
                "value_end": value_end,
            },
        }

    for document_id, manifest in manifests.items():
        observed = (
            len(pages_by_document.get(document_id, set())),
            lines_by_document[document_id],
            matched_by_document[document_id],
        )
        declared = (
            manifest["page_count"],
            manifest["line_count"],
            manifest["matched_line_count"],
        )
        if observed != declared:
            raise ValueError(
                "normalized source lines disagree with document counts: "
                f"{document_id}"
            )
    return expected


def _validate_candidate_completeness(
    candidates: list[dict[str, Any]],
    expected: dict[tuple[str, int, int], dict[str, Any]],
) -> None:
    actual = {
        (candidate["document"], candidate["page"], candidate["line"]): candidate
        for candidate in candidates
    }
    if set(actual) != set(expected):
        raise ValueError(
            "normalized candidate set does not match retained source lines"
        )
    keys = ("field", "record_id", "raw_label", "raw_value", "extractor", "source_span")
    for coordinate, expected_candidate in expected.items():
        candidate = actual[coordinate]
        if any(candidate.get(key) != expected_candidate[key] for key in keys):
            raise ValueError(
                "normalized candidate identity disagrees with retained source line: "
                f"{coordinate}"
            )


def _candidate_validation_key(
    field_name: str, candidate: Any
) -> tuple[bool, int, float, int]:
    if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_KEYS:
        raise ValueError(f"normalized field has invalid candidates: {field_name}")
    authority = candidate.get("authority_rank")
    confidence = candidate.get("confidence")
    sequence = candidate.get("sequence")
    record_id = candidate.get("record_id")
    if (
        isinstance(authority, bool)
        or not isinstance(authority, int)
        or authority < 0
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 1
        or not isinstance(record_id, str)
        or not record_id
        or candidate.get("field") != field_name
    ):
        raise ValueError(f"normalized field has invalid selection ledger: {field_name}")
    raw_label = candidate.get("raw_label")
    if not isinstance(raw_label, str) or ALIASES.get(raw_label) != field_name:
        raise ValueError(
            f"normalized candidate label does not map to field: {field_name}"
        )
    return (
        candidate.get("normalized_value") is not None,
        authority,
        float(confidence),
        -sequence,
    )


def _validated_ranked_candidates(
    field_name: str, candidates: Any
) -> list[dict[str, Any]]:
    if not isinstance(candidates, list) or not candidates:
        raise ValueError(f"normalized field has no candidates: {field_name}")
    keys = [
        _candidate_validation_key(field_name, candidate) for candidate in candidates
    ]
    record_ids = [candidate["record_id"] for candidate in candidates]
    sequences = [candidate["sequence"] for candidate in candidates]
    ranks = [candidate.get("selection_rank") for candidate in candidates]
    if (
        len(record_ids) != len(set(record_ids))
        or len(sequences) != len(set(sequences))
        or any(isinstance(rank, bool) or not isinstance(rank, int) for rank in ranks)
        or sorted(ranks) != list(range(1, len(candidates) + 1))
        or any(
            not isinstance(candidate.get("selected"), bool) for candidate in candidates
        )
    ):
        raise ValueError(f"normalized field has invalid selection ledger: {field_name}")

    ranked = [
        candidate
        for _key, candidate in sorted(
            zip(keys, candidates, strict=True), key=lambda item: item[0], reverse=True
        )
    ]
    for expected_rank, candidate in enumerate(ranked, start=1):
        expected_selected = expected_rank == 1
        if (
            candidate["selection_rank"] != expected_rank
            or candidate["selected"] is not expected_selected
        ):
            raise ValueError(
                f"normalized field has invalid selection ledger: {field_name}"
            )
    return ranked


def _selected_evidence(
    field_name: str, details: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    ranked = _validated_ranked_candidates(field_name, details.get("candidates"))
    source = details.get("selected_from")
    candidate = ranked[0]
    if not isinstance(source, dict) or set(source) != SOURCE_REFERENCE_KEYS:
        raise ValueError(
            f"normalized field has invalid evidence reference: {field_name}"
        )
    if any(source[key] != candidate.get(key) for key in SOURCE_REFERENCE_KEYS):
        raise ValueError(
            f"normalized evidence reference does not match selected candidate: {field_name}"
        )
    if (
        details.get("value") != candidate.get("normalized_value")
        or details.get("unit") != candidate.get("unit")
        or details.get("transformation") != candidate.get("transformation")
        or candidate.get("field") != field_name
    ):
        raise ValueError(
            f"normalized value does not match selected candidate: {field_name}"
        )
    return candidate, source


def _validate_candidate_span(field_name: str, candidate: dict[str, Any]) -> None:
    span = candidate.get("source_span")
    raw_line = candidate.get("raw_line")
    if not isinstance(span, dict) or not isinstance(raw_line, str):
        raise ValueError(f"normalized candidate has no source span: {field_name}")
    offsets = tuple(
        span.get(key)
        for key in ("alias_start", "alias_end", "value_start", "value_end")
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in offsets):
        raise ValueError(f"normalized candidate has invalid source span: {field_name}")
    alias_start, alias_end, value_start, value_end = offsets
    if not (0 <= alias_start < alias_end <= value_start <= value_end <= len(raw_line)):
        raise ValueError(f"normalized candidate has invalid source span: {field_name}")
    alias_matches = (
        raw_line[alias_start:alias_end].casefold()
        == str(candidate.get("raw_label", "")).casefold()
    )
    raw_value = str(candidate.get("raw_value", ""))
    spanned_value = raw_line[value_start:value_end]
    value_matches = (
        spanned_value == raw_value
        if raw_value
        else spanned_value.strip().casefold() in BLANK_MARKERS
    )
    if not alias_matches or not value_matches:
        raise ValueError(
            f"normalized candidate span does not reproduce raw evidence: {field_name}"
        )


def _validate_candidate_normalization(
    field_name: str, candidate: dict[str, Any]
) -> None:
    try:
        normalized_value, unit, transformation = _normalize(
            field_name, str(candidate.get("raw_value", ""))
        )
    except ValueError:
        normalized_value, unit, transformation = None, None, "parse_failed"
    if (
        candidate.get("normalized_value") != normalized_value
        or candidate.get("unit") != unit
        or candidate.get("transformation") != transformation
    ):
        raise ValueError(
            f"normalized candidate does not reproduce raw evidence: {field_name}"
        )


def _validate_candidate_source(
    field_name: str,
    candidate: dict[str, Any],
    document_hashes: dict[str, str],
    manifests: dict[str, dict[str, Any]],
    line_index: dict[tuple[str, int, int], dict[str, Any]],
    policy: dict[str, Any],
) -> None:
    raw_label = candidate.get("raw_label")
    if not isinstance(raw_label, str) or ALIASES.get(raw_label) != field_name:
        raise ValueError(
            f"normalized candidate label does not map to field: {field_name}"
        )
    document_id = candidate.get("document")
    if candidate.get("document_sha256") != document_hashes.get(document_id):
        raise ValueError(
            f"normalized candidate does not match document manifest: {field_name}"
        )
    if candidate.get("document_type") != manifests[document_id].get("document_type"):
        raise ValueError(
            f"normalized candidate document type does not match manifest: {field_name}"
        )
    source_line = line_index.get(
        (document_id, candidate.get("page"), candidate.get("line"))
    )
    if source_line is None or candidate.get("raw_line") != source_line["text"]:
        raise ValueError(
            f"normalized candidate does not match retained source line: {field_name}"
        )
    if candidate.get("line_sha256") != source_line["line_sha256"]:
        raise ValueError(
            f"normalized candidate line hash does not match source line: {field_name}"
        )
    if float(candidate.get("confidence")) != float(source_line["confidence"]):
        raise ValueError(
            f"normalized candidate confidence does not match source line: {field_name}"
        )
    expected_authority = _authority(policy, field_name, candidate["document_type"])
    if candidate.get("authority_rank") != expected_authority:
        raise ValueError(
            f"normalized candidate authority does not match policy: {field_name}"
        )
    expected_location = f"page {candidate.get('page')} / line {candidate.get('line')}"
    if candidate.get("location") != expected_location:
        raise ValueError(
            f"normalized candidate location does not match coordinates: {field_name}"
        )
    _validate_candidate_span(field_name, candidate)
    _validate_candidate_normalization(field_name, candidate)


def _validate_field_selection_metadata(
    field_name: str,
    details: dict[str, Any],
    policy: dict[str, Any],
    candidate_count: int,
) -> None:
    selection = details.get("selection")
    if not isinstance(selection, dict) or (
        selection.get("policy_id") != policy["policy_id"]
        or selection.get("strategy") != policy["selection_strategy"]
        or selection.get("candidate_count") != candidate_count
    ):
        raise ValueError(
            f"normalized field selection metadata disagrees with policy: {field_name}"
        )


def _validate_global_candidate_order(candidates: list[dict[str, Any]]) -> None:
    record_ids = [candidate["record_id"] for candidate in candidates]
    coordinates = [
        (candidate["document"], candidate["page"], candidate["line"])
        for candidate in candidates
    ]
    if len(record_ids) != len(set(record_ids)) or len(coordinates) != len(
        set(coordinates)
    ):
        raise ValueError("normalized candidates have duplicate evidence identities")
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate["document"],
            candidate["page"],
            candidate["line"],
            candidate["record_id"],
        ),
    )
    for expected_sequence, candidate in enumerate(ordered, start=1):
        if candidate["sequence"] != expected_sequence:
            raise ValueError(
                "normalized candidate sequence disagrees with source order"
            )


def validate_normalized_evidence(
    payload: dict[str, Any], required_fields: Iterable[str]
) -> None:
    """Re-check selected values against retained OCR lines and document hashes."""
    if not isinstance(payload, dict) or set(payload) not in (
        NORMALIZED_PAYLOAD_KEYS,
        NORMALIZED_PAYLOAD_KEYS | {"reproduction"},
    ):
        raise ValueError("normalized evidence has missing or unsupported properties")
    if payload.get("schema_version") != NORMALIZED_SCHEMA_VERSION:
        raise ValueError(
            "unsupported normalized evidence schema_version; expected "
            f"{NORMALIZED_SCHEMA_VERSION}"
        )
    documents = payload.get("source_documents")
    source_lines = payload.get("source_lines")
    fields = payload.get("fields")
    policy = payload.get("policy")
    if not isinstance(documents, list) or not documents:
        raise ValueError("normalized evidence requires a source document manifest")
    if not isinstance(source_lines, list) or not source_lines:
        raise ValueError("normalized evidence requires retained source lines")
    if not isinstance(fields, dict):
        raise ValueError("normalized evidence fields must be an object")
    _validate_policy(policy)
    document_hashes, manifests, line_index = _validated_line_index(
        documents, source_lines
    )
    expected_candidates = _expected_candidate_index(manifests, line_index)

    selected_candidates: dict[str, dict[str, Any]] = {}
    all_candidates: list[dict[str, Any]] = []
    for field_name, details in sorted(fields.items()):
        if (
            field_name not in SUPPORTED_FIELDS
            or not isinstance(details, dict)
            or set(details) != NORMALIZED_FIELD_KEYS
            or not isinstance(details.get("selection"), dict)
            or set(details["selection"]) != SELECTION_METADATA_KEYS
        ):
            raise ValueError(f"normalized evidence has invalid field: {field_name}")
        candidates = details.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"normalized field has no candidates: {field_name}")
        for candidate in candidates:
            _candidate_validation_key(field_name, candidate)
            _validate_candidate_source(
                field_name,
                candidate,
                document_hashes,
                manifests,
                line_index,
                policy,
            )
        _validate_field_selection_metadata(field_name, details, policy, len(candidates))
        candidate, _source = _selected_evidence(field_name, details)
        selected_candidates[field_name] = candidate
        all_candidates.extend(candidates)

    _validate_global_candidate_order(all_candidates)
    _validate_candidate_completeness(all_candidates, expected_candidates)
    seen_record_ids: set[str] = set()
    for field_name in required_fields:
        candidate = selected_candidates.get(field_name)
        if candidate is None or candidate.get("normalized_value") is None:
            raise ValueError(f"required normalized field is missing: {field_name}")
        record_id = candidate.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError(
                f"normalized candidate has invalid record id: {field_name}"
            )
        if record_id in seen_record_ids:
            raise ValueError(
                f"evidence record is selected by multiple fields: {record_id}"
            )
        seen_record_ids.add(record_id)


def normalize_file(
    path: str | Path,
    *,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = strict_json_file(path)
    policy = load_policy(policy_path) if policy_path else None
    return normalize_records(payload, policy)
