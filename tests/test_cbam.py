import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

from ecoguard.cbam import calculate_exposure
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

    def test_v2_golden_inventory_and_legacy_comparison(self):
        self.assertEqual(self.result["schema_version"], "cbam-scenario/2.0")
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

    def test_zero_floor_prevents_negative_exposure(self):
        normalized = self._normalized_copy()
        normalized["fields"]["carbon_price_paid_eur_per_tco2e"]["value"] = "100"
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
                with self.assertRaisesRegex(ValueError, "no evidence reference"):
                    calculate_exposure(normalized)

    def test_component_see_mass_and_weighted_intensity_mismatches_are_rejected(self):
        component_mismatch = self._normalized_copy()
        component_mismatch["fields"]["m5_process_direct_intensity_tco2e_per_t"][
            "value"
        ] = "3.201"
        with self.assertRaisesRegex(ValueError, "M5 component intensity"):
            calculate_exposure(component_mismatch)

        missing_component = self._normalized_copy()
        del missing_component["fields"]["m12_precursor_indirect_intensity_tco2e_per_t"]
        with self.assertRaisesRegex(ValueError, "required normalized field"):
            calculate_exposure(missing_component)

        mass_mismatch = self._normalized_copy()
        mass_mismatch["fields"]["shipment_mass_t"]["value"] = "191"
        with self.assertRaisesRegex(ValueError, "does not match shipment mass"):
            calculate_exposure(mass_mismatch)

        intensity_mismatch = self._normalized_copy()
        intensity_mismatch["fields"]["actual_intensity_tco2e_per_t"]["value"] = "4"
        with self.assertRaisesRegex(ValueError, "weighted intensity"):
            calculate_exposure(intensity_mismatch)

    def test_duplicate_installation_is_rejected(self):
        normalized = self._normalized_copy()
        normalized["fields"]["m12_installation_id"]["value"] = normalized["fields"][
            "m5_installation_id"
        ]["value"]
        with self.assertRaisesRegex(ValueError, "distinct installation evidence"):
            calculate_exposure(normalized)

    def test_negative_out_of_range_price_and_nonfinite_values_are_rejected(self):
        invalid_cases = (
            ("m5_mass_t", "-1"),
            ("m5_process_direct_intensity_tco2e_per_t", "-0.001"),
            ("actual_intensity_tco2e_per_t", "-1"),
            ("default_intensity_tco2e_per_t", "-1"),
            ("certificate_price_eur_per_tco2e", "-1"),
            ("carbon_price_paid_eur_per_tco2e", "-1"),
            ("scenario_exposure_factor", "-0.01"),
            ("scenario_exposure_factor", "1.01"),
            ("m12_precursor_indirect_intensity_tco2e_per_t", "NaN"),
            ("certificate_price_eur_per_tco2e", "Infinity"),
            ("scenario_exposure_factor", "-Infinity"),
        )
        for field, value in invalid_cases:
            with self.subTest(field=field, value=value):
                normalized = self._normalized_copy()
                normalized["fields"][field]["value"] = value
                with self.assertRaises(ValueError):
                    calculate_exposure(normalized)

    def test_energy_memo_values_do_not_enter_inventory_or_price_calculation(self):
        normalized = self._normalized_copy()
        normalized["fields"]["electricity_kwh"]["value"] = "123456789"
        normalized["fields"]["lng_nm3"]["value"] = "987654321"
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
