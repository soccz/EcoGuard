"""Deterministic CBAM exposure scenarios from normalized evidence."""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


MONEY = Decimal("0.01")
EMISSIONS = Decimal("0.01")
INTENSITY = Decimal("0.000001")
INTENSITY_DELTA = Decimal("0.000000001")
INTENSITY_TOLERANCE = Decimal("0.000001")


def _decimal(fields: dict[str, Any], name: str) -> Decimal:
    value = fields[name]["value"]
    if value is None:
        raise ValueError(f"required normalized field is missing: {name}")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"required normalized field is not finite: {name}")
    return parsed


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def _emissions(value: Decimal) -> str:
    return str(value.quantize(EMISSIONS, rounding=ROUND_HALF_UP))


def _intensity(value: Decimal) -> str:
    return str(value.quantize(INTENSITY, rounding=ROUND_HALF_UP))


def _intensity_delta(value: Decimal) -> str:
    return format(
        value.quantize(INTENSITY_DELTA, rounding=ROUND_HALF_UP),
        "f",
    )


def _line_sort_key(prefix: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.*?)(\d+)", prefix)
    if match:
        return match.group(1), int(match.group(2))
    return prefix, -1


def calculate_exposure(normalized: dict[str, Any]) -> dict[str, Any]:
    """Calculate two transparent exposure scenarios.

    This is an educational comparison, not a statutory CBAM obligation
    calculator. Prices, intensities and the phase-in factor are supplied by
    the synthetic case rather than embedded as changing regulatory constants.
    """
    fields = normalized["fields"]
    mass = _decimal(fields, "shipment_mass_t")
    sheet_actual_intensity = _decimal(fields, "actual_intensity_tco2e_per_t")
    default_intensity = _decimal(fields, "default_intensity_tco2e_per_t")
    price = _decimal(fields, "certificate_price_eur_per_tco2e")
    phase_in = _decimal(fields, "phase_in_factor")
    origin_price = _decimal(fields, "carbon_price_paid_eur_per_tco2e")

    if mass <= 0:
        raise ValueError("shipment mass must be positive")
    if sheet_actual_intensity < 0 or default_intensity < 0:
        raise ValueError("emission intensities must be non-negative")
    if price < 0 or origin_price < 0:
        raise ValueError("carbon prices must be non-negative")
    if not Decimal("0") <= phase_in <= Decimal("1"):
        raise ValueError("phase-in factor must be between 0 and 1")

    mass_suffix = "_mass_t"
    intensity_suffix = "_intensity_tco2e_per_t"
    mass_prefixes = {
        field[: -len(mass_suffix)]
        for field in fields
        if field.endswith(mass_suffix) and field != "shipment_mass_t"
    }
    intensity_prefixes = {
        field[: -len(intensity_suffix)]
        for field in fields
        if field.endswith(intensity_suffix)
        and field
        not in {
            "actual_intensity_tco2e_per_t",
            "default_intensity_tco2e_per_t",
        }
    }
    if mass_prefixes != intensity_prefixes:
        missing_mass = sorted(intensity_prefixes - mass_prefixes)
        missing_intensity = sorted(mass_prefixes - intensity_prefixes)
        details = []
        if missing_mass:
            details.append("mass for " + ", ".join(missing_mass))
        if missing_intensity:
            details.append("intensity for " + ", ".join(missing_intensity))
        raise ValueError("partial line-item evidence; missing " + "; ".join(details))
    line_definitions = [
        (
            prefix.upper(),
            prefix + mass_suffix,
            prefix + intensity_suffix,
        )
        for prefix in sorted(mass_prefixes, key=_line_sort_key)
    ]
    line_items: list[dict[str, str]] = []
    line_mass = Decimal("0")
    actual_emissions = Decimal("0")
    if line_definitions:
        for name, mass_field, intensity_field in line_definitions:
            item_mass = _decimal(fields, mass_field)
            item_intensity = _decimal(fields, intensity_field)
            if item_mass < 0 or item_intensity < 0:
                raise ValueError("line-item mass and intensity must be non-negative")
            emissions = item_mass * item_intensity
            line_mass += item_mass
            actual_emissions += emissions
            line_items.append(
                {
                    "item": name,
                    "mass_t": str(item_mass),
                    "intensity_tco2e_per_t": str(item_intensity),
                    "embedded_emissions_tco2e": _emissions(emissions),
                    "mass_source": fields[mass_field]["selected_from"],
                    "intensity_source": fields[intensity_field]["selected_from"],
                }
            )
        if line_mass != mass:
            raise ValueError(
                f"line-item mass {line_mass} t does not match shipment mass {mass} t"
            )
        calculation_basis = "sum of normalized line-item mass × intensity"
    else:
        line_mass = mass
        actual_emissions = mass * sheet_actual_intensity
        calculation_basis = "shipment mass × supplied weighted intensity"

    derived_actual_intensity = actual_emissions / mass
    intensity_difference = abs(
        derived_actual_intensity - sheet_actual_intensity
    )
    intensity_matches = intensity_difference <= INTENSITY_TOLERANCE
    if not intensity_matches:
        raise ValueError(
            "derived weighted intensity does not reconcile with the sheet value"
        )
    effective_price = max(price - origin_price, Decimal("0"))
    default_emissions = mass * default_intensity
    actual_exposure = actual_emissions * phase_in * effective_price
    default_exposure = default_emissions * phase_in * effective_price

    inputs = {
        "shipment_mass_t": str(mass),
        "sheet_actual_intensity_tco2e_per_t": str(sheet_actual_intensity),
        "default_intensity_tco2e_per_t": str(default_intensity),
        "certificate_price_eur_per_tco2e": str(price),
        "carbon_price_paid_eur_per_tco2e": str(origin_price),
        "phase_in_factor": str(phase_in),
    }
    input_provenance = {
        name: fields[name]["selected_from"]
        for name in (
            "shipment_mass_t",
            "actual_intensity_tco2e_per_t",
            "default_intensity_tco2e_per_t",
            "certificate_price_eur_per_tco2e",
            "carbon_price_paid_eur_per_tco2e",
            "phase_in_factor",
        )
    }
    return {
        "case_id": normalized["case_id"],
        "method": (
            calculation_basis
            + " × phase-in × max(certificate price − origin carbon price, 0)"
        ),
        "classification": "gross_price_sensitivity_scenario",
        "inputs": inputs,
        "input_provenance": input_provenance,
        "actual_data_scenario": {
            "calculation_basis": calculation_basis,
            "line_items": line_items,
            "weighted_intensity_tco2e_per_t": _intensity(
                derived_actual_intensity
            ),
            "embedded_emissions_tco2e": _emissions(actual_emissions),
            "exposure_eur": _money(actual_exposure),
        },
        "default_value_scenario": {
            "embedded_emissions_tco2e": _emissions(default_emissions),
            "exposure_eur": _money(default_exposure),
        },
        "difference": {
            "embedded_emissions_tco2e": _emissions(default_emissions - actual_emissions),
            "exposure_eur": _money(default_exposure - actual_exposure),
        },
        "reconciliation": {
            "line_item_mass_total_t": str(line_mass),
            "shipment_mass_t": str(mass),
            "mass_matches": line_mass == mass,
            "derived_weighted_intensity_tco2e_per_t": _intensity(
                derived_actual_intensity
            ),
            "sheet_weighted_intensity_tco2e_per_t": str(
                sheet_actual_intensity
            ),
            "absolute_intensity_difference": _intensity_delta(
                intensity_difference
            ),
            "intensity_tolerance": str(INTENSITY_TOLERANCE),
            "intensity_matches": intensity_matches,
        },
        "assumptions": [
            "가격·집약도·적용계수는 합성 사례의 입력값이며 규제 상수가 아닙니다.",
            "원산지 탄소가격은 입력된 증빙 금액만큼 단순 차감한 비교 시나리오입니다.",
            "Article 31 무상할당 조정과 Article 9의 법정 변환 방법을 구현하지 않습니다.",
            "기본값 시나리오의 탄소가격 처리는 현행 법정 의무액이 아닌 단순 민감도 비교입니다.",
            "인증서 가격은 합성 fixture이며 실제 분기·주간 가격 산식이 아닙니다.",
            "결과는 공식 신고액이나 인증서 의무량을 대체하지 않습니다.",
        ],
    }
