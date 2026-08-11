"""Normalize OCR candidates while preserving selection and evidence lineage."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
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


DEFAULT_POLICY: dict[str, Any] = {
    "policy_id": "ecoguard-normalization-v2",
    "selection_strategy": "validity > document authority > confidence > stable input order",
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
    with Path(path).open(encoding="utf-8") as handle:
        policy = json.load(handle)
    _validate_policy(policy)
    return policy


def _validate_policy(policy: dict[str, Any]) -> None:
    if not isinstance(policy.get("policy_id"), str):
        raise ValueError("normalization policy requires policy_id")
    authorities = policy.get("source_authority", {})
    if not isinstance(authorities, dict) or any(
        not isinstance(value, int) or value < 0 for value in authorities.values()
    ):
        raise ValueError("source_authority values must be non-negative integers")
    for field, config in policy.get("field_overrides", {}).items():
        field_authorities = config.get("source_authority", {})
        if not isinstance(field_authorities, dict) or any(
            not isinstance(value, int) or value < 0
            for value in field_authorities.values()
        ):
            raise ValueError(
                f"field source_authority values must be non-negative integers: {field}"
            )
        try:
            tolerance = Decimal(str(config.get("absolute_conflict_tolerance", "0")))
        except InvalidOperation as exc:
            raise ValueError(f"invalid conflict tolerance for {field}") from exc
        if not tolerance.is_finite() or tolerance < 0:
            raise ValueError(f"invalid conflict tolerance for {field}")


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


def _normalize_mass(raw: str, value: Decimal, lowered: str) -> tuple[str, str, str]:
    if re.search(r"\bkg(?:s)?\b", lowered):
        value /= Decimal("1000")
        transformation = "kg_to_t"
    elif "톤" in raw or re.search(r"\b(?:mt|t|tons?|tonnes?)\b", lowered):
        transformation = "identity_tonnes"
    else:
        raise ValueError(f"unsupported or missing mass unit: {raw!r}")
    return _plain(value), "t", transformation


def _normalize_intensity(
    raw: str, value: Decimal, lowered: str
) -> tuple[str, str, str]:
    compact = re.sub(r"\s+", "", lowered)
    if "tco2" not in compact or not any(
        marker in compact for marker in ("/t", "perton", "pertonne")
    ):
        raise ValueError(f"unsupported emission-intensity unit: {raw!r}")
    return _plain(value), "tCO2e/t", "normalize_emission_intensity_unit"


def _normalize_carbon_price(
    raw: str, value: Decimal, lowered: str
) -> tuple[str, str, str]:
    if "eur" not in lowered and "€" not in raw:
        raise ValueError(f"unsupported carbon-price currency: {raw!r}")
    compact = re.sub(r"\s+", "", lowered)
    unit_markers = (
        "/tco2e",
        "pertco2e",
        "/tonneco2e",
        "pertonneco2e",
        "/tonco2e",
        "pertonco2e",
    )
    if not any(marker in compact for marker in unit_markers):
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
        digits = re.sub(r"[^0-9]", "", raw)
        if len(digits) != 8:
            raise ValueError(f"invalid CN code: {raw!r}")
        return digits, None, "strip_non_digits"

    value = _number(raw)
    lowered = raw.lower()
    if field.endswith("_mass_t"):
        return _normalize_mass(raw, value, lowered)
    if field.endswith("_intensity_tco2e_per_t"):
        return _normalize_intensity(raw, value, lowered)
    if field in {"certificate_price_eur_per_tco2e", "carbon_price_paid_eur_per_tco2e"}:
        return _normalize_carbon_price(raw, value, lowered)
    if field == "scenario_exposure_factor":
        return _normalize_ratio(raw, value)
    if field == "electricity_kwh":
        if "kwh" not in lowered:
            raise ValueError(f"unsupported electricity unit: {raw!r}")
        return _plain(value), "kWh", "normalize_kwh"
    if field == "lng_nm3":
        if "nm3" not in lowered and "nm³" not in lowered:
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
    record: dict[str, Any], index: int, policy: dict[str, Any]
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

    try:
        confidence = float(record["confidence"])
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

    document_type = str(record.get("document_type", "unknown"))
    return (
        Candidate(
            sequence=index,
            record_id=record_id,
            field=field,
            raw_label=label,
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


def normalize_records(
    payload: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return selected values, every candidate, lineage, and a validation ledger."""
    active_policy = policy or DEFAULT_POLICY
    _validate_policy(active_policy)
    grouped: dict[str, list[Candidate]] = {}
    issues: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    records = payload.get("records", [])
    if not records:
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
    else:
        checks.append(
            {
                "check_id": "input.non_empty",
                "status": "pass",
                "observed": len(records),
            }
        )

    for index, record in enumerate(records, start=1):
        candidate, candidate_issues = _candidate_from_record(
            record, index, active_policy
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
        if selected.normalized_value is None:
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
        "schema_version": "2.0.0",
        "case_id": payload.get("case_id", "UNKNOWN"),
        "notice": payload.get("notice", ""),
        "policy": {
            "policy_id": active_policy["policy_id"],
            "selection_strategy": active_policy.get("selection_strategy"),
        },
        "source_documents": payload.get("documents", []),
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


def normalize_file(
    path: str | Path,
    *,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    policy = load_policy(policy_path) if policy_path else None
    return normalize_records(payload, policy)
