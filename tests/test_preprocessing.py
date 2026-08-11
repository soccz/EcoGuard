import json
import unittest
from pathlib import Path

from ecoguard.preprocessing import normalize_records


ROOT = Path(__file__).resolve().parents[1]


class PreprocessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(
            (ROOT / "data/synthetic/ocr_records.json").read_text(encoding="utf-8")
        )
        cls.result = normalize_records(cls.payload)

    def test_units_and_aliases_are_normalized(self):
        mass = self.result["fields"]["shipment_mass_t"]
        self.assertEqual(mass["value"], "190")
        self.assertEqual(mass["unit"], "t")
        self.assertEqual(len(mass["candidates"]), 3)
        self.assertEqual(self.result["fields"]["m12_mass_t"]["value"], "100")
        self.assertEqual(
            self.result["fields"]["m12_intensity_tco2e_per_t"]["value"],
            "6.088",
        )

    def test_selected_value_keeps_source_location(self):
        source = self.result["fields"]["shipment_mass_t"]["selected_from"]
        self.assertEqual(source["document"], "commercial_invoice")
        self.assertEqual(source["location"], "page 1 / total net weight")
        self.assertEqual(source["raw_value"], "190,000 kg")

    def test_conflicts_and_missing_evidence_enter_review_queue(self):
        codes = {(issue["code"], issue.get("field")) for issue in self.result["issues"]}
        self.assertIn(("cross_document_conflict", "shipment_mass_t"), codes)
        self.assertIn(
            ("cross_document_conflict", "actual_intensity_tco2e_per_t"), codes
        )
        self.assertIn(("missing_required_evidence", "verification_reference"), codes)
        self.assertEqual(self.result["summary"]["status"], "review")

    def test_empty_input_never_passes(self):
        result = normalize_records({"case_id": "EMPTY", "records": []})
        self.assertEqual(result["summary"]["status"], "review")
        self.assertIn("empty_input", {issue["code"] for issue in result["issues"]})
        self.assertIn(
            "missing_required_field",
            {issue["code"] for issue in result["issues"]},
        )

    def test_invalid_high_confidence_candidate_cannot_hide_valid_value(self):
        payload = {
            "case_id": "UNIT",
            "records": [
                {
                    "document": "bad",
                    "location": "row 1",
                    "label": "총 출하 중량",
                    "value": "190 lb",
                    "confidence": 0.99,
                },
                {
                    "document": "good",
                    "location": "row 2",
                    "label": "NET WT",
                    "value": "190 MT",
                    "confidence": 0.5,
                },
            ],
        }
        result = normalize_records(payload)
        selected = result["fields"]["shipment_mass_t"]
        self.assertEqual(selected["value"], "190")
        self.assertEqual(selected["selected_from"]["document"], "good")
        self.assertIn("parse_failure", {issue["code"] for issue in result["issues"]})

    def test_invalid_cn_and_confidence_are_review_issues(self):
        payload = {
            "case_id": "INVALID",
            "records": [
                {
                    "document": "memo",
                    "location": "line 1",
                    "label": "CN code",
                    "value": "not available",
                    "confidence": "NaN",
                }
            ],
        }
        result = normalize_records(payload)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("parse_failure", codes)
        self.assertIn("invalid_confidence", codes)
        self.assertIsNone(result["fields"]["cn_code"]["value"])

    def test_carbon_prices_require_currency_and_per_tco2e_unit(self):
        payload = {
            "case_id": "BAD-PRICE-UNITS",
            "records": [
                {
                    "document": "memo",
                    "location": "line 1",
                    "label": "CBAM 인증서 가격",
                    "value": "EUR 87.50 total",
                    "confidence": 1.0,
                },
                {
                    "document": "memo",
                    "location": "line 2",
                    "label": "원산지 탄소가격",
                    "value": "EUR 12 / kg",
                    "confidence": 1.0,
                },
            ],
        }
        result = normalize_records(payload)
        self.assertIsNone(
            result["fields"]["certificate_price_eur_per_tco2e"]["value"]
        )
        self.assertIsNone(
            result["fields"]["carbon_price_paid_eur_per_tco2e"]["value"]
        )
        failures = [
            issue for issue in result["issues"] if issue["code"] == "parse_failure"
        ]
        self.assertEqual(len(failures), 2)


if __name__ == "__main__":
    unittest.main()
