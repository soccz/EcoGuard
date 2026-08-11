"""Normalize heterogeneous OCR-like records while preserving provenance."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


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
    "EU 기본값": "default_intensity_tco2e_per_t",
    "CBAM 인증서 가격": "certificate_price_eur_per_tco2e",
    "노출도 적용계수": "phase_in_factor",
    "원산지 탄소가격": "carbon_price_paid_eur_per_tco2e",
    "검증서 번호": "verification_reference",
    "전기사용량": "electricity_kwh",
    "LNG 사용량": "lng_nm3",
}

REQUIRED_FIELDS = {
    "shipment_mass_t",
    "m5_mass_t",
    "m5_intensity_tco2e_per_t",
    "m12_mass_t",
    "m12_intensity_tco2e_per_t",
    "cn_code",
    "actual_intensity_tco2e_per_t",
    "default_intensity_tco2e_per_t",
    "certificate_price_eur_per_tco2e",
    "phase_in_factor",
    "carbon_price_paid_eur_per_tco2e",
    "verification_reference",
}


@dataclass(frozen=True)
class Candidate:
    record_id: str
    field: str
    raw_label: str
    normalized_value: str | None
    unit: str | None
    raw_value: str
    confidence: float
    document: str
    location: str
    extractor: str


def _number(value: str) -> Decimal:
    match = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", value)
    if not match:
        raise ValueError(f"numeric value not found: {value!r}")
    return Decimal(match.group(0).replace(",", ""))


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _normalize(field: str, raw: str) -> tuple[str | None, str | None]:
    if field == "verification_reference":
        stripped = raw.strip()
        return (stripped or None), None
    if field == "cn_code":
        digits = re.sub(r"[^0-9]", "", raw)
        if len(digits) != 8:
            raise ValueError(f"invalid CN code: {raw!r}")
        return digits, None

    value = _number(raw)
    lowered = raw.lower()
    if field.endswith("_mass_t"):
        if re.search(r"\bkg(?:s)?\b", lowered):
            value /= Decimal("1000")
        elif not (
            "톤" in raw
            or re.search(r"\b(?:mt|t|tons?|tonnes?)\b", lowered)
        ):
            raise ValueError(f"unsupported or missing mass unit: {raw!r}")
        return _plain(value), "t"
    if field.endswith("_intensity_tco2e_per_t"):
        if "tco2" not in lowered or "/t" not in lowered:
            raise ValueError(f"unsupported emission-intensity unit: {raw!r}")
        return _plain(value), "tCO2e/t"
    if field in {"certificate_price_eur_per_tco2e", "carbon_price_paid_eur_per_tco2e"}:
        if "eur" not in lowered and "€" not in raw:
            raise ValueError(f"unsupported carbon-price currency: {raw!r}")
        compact = re.sub(r"\s+", "", lowered)
        per_tco2e = any(
            marker in compact
            for marker in (
                "/tco2e",
                "pertco2e",
                "/tonneco2e",
                "pertonneco2e",
                "/tonco2e",
                "pertonco2e",
            )
        )
        if not per_tco2e:
            raise ValueError(f"unsupported carbon-price unit: {raw!r}")
        return _plain(value), "EUR/tCO2e"
    if field == "phase_in_factor":
        if "%" in raw:
            value /= Decimal("100")
        return _plain(value), "ratio"
    if field == "electricity_kwh":
        if "kwh" not in lowered:
            raise ValueError(f"unsupported electricity unit: {raw!r}")
        return _plain(value), "kWh"
    if field == "lng_nm3":
        if "nm3" not in lowered and "nm³" not in lowered:
            raise ValueError(f"unsupported gas-volume unit: {raw!r}")
        return _plain(value), "Nm3"
    raise KeyError(field)


def _select(candidates: list[Candidate]) -> Candidate:
    """Prefer a parsed candidate, then confidence and stable fixture order."""
    return max(
        candidates,
        key=lambda item: (item.normalized_value is not None, item.confidence),
    )


def normalize_records(payload: dict[str, Any]) -> dict[str, Any]:
    """Return normalized values, all candidates, provenance and review issues."""
    grouped: dict[str, list[Candidate]] = {}
    issues: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    records = payload.get("records", [])
    if not records:
        issues.append(
            {
                "code": "empty_input",
                "severity": "high",
                "message": "정규화할 입력 레코드가 없습니다.",
            }
        )

    for index, record in enumerate(records, start=1):
        label = record["label"]
        if label not in ALIASES:
            issues.append(
                {
                    "code": "unknown_label",
                    "severity": "review",
                    "message": f"정규화 규칙이 없는 라벨: {label}",
                    "source": {
                        "document": record["document"],
                        "location": record["location"],
                    },
                }
            )
            rejected_records.append(dict(record))
            continue
        field = ALIASES[label]
        try:
            value, unit = _normalize(field, str(record["value"]))
        except ValueError as exc:
            value, unit = None, None
            issues.append(
                {
                    "code": "parse_failure",
                    "severity": "review",
                    "field": field,
                    "message": str(exc),
                    "source": {
                        "document": record["document"],
                        "location": record["location"],
                    },
                }
            )
        try:
            confidence = float(record["confidence"])
        except (TypeError, ValueError):
            confidence = float("nan")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            issues.append(
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
        grouped.setdefault(field, []).append(
            Candidate(
                record_id=str(record.get("record_id", f"record-{index:03d}")),
                field=field,
                raw_label=label,
                normalized_value=value,
                unit=unit,
                raw_value=str(record["value"]),
                confidence=confidence,
                document=record["document"],
                location=record["location"],
                extractor=str(record.get("extractor", "ocr_adapter_boundary")),
            )
        )

    fields: dict[str, Any] = {}
    for field, candidates in grouped.items():
        selected = _select(candidates)
        fields[field] = {
            "value": selected.normalized_value,
            "unit": selected.unit,
            "selected_from": {
                "document": selected.document,
                "location": selected.location,
                "record_id": selected.record_id,
                "raw_label": selected.raw_label,
                "raw_value": selected.raw_value,
                "confidence": selected.confidence,
                "extractor": selected.extractor,
            },
            "candidates": [asdict(candidate) for candidate in candidates],
        }

        present_values = {
            candidate.normalized_value
            for candidate in candidates
            if candidate.normalized_value is not None
        }
        if len(present_values) > 1:
            issues.append(
                {
                    "code": "cross_document_conflict",
                    "severity": "review",
                    "field": field,
                    "selected": selected.normalized_value,
                    "alternatives": sorted(present_values),
                    "message": "문서 간 값이 달라 원본 확인이 필요합니다.",
                }
            )
        if selected.normalized_value is None:
            issues.append(
                {
                    "code": "missing_required_evidence",
                    "severity": "high",
                    "field": field,
                    "message": "필수 증빙 값이 비어 있습니다.",
                }
            )

    for field in sorted(REQUIRED_FIELDS - fields.keys()):
        issues.append(
            {
                "code": "missing_required_field",
                "severity": "high",
                "field": field,
                "message": "필수 필드 후보가 입력에 없습니다.",
            }
        )

    return {
        "case_id": payload.get("case_id", "UNKNOWN"),
        "notice": payload.get("notice", ""),
        "fields": fields,
        "issues": issues,
        "rejected_records": rejected_records,
        "summary": {
            "field_count": len(fields),
            "issue_count": len(issues),
            "status": "review" if issues else "pass",
        },
    }


def normalize_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return normalize_records(json.load(handle))
