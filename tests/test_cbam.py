import copy
import json
import unittest
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from ecoguard.cbam import _price_scenario, calculate_exposure
from ecoguard.ingestion import extract_document_bundle, extract_document_bundle_file
from ecoguard.preprocessing import load_policy, normalize_records


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/synthetic/trade_case_documents.json"
POLICY = ROOT / "data/reference/normalization_policy.json"

EXPECTED_COMPONENTS = {
    "M5": {
        "process_direct": "288.00",
        "process_indirect": "34.56",
        "precursor_direct": "157.50",
        "precursor_indirect": "22.50",
    },
    "M12": {
        "process_direct": "350.00",
        "process_indirect": "58.80",
        "precursor_direct": "175.00",
        "precursor_indirect": "25.00",
    },
}


def _keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _keys(nested)


class CbamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extracted = extract_document_bundle_file(BUNDLE)
        cls.policy = load_policy(POLICY)
        cls.normalized = normalize_records(cls.extracted, cls.policy)
        cls.result = calculate_exposure(cls.normalized)

    def _normalized_copy(self):
        return copy.deepcopy(self.normalized)

    def _normalized_after_replacements(self, replacements):
        bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
        found = {source: 0 for source in replacements}
        for document in bundle["documents"]:
            for page in document["pages"]:
                for line in page["lines"]:
                    for source, replacement in replacements.items():
                        if line["text"] == source:
                            line["text"] = replacement
                            found[source] += 1
        self.assertEqual(found, {source: 1 for source in replacements})
        return normalize_records(extract_document_bundle(bundle), self.policy)

    def test_normalized_schema_version_is_enforced_at_calculation_boundary(self):
        for schema_version in (None, "0.0.0", "cbam-other-format"):
            with self.subTest(schema_version=schema_version):
                normalized = self._normalized_copy()
                if schema_version is None:
                    del normalized["schema_version"]
                else:
                    normalized["schema_version"] = schema_version
                with self.assertRaisesRegex(ValueError, "normalized evidence"):
                    calculate_exposure(normalized)

        for mutate in (
            lambda payload: payload.update(officially_approved=True),
            lambda payload: payload["fields"]["shipment_mass_t"].update(official=True),
            lambda payload: payload["fields"]["shipment_mass_t"]["candidates"][
                0
            ].update(approved=True),
            lambda payload: payload["source_lines"][0].update(compliant=True),
            lambda payload: payload.pop("validation_ledger"),
        ):
            with self.subTest(mutate=mutate):
                normalized = self._normalized_copy()
                mutate(normalized)
                with self.assertRaises(ValueError):
                    calculate_exposure(normalized)

    def test_v3_golden_inventory_and_legacy_comparison(self):
        self.assertEqual(self.result["schema_version"], "cbam-scenario/3.0")
        self.assertEqual(
            self.result["classification"], "gross_price_sensitivity_scenario"
        )
        self.assertFalse(self.result["statutory_calculator"])

        actual = self.result["actual_data_scenario"]
        self.assertEqual(actual["embedded_emissions_tco2e"], "1111.36")
        self.assertEqual(actual["exposure_eur"], "97244.00")
        self.assertEqual(actual["weighted_intensity_tco2e_per_t"], "5.849263")

        default = self.result["default_value_scenario"]
        self.assertEqual(default["embedded_emissions_tco2e"], "1389.20")
        self.assertEqual(default["exposure_eur"], "121555.00")
        self.assertEqual(self.result["difference"]["exposure_eur"], "24311.00")

    def test_m5_and_m12_expose_all_four_components(self):
        items = {
            item["item_id"]: item
            for item in self.result["technical_inventory"]["items"]
        }
        self.assertEqual(set(items), {"M5", "M12"})
        self.assertEqual(items["M5"]["embedded_emissions_tco2e"], "502.56")
        self.assertEqual(items["M12"]["embedded_emissions_tco2e"], "608.80")

        for item_id, expected in EXPECTED_COMPONENTS.items():
            with self.subTest(item=item_id):
                item = items[item_id]
                observed = {
                    component["component"]: component["embedded_emissions_tco2e"]
                    for component in item["components"]
                }
                self.assertEqual(observed, expected)
                self.assertEqual(
                    sum((Decimal(value) for value in observed.values()), Decimal("0")),
                    Decimal(item["embedded_emissions_exact_tco2e"]),
                )
                self.assertTrue(item["see_matches"])
                self.assertEqual(item["see_absolute_difference"], "0.000000000")
                self.assertEqual(
                    Decimal(item["derived_component_see_tco2e_per_t"]),
                    Decimal(item["supplied_see_tco2e_per_t"]),
                )

    def test_direct_indirect_and_process_precursor_axes_reconcile(self):
        inventory = self.result["technical_inventory"]
        axes = inventory["component_axes"]
        self.assertEqual(
            axes,
            {
                "direct_tco2e": "970.50",
                "indirect_tco2e": "140.86",
                "process_tco2e": "731.36",
                "precursor_tco2e": "380.00",
            },
        )
        total = Decimal(inventory["embedded_emissions_exact_tco2e"])
        self.assertEqual(
            Decimal(axes["direct_tco2e"]) + Decimal(axes["indirect_tco2e"]),
            total,
        )
        self.assertEqual(
            Decimal(axes["process_tco2e"]) + Decimal(axes["precursor_tco2e"]),
            total,
        )
        self.assertEqual(total, Decimal("1111.36"))
        self.assertTrue(
            self.result["reconciliation"]["direct_plus_indirect_matches_total"]
        )
        self.assertTrue(
            self.result["reconciliation"]["process_plus_precursor_matches_total"]
        )

    def test_calculation_trace_is_complete_topological_and_arithmetic(self):
        trace = self.result["technical_inventory"]["calculation_trace"]
        expected_ids = {
            f"{item}.{component}"
            for item in ("m5", "m12")
            for component in (
                "process_direct",
                "process_indirect",
                "precursor_direct",
                "precursor_indirect",
            )
        } | {"m5.component_sum", "m12.component_sum", "shipment.component_sum"}
        self.assertEqual({step["step_id"] for step in trace}, expected_ids)
        self.assertEqual(len(trace), len(expected_ids))

        prior_results = {}
        for step in trace:
            with self.subTest(step=step["step_id"]):
                result = Decimal(step["result_exact"])
                if step["operation"] == "multiply":
                    self.assertEqual(len(step["operands"]), 2)
                    expected = Decimal("1")
                    for operand in step["operands"]:
                        expected *= Decimal(operand["exact"])
                    self.assertEqual(result, expected)
                    self.assertEqual(
                        step["source_refs"],
                        sorted(operand["evidence_ref"] for operand in step["operands"]),
                    )
                elif step["operation"] == "sum":
                    expected = Decimal("0")
                    for operand in step["operands"]:
                        parent = operand["derived_from"]
                        self.assertIn(parent, prior_results)
                        self.assertEqual(
                            Decimal(operand["exact"]), prior_results[parent]
                        )
                        expected += Decimal(operand["exact"])
                    self.assertEqual(result, expected)
                else:
                    self.fail(f"unexpected technical-inventory operation: {step}")
                prior_results[step["step_id"]] = result

        self.assertEqual(prior_results["shipment.component_sum"], Decimal("1111.36"))

    def test_every_evidence_leaf_and_item_descriptor_keeps_provenance(self):
        fields = self.normalized["fields"]
        trace = self.result["technical_inventory"]["calculation_trace"]
        leaf_operands = [
            operand
            for step in trace
            for operand in step["operands"]
            if "derived_from" not in operand
        ]
        self.assertEqual(len(leaf_operands), 16)
        for operand in leaf_operands:
            with self.subTest(path=operand["input_path"]):
                field_name = operand["input_path"].rsplit(".", 1)[-1]
                selected = fields[field_name]["selected_from"]
                self.assertEqual(operand["evidence_ref"], selected["record_id"])
                self.assertEqual(operand["document"], selected["document"])
                self.assertEqual(operand["location"], selected["location"])
                self.assertEqual(operand["line_sha256"], selected["line_sha256"])
                self.assertEqual(len(operand["line_sha256"]), 64)

        for item in self.result["technical_inventory"]["items"]:
            for source_name in (
                "cn_code_source",
                "installation_source",
                "production_process_source",
                "mass_source",
                "supplied_see_source",
            ):
                source = item[source_name]
                with self.subTest(item=item["item_id"], source=source_name):
                    self.assertTrue(source["record_id"])
                    self.assertTrue(source["document"])
                    self.assertTrue(source["location"])
                    self.assertEqual(len(source["line_sha256"]), 64)
            for component in item["components"]:
                source = component["intensity_source"]
                self.assertTrue(source["record_id"])
                self.assertEqual(len(source["line_sha256"]), 64)

    def test_all_pricing_leaf_inputs_are_evidence_or_explicit_assumptions(self):
        for scenario in self.result["sensitivity_scenarios"]:
            for step in scenario["calculation_trace"]:
                for operand in step["operands"]:
                    if "derived_from" in operand:
                        continue
                    with self.subTest(
                        scenario=scenario["scenario_id"], operand=operand["name"]
                    ):
                        references = {
                            key
                            for key in ("evidence_ref", "assumption_ref")
                            if key in operand
                        }
                        self.assertEqual(len(references), 1)
                        if "evidence_ref" in operand:
                            self.assertIn("input_path", operand)
                        else:
                            self.assertEqual(
                                operand["source_type"], "analyst_defined_sensitivity"
                            )
                            self.assertTrue(
                                operand["assumption_ref"].startswith(
                                    "analyst-assumption:"
                                )
                            )

    def test_three_price_sensitivity_scenarios_reproduce_exactly(self):
        scenarios = {
            scenario["scenario_id"]: scenario
            for scenario in self.result["sensitivity_scenarios"]
        }
        expected = {
            "published_fixture": ("1", "0", "1111.36", "87.5", "97244.00"),
            "factor_0_80": ("0.8", "0", "889.088", "87.5", "77795.20"),
            "factor_0_80_with_12_50_third_country_price": (
                "0.8",
                "12.5",
                "889.088",
                "75",
                "66681.60",
            ),
        }
        self.assertEqual(set(scenarios), set(expected))
        for scenario_id, values in expected.items():
            factor, third_country, adjusted, effective_price, exposure = values
            scenario = scenarios[scenario_id]
            with self.subTest(scenario=scenario_id):
                self.assertEqual(scenario["inputs"]["scenario_exposure_factor"], factor)
                self.assertEqual(
                    scenario["inputs"]["third_country_price_eur_per_tco2e"],
                    third_country,
                )
                self.assertEqual(scenario["adjusted_emissions_tco2e"], adjusted)
                self.assertEqual(
                    scenario["effective_price_eur_per_tco2e"], effective_price
                )
                self.assertEqual(scenario["exposure_eur"], exposure)
                self.assertFalse(scenario["statutory_obligation"])

                inputs = scenario["inputs"]
                expected_effective = max(
                    Decimal(inputs["certificate_price_eur_per_tco2e"])
                    - Decimal(inputs["third_country_price_eur_per_tco2e"]),
                    Decimal("0"),
                )
                expected_adjusted = Decimal(
                    inputs["embedded_emissions_tco2e"]
                ) * Decimal(inputs["scenario_exposure_factor"])
                self.assertEqual(Decimal(effective_price), expected_effective)
                self.assertEqual(Decimal(adjusted), expected_adjusted)
                self.assertEqual(
                    Decimal(exposure), expected_effective * expected_adjusted
                )

    def test_default_value_trace_derives_emissions_from_evidence(self):
        trace = self.result["default_value_scenario"]["pricing_trace"]
        self.assertEqual(
            [step["step_id"] for step in trace],
            [
                "default_value_fixture.embedded_emissions",
                "default_value_fixture.effective_price",
                "default_value_fixture.adjusted_emissions",
                "default_value_fixture.gross_exposure",
            ],
        )
        emissions_step = trace[0]
        self.assertEqual(emissions_step["result_exact"], "1389.20001")
        self.assertEqual(
            [operand["input_path"] for operand in emissions_step["operands"]],
            [
                "normalized_evidence.fields.shipment_mass_t",
                "normalized_evidence.fields.default_intensity_tco2e_per_t",
            ],
        )
        self.assertEqual(
            trace[2]["operands"][0]["derived_from"],
            emissions_step["step_id"],
        )
        published_trace = self.result["actual_data_scenario"]["pricing_trace"]
        exact_difference = Decimal(trace[-1]["result_exact"]) - Decimal(
            published_trace[-1]["result_exact"]
        )
        self.assertEqual(exact_difference, Decimal("24311.000875"))
        self.assertEqual(self.result["difference"]["exposure_eur"], "24311.00")

    def test_zero_floor_prevents_negative_exposure(self):
        normalized = self._normalized_after_replacements(
            {"원산지 탄소가격 : EUR 0 / tCO2e": ("원산지 탄소가격 : EUR 100 / tCO2e")}
        )
        result = calculate_exposure(normalized)
        published = result["sensitivity_scenarios"][0]
        self.assertEqual(published["effective_price_eur_per_tco2e"], "0")
        self.assertEqual(published["exposure_eur"], "0.00")

    def test_missing_component_provenance_is_rejected(self):
        for field in (
            "m5_process_direct_intensity_tco2e_per_t",
            "m12_installation_id",
            "certificate_price_eur_per_tco2e",
        ):
            with self.subTest(field=field):
                normalized = self._normalized_copy()
                normalized["fields"][field]["selected_from"] = {}
                with self.assertRaisesRegex(ValueError, "invalid evidence reference"):
                    calculate_exposure(normalized)

    def test_units_cn_and_evidence_hash_are_validated_at_calculation_boundary(self):
        invalid_cases = (
            ("m5_mass_t", "unit", "kg"),
            ("certificate_price_eur_per_tco2e", "unit", "EUR"),
            ("cn_code", "value", "7318155X"),
        )
        for field, key, value in invalid_cases:
            with self.subTest(field=field, key=key):
                normalized = self._normalized_copy()
                normalized["fields"][field][key] = value
                with self.assertRaisesRegex(ValueError, "selected candidate"):
                    calculate_exposure(normalized)

        for hash_name in ("line_sha256", "document_sha256"):
            with self.subTest(hash_name=hash_name):
                normalized = self._normalized_copy()
                normalized["fields"]["shipment_mass_t"]["selected_from"][
                    hash_name
                ] = "tampered"
                with self.assertRaisesRegex(ValueError, "selected candidate"):
                    calculate_exposure(normalized)

        normalized = self._normalized_copy()
        source = normalized["fields"]["shipment_mass_t"]["selected_from"]
        source.update(
            {
                "record_id": "fabricated-record",
                "document": "fabricated-document",
                "location": "page 9 / line 9",
                "line_sha256": "0" * 64,
                "document_sha256": "0" * 64,
            }
        )
        with self.assertRaisesRegex(ValueError, "selected candidate"):
            calculate_exposure(normalized)

        price_fields = (
            "certificate_price_eur_per_tco2e",
            "carbon_price_paid_eur_per_tco2e",
        )
        swapped = self._normalized_copy()
        first, second = price_fields
        swapped["fields"][first], swapped["fields"][second] = (
            swapped["fields"][second],
            swapped["fields"][first],
        )
        for field_name in price_fields:
            for candidate in swapped["fields"][field_name]["candidates"]:
                candidate["field"] = field_name
        with self.assertRaisesRegex(ValueError, "label does not map to field"):
            calculate_exposure(swapped)

        reranked = self._normalized_copy()
        mass_details = reranked["fields"]["shipment_mass_t"]
        higher, lower = mass_details["candidates"][:2]
        self.assertEqual((higher["authority_rank"], lower["authority_rank"]), (100, 90))
        higher["selected"], higher["selection_rank"] = False, 2
        lower["selected"], lower["selection_rank"] = True, 1
        mass_details["value"] = lower["normalized_value"]
        mass_details["unit"] = lower["unit"]
        mass_details["transformation"] = lower["transformation"]
        mass_details["selected_from"] = {
            key: lower[key] for key in mass_details["selected_from"]
        }
        with self.assertRaisesRegex(ValueError, "invalid selection ledger"):
            calculate_exposure(reranked)

        forged_authority = self._normalized_copy()
        mass_details = forged_authority["fields"]["shipment_mass_t"]
        higher, lower = mass_details["candidates"][:2]
        higher["authority_rank"] = 90
        lower["authority_rank"] = 101
        higher["selected"], higher["selection_rank"] = False, 2
        lower["selected"], lower["selection_rank"] = True, 1
        for key in ("value", "unit", "transformation"):
            source_key = "normalized_value" if key == "value" else key
            mass_details[key] = lower[source_key]
        mass_details["selected_from"] = {
            key: lower[key] for key in mass_details["selected_from"]
        }
        with self.assertRaisesRegex(ValueError, "authority does not match policy"):
            calculate_exposure(forged_authority)

        concealed_winner = self._normalized_copy()
        mass_details = concealed_winner["fields"]["shipment_mass_t"]
        higher, lower = mass_details["candidates"][:2]
        higher.update(
            {
                "normalized_value": None,
                "unit": None,
                "transformation": "parse_failed",
                "selected": False,
                "selection_rank": 3,
            }
        )
        lower.update({"selected": True, "selection_rank": 1})
        mass_details["candidates"][2]["selection_rank"] = 2
        for key in ("value", "unit", "transformation"):
            source_key = "normalized_value" if key == "value" else key
            mass_details[key] = lower[source_key]
        mass_details["selected_from"] = {
            key: lower[key] for key in mass_details["selected_from"]
        }
        with self.assertRaisesRegex(ValueError, "does not reproduce raw evidence"):
            calculate_exposure(concealed_winner)

        confidence_tamper = self._normalized_copy()
        details = confidence_tamper["fields"]["certificate_price_eur_per_tco2e"]
        candidate = details["candidates"][0]
        candidate["confidence"] = 0.01
        details["selected_from"]["confidence"] = 0.01
        with self.assertRaisesRegex(ValueError, "confidence does not match source"):
            calculate_exposure(confidence_tamper)

        sequence_tamper = self._normalized_copy()
        candidate = sequence_tamper["fields"]["certificate_price_eur_per_tco2e"][
            "candidates"
        ][0]
        candidate["sequence"] += 100
        with self.assertRaisesRegex(ValueError, "sequence disagrees with source order"):
            calculate_exposure(sequence_tamper)

    def test_calculation_revalidates_candidate_against_retained_source_lines(self):
        fabricated = self._normalized_copy()
        details = fabricated["fields"]["shipment_mass_t"]
        candidate = next(item for item in details["candidates"] if item["selected"])
        candidate.update(
            {
                "document": "fabricated-document",
                "document_sha256": "0" * 64,
            }
        )
        for key in ("document", "document_sha256"):
            details["selected_from"][key] = candidate[key]
        with self.assertRaisesRegex(ValueError, "document manifest"):
            calculate_exposure(fabricated)

        changed_line = self._normalized_copy()
        details = changed_line["fields"]["shipment_mass_t"]
        candidate = next(item for item in details["candidates"] if item["selected"])
        source_line = next(
            item
            for item in changed_line["source_lines"]
            if (
                item["document_id"],
                item["page"],
                item["line"],
            )
            == (candidate["document"], candidate["page"], candidate["line"])
        )
        source_line["text"] = "총 출하 중량 : 190,001 kg"
        source_line["line_sha256"] = sha256(
            source_line["text"].encode("utf-8")
        ).hexdigest()
        candidate["raw_line"] = source_line["text"]
        candidate["raw_value"] = "190,001 kg"
        candidate["normalized_value"] = "190.001"
        candidate["line_sha256"] = source_line["line_sha256"]
        details["value"] = candidate["normalized_value"]
        for key in ("raw_value", "line_sha256"):
            details["selected_from"][key] = candidate[key]
        with self.assertRaisesRegex(ValueError, "document hash"):
            calculate_exposure(changed_line)

    def test_calculation_rejects_hidden_candidate_and_manifest_count_tampering(self):
        hidden = self._normalized_copy()
        details = hidden["fields"]["shipment_mass_t"]
        details["candidates"] = [
            candidate
            for candidate in details["candidates"]
            if candidate["document"] != "operator_memo"
        ]
        details["selection"]["candidate_count"] = len(details["candidates"])
        all_candidates = [
            candidate
            for field in hidden["fields"].values()
            for candidate in field["candidates"]
        ]
        for sequence, candidate in enumerate(
            sorted(
                all_candidates,
                key=lambda item: (
                    item["document"],
                    item["page"],
                    item["line"],
                    item["record_id"],
                ),
            ),
            start=1,
        ):
            candidate["sequence"] = sequence
        with self.assertRaisesRegex(ValueError, "candidate set does not match"):
            calculate_exposure(hidden)

        false_manifest_count = self._normalized_copy()
        invoice = next(
            document
            for document in false_manifest_count["source_documents"]
            if document["document_id"] == "commercial_invoice"
        )
        invoice["matched_line_count"] -= 1
        with self.assertRaisesRegex(ValueError, "document counts"):
            calculate_exposure(false_manifest_count)

    def test_component_see_mass_and_weighted_intensity_mismatches_are_rejected(self):
        component_mismatch = self._normalized_after_replacements(
            {"M5 공정 직접배출 : 3.200 tCO2e/t": ("M5 공정 직접배출 : 3.201 tCO2e/t")}
        )
        with self.assertRaisesRegex(ValueError, "M5 component intensity"):
            calculate_exposure(component_mismatch)

        missing_component = self._normalized_after_replacements(
            {
                "M12 전구물질 간접배출 : 0.250 tCO2e/t": (
                    "M12 precursor indirect evidence intentionally omitted"
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "required normalized field"):
            calculate_exposure(missing_component)

        mass_mismatch = self._normalized_after_replacements(
            {"총 출하 중량 : 190,000 kg": "총 출하 중량 : 191,000 kg"}
        )
        with self.assertRaisesRegex(ValueError, "does not match shipment mass"):
            calculate_exposure(mass_mismatch)

        intensity_mismatch = self._normalized_after_replacements(
            {"실측 배출계수 : 5.849263 tCO2e/t": ("실측 배출계수 : 4 tCO2e/t")}
        )
        with self.assertRaisesRegex(ValueError, "weighted intensity"):
            calculate_exposure(intensity_mismatch)

    def test_duplicate_installation_is_rejected(self):
        normalized = self._normalized_after_replacements(
            {"M12 설비 ID : SYN-INSTALLATION-B": ("M12 설비 ID : SYN-INSTALLATION-A")}
        )
        with self.assertRaisesRegex(ValueError, "distinct installation evidence"):
            calculate_exposure(normalized)

    def test_negative_out_of_range_price_and_nonfinite_values_are_rejected(self):
        invalid_cases = (
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : -1 MT",
                "item mass must be positive",
            ),
            (
                "M5 공정 직접배출 : 3.200 tCO2e/t",
                "M5 공정 직접배출 : -0.001 tCO2e/t",
                "component intensity must be non-negative",
            ),
            (
                "실측 배출계수 : 5.849263 tCO2e/t",
                "실측 배출계수 : -1 tCO2e/t",
                "emission intensities must be non-negative",
            ),
            (
                "EU 기본값 : 7.311579 tCO2e/t",
                "EU 기본값 : -1 tCO2e/t",
                "emission intensities must be non-negative",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR -1 / tCO2e",
                "carbon prices must be non-negative",
            ),
            (
                "원산지 탄소가격 : EUR 0 / tCO2e",
                "원산지 탄소가격 : EUR -1 / tCO2e",
                "carbon prices must be non-negative",
            ),
            (
                "시나리오 노출계수 : 100%",
                "시나리오 노출계수 : -1%",
                "required normalized field is missing",
            ),
            (
                "시나리오 노출계수 : 100%",
                "시나리오 노출계수 : 101%",
                "required normalized field is missing",
            ),
            (
                "M12 전구물질 간접배출 : 0.250 tCO2e/t",
                "M12 전구물질 간접배출 : NaN tCO2e/t",
                "required normalized field is missing",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR Infinity / tCO2e",
                "required normalized field is missing",
            ),
            (
                "시나리오 노출계수 : 100%",
                "시나리오 노출계수 : -Infinity%",
                "required normalized field is missing",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR not-a-number / tCO2e",
                "required normalized field is missing",
            ),
        )
        for source, replacement, message in invalid_cases:
            with self.subTest(replacement=replacement):
                normalized = self._normalized_after_replacements({source: replacement})
                with self.assertRaisesRegex(ValueError, message):
                    calculate_exposure(normalized)

        for sign in ("−", "‐", "‑", "‒", "–", "—", "－", "﹣", "➖"):
            with self.subTest(unicode_minus=sign):
                normalized = self._normalized_after_replacements(
                    {
                        "CBAM 인증서 가격 : EUR 87.50 / tCO2e": (
                            f"CBAM 인증서 가격 : EUR {sign}1 / tCO2e"
                        )
                    }
                )
                price = normalized["fields"]["certificate_price_eur_per_tco2e"]
                self.assertEqual(price["value"], "-1")
                with self.assertRaisesRegex(
                    ValueError, "carbon prices must be non-negative"
                ):
                    calculate_exposure(normalized)

    def test_raw_ambiguous_values_cannot_reach_cbam_calculation(self):
        invalid_cases = (
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR .5 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR .5 / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR -.5 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR -.5 / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 1e3 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR 1e3 / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR (0.5) / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR (0.5) / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR （0.5） / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR （0.5） / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR ﹙0.5﹚ / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR ﹙0.5﹚ / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87¹ / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR 87¹ / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87① / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR 87① / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87₁ / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR 87₁ / tCO2e",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT (not kg)",
                "m5_mass_t",
                "90 MT (not kg)",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : USD 87.50 / tCO2e (not EUR)",
                "certificate_price_eur_per_tco2e",
                "USD 87.50 / tCO2e (not EUR)",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT/day",
                "m5_mass_t",
                "90 MT/day",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT/일",
                "m5_mass_t",
                "90 MT/일",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT∕일",
                "m5_mass_t",
                "90 MT∕일",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 tonne-force",
                "m5_mass_t",
                "90 tonne-force",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 US tons",
                "m5_mass_t",
                "90 US tons",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 short tons",
                "m5_mass_t",
                "90 short tons",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 long tons",
                "m5_mass_t",
                "90 long tons",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 imperial tons",
                "m5_mass_t",
                "90 imperial tons",
            ),
            (
                "M5 공정 직접배출 : 3.200 tCO2e/t",
                "M5 공정 직접배출 : 5 tCO2e/t / kg",
                "m5_process_direct_intensity_tco2e_per_t",
                "5 tCO2e/t / kg",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87.5 / tCO2e / kg",
                "certificate_price_eur_per_tco2e",
                "EUR 87.5 / tCO2e / kg",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : not 90 MT",
                "m5_mass_t",
                "not 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT 아님",
                "m5_mass_t",
                "90 MT 아님",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : 미적용 EUR 87.5 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "미적용 EUR 87.5 / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 20 / tCO2e 제외",
                "certificate_price_eur_per_tco2e",
                "EUR 20 / tCO2e 제외",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : <90 MT",
                "m5_mass_t",
                "<90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : ≤90 MT",
                "m5_mass_t",
                "≤90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : at most 90 MT",
                "m5_mass_t",
                "at most 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : up to 90 MT",
                "m5_mass_t",
                "up to 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT 이하",
                "m5_mass_t",
                "90 MT 이하",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : >90 MT",
                "m5_mass_t",
                ">90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : at least 90 MT",
                "m5_mass_t",
                "at least 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT 이상",
                "m5_mass_t",
                "90 MT 이상",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : maximum 90 MT",
                "m5_mass_t",
                "maximum 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT max",
                "m5_mass_t",
                "90 MT max",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : minimum 90 MT",
                "m5_mass_t",
                "minimum 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT min",
                "m5_mass_t",
                "90 MT min",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : no more than 90 MT",
                "m5_mass_t",
                "no more than 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : no less than 90 MT",
                "m5_mass_t",
                "no less than 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : less than 90 MT",
                "m5_mass_t",
                "less than 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : more than 90 MT",
                "m5_mass_t",
                "more than 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : greater than 90 MT",
                "m5_mass_t",
                "greater than 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : under 90 MT",
                "m5_mass_t",
                "under 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : over 90 MT",
                "m5_mass_t",
                "over 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : above 90 MT",
                "m5_mass_t",
                "above 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : below 90 MT",
                "m5_mass_t",
                "below 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : at or below 90 MT",
                "m5_mass_t",
                "at or below 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : at or above 90 MT",
                "m5_mass_t",
                "at or above 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : upper limit 90 MT",
                "m5_mass_t",
                "upper limit 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : lower limit 90 MT",
                "m5_mass_t",
                "lower limit 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : not exceeding 90 MT",
                "m5_mass_t",
                "not exceeding 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : not exceed 90 MT",
                "m5_mass_t",
                "not exceed 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 최대 90 MT",
                "m5_mass_t",
                "최대 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT 최소",
                "m5_mass_t",
                "90 MT 최소",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT를 넘지 않음",
                "m5_mass_t",
                "90 MT를 넘지 않음",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 상한 90 MT",
                "m5_mass_t",
                "상한 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 하한 90 MT",
                "m5_mass_t",
                "하한 90 MT",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT/",
                "m5_mass_t",
                "90 MT/",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT/%",
                "m5_mass_t",
                "90 MT/%",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87.5/tCO2e/",
                "certificate_price_eur_per_tco2e",
                "EUR 87.5/tCO2e/",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87.5/tCO2e/%",
                "certificate_price_eur_per_tco2e",
                "EUR 87.5/tCO2e/%",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR minus 0.5 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR minus 0.5 / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR negative 0.5 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR negative 0.5 / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 마이너스 0.5 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR 마이너스 0.5 / tCO2e",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 음수 0.5 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR 음수 0.5 / tCO2e",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 190 thousand kg",
                "m5_mass_t",
                "190 thousand kg",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 190 million kg",
                "m5_mass_t",
                "190 million kg",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 190 천 kg",
                "m5_mass_t",
                "190 천 kg",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 190 K MT",
                "m5_mass_t",
                "190 K MT",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87.5 thousand / tCO2e",
                "certificate_price_eur_per_tco2e",
                "EUR 87.5 thousand / tCO2e",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 90 MT (not valid)",
                "m5_mass_t",
                "90 MT (not valid)",
            ),
            (
                "M5 순중량 : 90 MT",
                "M5 순중량 : 해당 없음 90 MT",
                "m5_mass_t",
                "해당 없음 90 MT",
            ),
            (
                "CBAM 인증서 가격 : EUR 87.50 / tCO2e",
                "CBAM 인증서 가격 : EUR 87.5 / tCO2e (not applicable)",
                "certificate_price_eur_per_tco2e",
                "EUR 87.5 / tCO2e (not applicable)",
            ),
            (
                "CN code : 7318.15.52",
                "CN code : 7308 / 9098",
                "cn_code",
                "7308 / 9098",
            ),
        )
        for source, replacement, field_name, extracted_value in invalid_cases:
            with self.subTest(replacement=replacement):
                bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
                matches = [
                    line
                    for document in bundle["documents"]
                    for page in document["pages"]
                    for line in page["lines"]
                    if line["text"] == source
                ]
                self.assertEqual(len(matches), 1)
                matches[0]["text"] = replacement

                extracted = extract_document_bundle(bundle)
                record = next(
                    item
                    for item in extracted["records"]
                    if item["raw_line"] == replacement
                )
                self.assertEqual(record["value"], extracted_value)

                normalized = normalize_records(extracted, self.policy)
                field = normalized["fields"][field_name]
                self.assertEqual(field["selected_from"]["raw_value"], extracted_value)
                self.assertIsNone(field["value"])
                self.assertEqual(field["transformation"], "parse_failed")
                self.assertIn(
                    ("parse_failure", field_name, record["record_id"]),
                    {
                        (
                            issue["code"],
                            issue.get("field"),
                            issue.get("source", {}).get("record_id"),
                        )
                        for issue in normalized["issues"]
                    },
                )
                with self.assertRaisesRegex(
                    ValueError,
                    f"required normalized field is missing: {field_name}",
                ):
                    calculate_exposure(normalized)

    def test_price_scenario_defense_rejects_out_of_range_factor(self):
        for factor in (Decimal("-0.01"), Decimal("1.01")):
            with self.subTest(factor=factor):
                with self.assertRaisesRegex(ValueError, "factor must be within"):
                    _price_scenario(
                        scenario_id="invalid-factor",
                        embedded_emissions=Decimal("1"),
                        certificate_price=Decimal("1"),
                        third_country_price=Decimal("0"),
                        exposure_factor=factor,
                        embedded_emissions_source={"derived_from": "test"},
                        input_sources={},
                        classification="test-only",
                    )

    def test_energy_memo_values_do_not_enter_inventory_or_price_calculation(self):
        normalized = self._normalized_after_replacements(
            {
                "전기사용량 : 970,000 kWh": "전기사용량 : 1,234,567 kWh",
                "LNG 사용량 : 39,300 Nm3": "LNG 사용량 : 987,654 Nm3",
            }
        )
        changed = calculate_exposure(normalized)

        for section in (
            "technical_inventory",
            "actual_data_scenario",
            "default_value_scenario",
            "difference",
            "sensitivity_scenarios",
            "reconciliation",
        ):
            with self.subTest(section=section):
                self.assertEqual(changed[section], self.result[section])
        self.assertEqual(
            self.result["unused_evidence"][0]["fields"],
            ["electricity_kwh", "lng_nm3"],
        )

        ambiguous_optional_inputs = (
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 MWh, not kWh",
                "electricity_kwh",
            ),
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 kWh/일",
                "electricity_kwh",
            ),
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 kWh/day",
                "electricity_kwh",
            ),
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 kWh∕day",
                "electricity_kwh",
            ),
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 kWh⁄day",
                "electricity_kwh",
            ),
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 kWh⧸day",
                "electricity_kwh",
            ),
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 kWh/",
                "electricity_kwh",
            ),
            (
                "전기사용량 : 970,000 kWh",
                "전기사용량 : 970000 kWh/%",
                "electricity_kwh",
            ),
            (
                "LNG 사용량 : 39,300 Nm3",
                "LNG 사용량 : 39.3 Nm3/hour",
                "lng_nm3",
            ),
            (
                "LNG 사용량 : 39,300 Nm3",
                "LNG 사용량 : 39.3 Nm3/시간",
                "lng_nm3",
            ),
            (
                "LNG 사용량 : 39,300 Nm3",
                "LNG 사용량 : 39.3 Nm3⁄시간",
                "lng_nm3",
            ),
            (
                "LNG 사용량 : 39,300 Nm3",
                "LNG 사용량 : 39.3 Nm3∕시간",
                "lng_nm3",
            ),
            (
                "LNG 사용량 : 39,300 Nm3",
                "LNG 사용량 : 39300 Nm3/",
                "lng_nm3",
            ),
            (
                "LNG 사용량 : 39,300 Nm3",
                "LNG 사용량 : 39300 Nm3/%",
                "lng_nm3",
            ),
        )
        for source, replacement, field_name in ambiguous_optional_inputs:
            with self.subTest(replacement=replacement):
                ambiguous_energy = self._normalized_after_replacements(
                    {source: replacement}
                )
                energy_field = ambiguous_energy["fields"][field_name]
                self.assertIsNone(energy_field["value"])
                self.assertEqual(energy_field["transformation"], "parse_failed")
                self.assertIn(
                    ("parse_failure", field_name),
                    {
                        (issue["code"], issue.get("field"))
                        for issue in ambiguous_energy["issues"]
                    },
                )
                quarantined = calculate_exposure(ambiguous_energy)
                for section in (
                    "technical_inventory",
                    "actual_data_scenario",
                    "default_value_scenario",
                    "difference",
                    "sensitivity_scenarios",
                    "reconciliation",
                ):
                    with self.subTest(ambiguous_energy_section=section):
                        self.assertEqual(quarantined[section], self.result[section])

    def test_output_is_explicitly_non_statutory_and_has_no_payable_field(self):
        self.assertFalse(self.result["statutory_calculator"])
        for scenario in self.result["sensitivity_scenarios"]:
            self.assertFalse(scenario["statutory_obligation"])

        keys = {key.casefold() for key in _keys(self.result)}
        for forbidden in (
            "payable",
            "amount_due",
            "official_obligation",
            "certificate_obligation",
            "statutory_amount",
        ):
            self.assertFalse(
                any(forbidden in key for key in keys),
                f"forbidden payable/statutory output key: {forbidden}",
            )
        serialized = json.dumps(self.result, ensure_ascii=False).casefold()
        self.assertNotIn('"statutory_calculator": true', serialized)
        self.assertNotIn('"statutory_obligation": true', serialized)
        self.assertNotIn("amount due", serialized)

    def test_document_input_order_does_not_change_cbam_result(self):
        payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
        reordered = copy.deepcopy(payload)
        reordered["documents"].reverse()
        for document in reordered["documents"]:
            document["pages"].reverse()
            for page in document["pages"]:
                page["lines"].reverse()

        normalized = normalize_records(extract_document_bundle(reordered), self.policy)
        self.assertEqual(calculate_exposure(normalized), self.result)


if __name__ == "__main__":
    unittest.main()
