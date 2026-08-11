import json
import copy
import unittest
from pathlib import Path

from ecoguard.cbam import calculate_exposure
from ecoguard.preprocessing import normalize_records


ROOT = Path(__file__).resolve().parents[1]


class CbamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = json.loads(
            (ROOT / "data/synthetic/ocr_records.json").read_text(encoding="utf-8")
        )
        cls.result = calculate_exposure(normalize_records(raw))

    def test_golden_exposure_scenarios(self):
        self.assertEqual(
            self.result["actual_data_scenario"]["embedded_emissions_tco2e"],
            "1111.36",
        )
        self.assertEqual(
            self.result["actual_data_scenario"]["exposure_eur"], "97244.00"
        )
        self.assertEqual(
            self.result["default_value_scenario"]["embedded_emissions_tco2e"],
            "1389.20",
        )
        self.assertEqual(
            self.result["default_value_scenario"]["exposure_eur"], "121555.00"
        )
        self.assertEqual(self.result["difference"]["exposure_eur"], "24311.00")

    def test_assumptions_are_exposed(self):
        self.assertEqual(
            self.result["classification"], "gross_price_sensitivity_scenario"
        )
        self.assertIn("phase_in_factor", self.result["inputs"])
        self.assertTrue(self.result["assumptions"])

    def test_line_items_reconcile_to_shipment_total(self):
        actual = self.result["actual_data_scenario"]
        self.assertEqual(
            [item["embedded_emissions_tco2e"] for item in actual["line_items"]],
            ["502.56", "608.80"],
        )
        self.assertEqual(actual["weighted_intensity_tco2e_per_t"], "5.849263")
        self.assertEqual(
            actual["line_items"][0]["mass_source"]["record_id"],
            "record-004",
        )
        self.assertIn(
            "certificate_price_eur_per_tco2e",
            self.result["input_provenance"],
        )
        self.assertTrue(self.result["reconciliation"]["mass_matches"])
        self.assertEqual(
            self.result["reconciliation"]["absolute_intensity_difference"],
            "0.000000158",
        )
        self.assertTrue(self.result["reconciliation"]["intensity_matches"])

    def test_partial_or_inconsistent_line_items_are_rejected(self):
        raw = json.loads(
            (ROOT / "data/synthetic/ocr_records.json").read_text(encoding="utf-8")
        )
        normalized = normalize_records(raw)

        partial = copy.deepcopy(normalized)
        del partial["fields"]["m12_intensity_tco2e_per_t"]
        with self.assertRaisesRegex(ValueError, "partial line-item"):
            calculate_exposure(partial)

        mismatch = copy.deepcopy(normalized)
        mismatch["fields"]["actual_intensity_tco2e_per_t"]["value"] = "4"
        with self.assertRaisesRegex(ValueError, "does not reconcile"):
            calculate_exposure(mismatch)

    def test_invalid_prices_and_non_finite_values_are_rejected(self):
        raw = json.loads(
            (ROOT / "data/synthetic/ocr_records.json").read_text(encoding="utf-8")
        )
        normalized = normalize_records(raw)
        for field, value in (
            ("certificate_price_eur_per_tco2e", "-1"),
            ("carbon_price_paid_eur_per_tco2e", "-1"),
            ("phase_in_factor", "NaN"),
        ):
            with self.subTest(field=field):
                invalid = copy.deepcopy(normalized)
                invalid["fields"][field]["value"] = value
                with self.assertRaises(ValueError):
                    calculate_exposure(invalid)


if __name__ == "__main__":
    unittest.main()
