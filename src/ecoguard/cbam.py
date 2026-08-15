"""Traceable CBAM technical-inventory and price-sensitivity calculations.

This module does not calculate a statutory CBAM certificate obligation.  It
reconstructs the educational scenario used by EcoGuard and makes every leaf
operand, reconciliation check, and arithmetic step inspectable.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .preprocessing import ITEM_COMPONENTS, ITEM_IDS, validate_normalized_evidence

MONEY = Decimal("0.01")
EMISSIONS = Decimal("0.01")
INTENSITY = Decimal("0.000001")
INTENSITY_DELTA = Decimal("0.000000001")
INTENSITY_TOLERANCE = Decimal("0.000001")

COMPONENT_LABELS = {
    "process_direct": "process direct",
    "process_indirect": "process indirect",
    "precursor_direct": "precursor direct",
    "precursor_indirect": "precursor indirect",
}

EXPECTED_UNITS = {
    "shipment_mass_t": "t",
    "actual_intensity_tco2e_per_t": "tCO2e/t",
    "default_intensity_tco2e_per_t": "tCO2e/t",
    "certificate_price_eur_per_tco2e": "EUR/tCO2e",
    "carbon_price_paid_eur_per_tco2e": "EUR/tCO2e",
    "scenario_exposure_factor": "ratio",
    "cn_code": None,
}
for _item_id in ITEM_IDS:
    EXPECTED_UNITS.update(
        {
            f"{_item_id}_mass_t": "t",
            f"{_item_id}_intensity_tco2e_per_t": "tCO2e/t",
            f"{_item_id}_installation_id": None,
            f"{_item_id}_production_process": None,
            **{
                f"{_item_id}_{component}_intensity_tco2e_per_t": "tCO2e/t"
                for component in ITEM_COMPONENTS
            },
        }
    )


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _decimal(fields: dict[str, Any], name: str) -> Decimal:
    if name not in fields:
        raise ValueError(f"required normalized field is missing: {name}")
    value = fields[name]["value"]
    if value is None:
        raise ValueError(f"required normalized field is missing: {name}")
    _validate_unit(fields, name)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"required normalized field is not numeric: {name}") from exc
    if not parsed.is_finite():
        raise ValueError(f"required normalized field is not finite: {name}")
    return parsed


def _text(fields: dict[str, Any], name: str) -> str:
    if name not in fields or fields[name]["value"] is None:
        raise ValueError(f"required normalized field is missing: {name}")
    _validate_unit(fields, name)
    return str(fields[name]["value"])


def _validate_case_inputs(
    shipment_mass: Decimal,
    actual_intensity: Decimal,
    default_intensity: Decimal,
    cn_code: str,
) -> None:
    if shipment_mass <= 0:
        raise ValueError("shipment mass must be positive")
    if actual_intensity < 0 or default_intensity < 0:
        raise ValueError("emission intensities must be non-negative")
    if not re.fullmatch(r"[0-9]{8}", cn_code):
        raise ValueError("CN code must contain exactly eight digits")


def _validate_unit(fields: dict[str, Any], name: str) -> None:
    expected = EXPECTED_UNITS[name]
    actual = fields[name].get("unit")
    if actual != expected:
        raise ValueError(
            f"normalized field has invalid unit: {name}: expected {expected!r}, "
            f"got {actual!r}"
        )


def _source(fields: dict[str, Any], name: str) -> dict[str, Any]:
    source = fields[name].get("selected_from")
    if not isinstance(source, dict) or not source.get("record_id"):
        raise ValueError(f"normalized field has no evidence reference: {name}")
    if not all(
        isinstance(source.get(key), str) and source[key].strip()
        for key in ("document", "location")
    ):
        raise ValueError(f"normalized field has incomplete evidence reference: {name}")
    for hash_name in ("line_sha256", "document_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(source.get(hash_name, ""))):
            raise ValueError(
                f"normalized field has invalid evidence hash: {name}: {hash_name}"
            )
    return source


def _operand(
    fields: dict[str, Any],
    name: str,
    value: Decimal,
    unit: str,
) -> dict[str, Any]:
    source = _source(fields, name)
    return {
        "input_path": f"normalized_evidence.fields.{name}",
        "exact": _plain(value),
        "unit": unit,
        "evidence_ref": source["record_id"],
        "document": source["document"],
        "location": source["location"],
        "line_sha256": source.get("line_sha256"),
    }


def _step(
    step_id: str,
    operation: str,
    expression: str,
    operands: list[dict[str, Any]],
    result: Decimal,
    unit: str,
    *,
    display_quantum: Decimal | None = None,
) -> dict[str, Any]:
    display = (
        result.quantize(display_quantum, rounding=ROUND_HALF_UP)
        if display_quantum is not None
        else result
    )
    return {
        "step_id": step_id,
        "operation": operation,
        "expression": expression,
        "operands": operands,
        "result_exact": _plain(result),
        "display_value": format(display, "f"),
        "unit": unit,
        "source_refs": sorted(
            {
                operand["evidence_ref"]
                for operand in operands
                if operand.get("evidence_ref")
            }
        ),
    }


def _money(value: Decimal) -> str:
    return format(value.quantize(MONEY, rounding=ROUND_HALF_UP), "f")


def _emissions(value: Decimal) -> str:
    return format(value.quantize(EMISSIONS, rounding=ROUND_HALF_UP), "f")


def _intensity(value: Decimal) -> str:
    return format(value.quantize(INTENSITY, rounding=ROUND_HALF_UP), "f")


def _intensity_delta(value: Decimal) -> str:
    return format(value.quantize(INTENSITY_DELTA, rounding=ROUND_HALF_UP), "f")


def _price_scenario(
    *,
    scenario_id: str,
    embedded_emissions: Decimal,
    certificate_price: Decimal,
    third_country_price: Decimal,
    exposure_factor: Decimal,
    embedded_emissions_source: dict[str, Any],
    input_sources: dict[str, dict[str, Any]],
    classification: str,
) -> dict[str, Any]:
    if certificate_price < 0 or third_country_price < 0:
        raise ValueError("carbon prices must be non-negative")
    if not Decimal("0") <= exposure_factor <= Decimal("1"):
        raise ValueError("scenario exposure factor must be within [0, 1]")
    effective_price = max(certificate_price - third_country_price, Decimal("0"))
    adjusted_emissions = embedded_emissions * exposure_factor
    exposure = adjusted_emissions * effective_price
    return {
        "scenario_id": scenario_id,
        "classification": classification,
        "inputs": {
            "embedded_emissions_tco2e": _plain(embedded_emissions),
            "scenario_exposure_factor": _plain(exposure_factor),
            "certificate_price_eur_per_tco2e": _plain(certificate_price),
            "third_country_price_eur_per_tco2e": _plain(third_country_price),
        },
        "calculation_trace": [
            {
                "step_id": f"{scenario_id}.effective_price",
                "operation": "subtract_with_zero_floor",
                "expression": "max(certificate price − third-country price, 0)",
                "operands": [
                    {
                        "name": "certificate_price",
                        "exact": _plain(certificate_price),
                        "unit": "EUR/tCO2e",
                        **input_sources.get("certificate_price", {}),
                    },
                    {
                        "name": "third_country_price",
                        "exact": _plain(third_country_price),
                        "unit": "EUR/tCO2e",
                        **input_sources.get("third_country_price", {}),
                    },
                ],
                "result_exact": _plain(effective_price),
                "unit": "EUR/tCO2e",
            },
            {
                "step_id": f"{scenario_id}.adjusted_emissions",
                "operation": "multiply",
                "expression": "technical inventory × scenario exposure factor",
                "operands": [
                    {
                        "name": "embedded_emissions",
                        "exact": _plain(embedded_emissions),
                        "unit": "tCO2e",
                        **embedded_emissions_source,
                    },
                    {
                        "name": "scenario_exposure_factor",
                        "exact": _plain(exposure_factor),
                        "unit": "ratio",
                        **input_sources.get("exposure_factor", {}),
                    },
                ],
                "result_exact": _plain(adjusted_emissions),
                "unit": "tCO2e",
            },
            {
                "step_id": f"{scenario_id}.gross_exposure",
                "operation": "multiply",
                "expression": "adjusted emissions × effective price",
                "operands": [
                    {
                        "name": "adjusted_emissions",
                        "exact": _plain(adjusted_emissions),
                        "unit": "tCO2e",
                        "derived_from": f"{scenario_id}.adjusted_emissions",
                    },
                    {
                        "name": "effective_price",
                        "exact": _plain(effective_price),
                        "unit": "EUR/tCO2e",
                        "derived_from": f"{scenario_id}.effective_price",
                    },
                ],
                "result_exact": _plain(exposure),
                "display_value": _money(exposure),
                "unit": "EUR",
            },
        ],
        "effective_price_eur_per_tco2e": _plain(effective_price),
        "adjusted_emissions_tco2e": _plain(adjusted_emissions),
        "exposure_eur": _money(exposure),
        "statutory_obligation": False,
    }


def calculate_exposure(normalized: dict[str, Any]) -> dict[str, Any]:
    """Build a nested technical inventory and transparent sensitivity scenarios."""
    validate_normalized_evidence(normalized, EXPECTED_UNITS)
    fields = normalized["fields"]
    shipment_mass = _decimal(fields, "shipment_mass_t")
    sheet_actual_intensity = _decimal(fields, "actual_intensity_tco2e_per_t")
    default_intensity = _decimal(fields, "default_intensity_tco2e_per_t")
    certificate_price = _decimal(fields, "certificate_price_eur_per_tco2e")
    exposure_factor = _decimal(fields, "scenario_exposure_factor")
    third_country_price = _decimal(fields, "carbon_price_paid_eur_per_tco2e")
    cn_code = _text(fields, "cn_code")

    _validate_case_inputs(
        shipment_mass,
        sheet_actual_intensity,
        default_intensity,
        cn_code,
    )

    items: list[dict[str, Any]] = []
    calculation_trace: list[dict[str, Any]] = []
    installation_ids: set[str] = set()
    mass_total = Decimal("0")
    emissions_total = Decimal("0")
    axis_totals = {
        "direct": Decimal("0"),
        "indirect": Decimal("0"),
        "process": Decimal("0"),
        "precursor": Decimal("0"),
    }

    for item_id in ITEM_IDS:
        item_name = item_id.upper()
        mass_field = f"{item_id}_mass_t"
        see_field = f"{item_id}_intensity_tco2e_per_t"
        installation_field = f"{item_id}_installation_id"
        process_field = f"{item_id}_production_process"
        mass = _decimal(fields, mass_field)
        supplied_see = _decimal(fields, see_field)
        installation_id = _text(fields, installation_field)
        production_process = _text(fields, process_field)
        if mass <= 0:
            raise ValueError(f"item mass must be positive: {item_name}")
        if installation_id in installation_ids:
            raise ValueError(
                "synthetic items with different supplied SEE must use distinct "
                f"installation evidence: {installation_id}"
            )
        installation_ids.add(installation_id)

        component_rows: list[dict[str, Any]] = []
        component_intensity_total = Decimal("0")
        component_emissions_total = Decimal("0")
        for component in ITEM_COMPONENTS:
            field = f"{item_id}_{component}_intensity_tco2e_per_t"
            intensity = _decimal(fields, field)
            if intensity < 0:
                raise ValueError(f"component intensity must be non-negative: {field}")
            emissions = mass * intensity
            component_intensity_total += intensity
            component_emissions_total += emissions
            if component in {"process_direct", "precursor_direct"}:
                axis_totals["direct"] += emissions
            else:
                axis_totals["indirect"] += emissions
            if component.startswith("process"):
                axis_totals["process"] += emissions
            else:
                axis_totals["precursor"] += emissions
            step = _step(
                f"{item_id}.{component}",
                "multiply",
                "shipment mass × component intensity",
                [
                    _operand(fields, mass_field, mass, "t"),
                    _operand(fields, field, intensity, "tCO2e/t"),
                ],
                emissions,
                "tCO2e",
                display_quantum=EMISSIONS,
            )
            calculation_trace.append(step)
            component_rows.append(
                {
                    "component": component,
                    "label": COMPONENT_LABELS[component],
                    "intensity_tco2e_per_t": _plain(intensity),
                    "embedded_emissions_exact_tco2e": _plain(emissions),
                    "embedded_emissions_tco2e": _emissions(emissions),
                    "scope_decision": (
                        "included in technical inventory; statutory CBAM scope not evaluated"
                    ),
                    "intensity_source": _source(fields, field),
                    "calculation_step_id": step["step_id"],
                }
            )

        see_difference = abs(component_intensity_total - supplied_see)
        if see_difference > INTENSITY_TOLERANCE:
            raise ValueError(
                f"{item_name} component intensity does not reconcile with supplied SEE"
            )
        item_step = _step(
            f"{item_id}.component_sum",
            "sum",
            "Σ(component embedded emissions)",
            [
                {
                    "derived_from": row["calculation_step_id"],
                    "exact": row["embedded_emissions_exact_tco2e"],
                    "unit": "tCO2e",
                }
                for row in component_rows
            ],
            component_emissions_total,
            "tCO2e",
            display_quantum=EMISSIONS,
        )
        calculation_trace.append(item_step)
        items.append(
            {
                "item_id": item_name,
                "cn_code": cn_code,
                "cn_code_source": _source(fields, "cn_code"),
                "installation_id": installation_id,
                "installation_source": _source(fields, installation_field),
                "production_process": production_process,
                "production_process_source": _source(fields, process_field),
                "mass_t": _plain(mass),
                "mass_source": _source(fields, mass_field),
                "supplied_see_tco2e_per_t": _plain(supplied_see),
                "supplied_see_source": _source(fields, see_field),
                "derived_component_see_tco2e_per_t": _intensity(
                    component_intensity_total
                ),
                "see_absolute_difference": _intensity_delta(see_difference),
                "see_matches": True,
                "components": component_rows,
                "embedded_emissions_exact_tco2e": _plain(component_emissions_total),
                "embedded_emissions_tco2e": _emissions(component_emissions_total),
                "calculation_step_id": item_step["step_id"],
            }
        )
        mass_total += mass
        emissions_total += component_emissions_total

    if mass_total != shipment_mass:
        raise ValueError(
            f"item mass {mass_total} t does not match shipment mass {shipment_mass} t"
        )
    derived_weighted_intensity = emissions_total / shipment_mass
    intensity_difference = abs(derived_weighted_intensity - sheet_actual_intensity)
    if intensity_difference > INTENSITY_TOLERANCE:
        raise ValueError(
            "derived weighted intensity does not reconcile with the sheet value"
        )
    if axis_totals["direct"] + axis_totals["indirect"] != emissions_total:
        raise AssertionError("direct/indirect axis does not reconcile")
    if axis_totals["process"] + axis_totals["precursor"] != emissions_total:
        raise AssertionError("process/precursor axis does not reconcile")

    shipment_step = _step(
        "shipment.component_sum",
        "sum",
        "Σ(item component emissions)",
        [
            {
                "derived_from": item["calculation_step_id"],
                "exact": item["embedded_emissions_exact_tco2e"],
                "unit": "tCO2e",
            }
            for item in items
        ],
        emissions_total,
        "tCO2e",
        display_quantum=EMISSIONS,
    )
    calculation_trace.append(shipment_step)

    price_sources = {
        "certificate_price": {
            "evidence_ref": _source(fields, "certificate_price_eur_per_tco2e")[
                "record_id"
            ],
            "input_path": "normalized_evidence.fields.certificate_price_eur_per_tco2e",
        },
        "third_country_price": {
            "evidence_ref": _source(fields, "carbon_price_paid_eur_per_tco2e")[
                "record_id"
            ],
            "input_path": "normalized_evidence.fields.carbon_price_paid_eur_per_tco2e",
        },
        "exposure_factor": {
            "evidence_ref": _source(fields, "scenario_exposure_factor")["record_id"],
            "input_path": "normalized_evidence.fields.scenario_exposure_factor",
        },
    }
    published_scenario = _price_scenario(
        scenario_id="published_fixture",
        embedded_emissions=emissions_total,
        certificate_price=certificate_price,
        third_country_price=third_country_price,
        exposure_factor=exposure_factor,
        embedded_emissions_source={"derived_from": "shipment.component_sum"},
        input_sources=price_sources,
        classification="gross_price_sensitivity_scenario",
    )
    sensitivity_scenarios = [
        published_scenario,
        _price_scenario(
            scenario_id="factor_0_80",
            embedded_emissions=emissions_total,
            certificate_price=certificate_price,
            third_country_price=Decimal("0"),
            exposure_factor=Decimal("0.8"),
            embedded_emissions_source={"derived_from": "shipment.component_sum"},
            input_sources={
                "certificate_price": price_sources["certificate_price"],
                "third_country_price": {
                    "assumption_ref": "analyst-assumption:third-country-price-0",
                    "source_type": "analyst_defined_sensitivity",
                },
                "exposure_factor": {
                    "assumption_ref": "analyst-assumption:exposure-factor-0.80",
                    "source_type": "analyst_defined_sensitivity",
                },
            },
            classification="analyst_defined_sensitivity",
        ),
        _price_scenario(
            scenario_id="factor_0_80_with_12_50_third_country_price",
            embedded_emissions=emissions_total,
            certificate_price=certificate_price,
            third_country_price=Decimal("12.5"),
            exposure_factor=Decimal("0.8"),
            embedded_emissions_source={"derived_from": "shipment.component_sum"},
            input_sources={
                "certificate_price": price_sources["certificate_price"],
                "third_country_price": {
                    "assumption_ref": "analyst-assumption:third-country-price-12.50",
                    "source_type": "analyst_defined_sensitivity",
                },
                "exposure_factor": {
                    "assumption_ref": "analyst-assumption:exposure-factor-0.80",
                    "source_type": "analyst_defined_sensitivity",
                },
            },
            classification="analyst_defined_sensitivity",
        ),
    ]

    default_emissions = shipment_mass * default_intensity
    default_emissions_step = _step(
        "default_value_fixture.embedded_emissions",
        "multiply",
        "shipment mass × default intensity",
        [
            _operand(fields, "shipment_mass_t", shipment_mass, "t"),
            _operand(
                fields,
                "default_intensity_tco2e_per_t",
                default_intensity,
                "tCO2e/t",
            ),
        ],
        default_emissions,
        "tCO2e",
        display_quantum=EMISSIONS,
    )
    default_scenario = _price_scenario(
        scenario_id="default_value_fixture",
        embedded_emissions=default_emissions,
        certificate_price=certificate_price,
        third_country_price=third_country_price,
        exposure_factor=exposure_factor,
        embedded_emissions_source={"derived_from": default_emissions_step["step_id"]},
        input_sources=price_sources,
        classification="gross_price_sensitivity_scenario",
    )
    default_scenario["calculation_trace"].insert(0, default_emissions_step)
    difference_emissions = default_emissions - emissions_total
    difference_exposure = Decimal(
        default_scenario["calculation_trace"][-1]["result_exact"]
    ) - Decimal(published_scenario["calculation_trace"][-1]["result_exact"])

    return {
        "schema_version": "cbam-scenario/3.0",
        "case_id": normalized["case_id"],
        "classification": "gross_price_sensitivity_scenario",
        "statutory_calculator": False,
        "method": (
            "Σ(item mass × component intensity) × scenario exposure factor × "
            "max(certificate price − third-country price, 0)"
        ),
        "technical_inventory": {
            "scope": (
                "synthetic direct, indirect and precursor components; regulatory "
                "inclusion eligibility is not evaluated"
            ),
            "items": items,
            "component_axes": {
                "direct_tco2e": _emissions(axis_totals["direct"]),
                "indirect_tco2e": _emissions(axis_totals["indirect"]),
                "process_tco2e": _emissions(axis_totals["process"]),
                "precursor_tco2e": _emissions(axis_totals["precursor"]),
            },
            "embedded_emissions_exact_tco2e": _plain(emissions_total),
            "embedded_emissions_tco2e": _emissions(emissions_total),
            "weighted_intensity_tco2e_per_t": _intensity(derived_weighted_intensity),
            "calculation_trace": calculation_trace,
        },
        "inputs": {
            "shipment_mass_t": _plain(shipment_mass),
            "sheet_actual_intensity_tco2e_per_t": _plain(sheet_actual_intensity),
            "default_intensity_tco2e_per_t": _plain(default_intensity),
            "certificate_price_eur_per_tco2e": _plain(certificate_price),
            "third_country_price_eur_per_tco2e": _plain(third_country_price),
            "scenario_exposure_factor": _plain(exposure_factor),
        },
        "input_provenance": {
            name: _source(fields, name)
            for name in (
                "shipment_mass_t",
                "cn_code",
                "actual_intensity_tco2e_per_t",
                "default_intensity_tco2e_per_t",
                "certificate_price_eur_per_tco2e",
                "carbon_price_paid_eur_per_tco2e",
                "scenario_exposure_factor",
            )
        },
        "actual_data_scenario": {
            "calculation_basis": "sum of item component emissions",
            "line_items": items,
            "weighted_intensity_tco2e_per_t": _intensity(derived_weighted_intensity),
            "embedded_emissions_tco2e": _emissions(emissions_total),
            "exposure_eur": published_scenario["exposure_eur"],
            "pricing_trace": published_scenario["calculation_trace"],
        },
        "default_value_scenario": {
            "embedded_emissions_tco2e": _emissions(default_emissions),
            "exposure_eur": default_scenario["exposure_eur"],
            "pricing_trace": default_scenario["calculation_trace"],
        },
        "difference": {
            "embedded_emissions_tco2e": _emissions(difference_emissions),
            "exposure_eur": _money(difference_exposure),
        },
        "sensitivity_scenarios": sensitivity_scenarios,
        "reconciliation": {
            "item_mass_total_t": _plain(mass_total),
            "shipment_mass_t": _plain(shipment_mass),
            "mass_matches": mass_total == shipment_mass,
            "derived_weighted_intensity_tco2e_per_t": _intensity(
                derived_weighted_intensity
            ),
            "sheet_weighted_intensity_tco2e_per_t": _plain(sheet_actual_intensity),
            "absolute_intensity_difference": _intensity_delta(intensity_difference),
            "intensity_tolerance": _plain(INTENSITY_TOLERANCE),
            "intensity_matches": True,
            "direct_plus_indirect_matches_total": (
                axis_totals["direct"] + axis_totals["indirect"] == emissions_total
            ),
            "process_plus_precursor_matches_total": (
                axis_totals["process"] + axis_totals["precursor"] == emissions_total
            ),
        },
        "unused_evidence": [
            {
                "fields": ["electricity_kwh", "lng_nm3"],
                "reason": (
                    "Energy quantities are retained as evidence but are not converted "
                    "without source emission factors and an allocation method."
                ),
            }
        ],
        "assumptions": [
            "모든 수치와 생산공정은 합성 사례 입력이며 규제 상수가 아닙니다.",
            "직접·간접·전구물질 구성요소는 기술 인벤토리로 합산하며 법정 포함범위는 판정하지 않습니다.",
            "시나리오 노출계수는 공식 CBAM factor가 아닌 분석용 민감도 입력입니다.",
            "제3국 탄소가격은 단순 단가 차감이며 Article 9 적격성·환산·환급을 평가하지 않습니다.",
            "무상할당 조정, 실제 인증서 의무량과 분기별 가격 산식을 구현하지 않습니다.",
            "결과는 공식 신고액, 지급액 또는 법적 의무액이 아닙니다.",
        ],
    }
