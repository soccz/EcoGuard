import copy
import unittest
from pathlib import Path

from ecoguard.ingestion import extract_document_bundle_file
from ecoguard.preprocessing import load_policy, normalize_records


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/synthetic/trade_case_documents.json"
POLICY = ROOT / "data/reference/normalization_policy.json"


class PreprocessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extracted = extract_document_bundle_file(BUNDLE)
        cls.policy = load_policy(POLICY)
        cls.result = normalize_records(cls.extracted, cls.policy)

    def test_units_components_and_aliases_are_normalized(self):
        mass = self.result["fields"]["shipment_mass_t"]
        self.assertEqual(mass["value"], "190")
        self.assertEqual(mass["unit"], "t")
        self.assertEqual(mass["transformation"], "kg_to_t")
        self.assertEqual(len(mass["candidates"]), 3)
        self.assertEqual(self.result["fields"]["m12_mass_t"]["value"], "100")
        self.assertEqual(
            self.result["fields"]["m5_process_direct_intensity_tco2e_per_t"]["value"],
            "3.2",
        )
        self.assertEqual(
            self.result["fields"]["m12_precursor_indirect_intensity_tco2e_per_t"][
                "value"
            ],
            "0.25",
        )

    def test_selection_trace_keeps_span_hash_and_document_authority(self):
        field = self.result["fields"]["shipment_mass_t"]
        source = field["selected_from"]
        self.assertEqual(source["document"], "commercial_invoice")
        self.assertEqual(source["record_id"], "ev-commercial-invoice-p01-l004")
        self.assertEqual(source["authority_rank"], 100)
        self.assertEqual(source["raw_value"], "190,000 kg")
        self.assertEqual(len(source["line_sha256"]), 64)
        self.assertIsNotNone(source["source_span"])
        self.assertEqual(field["selection"]["policy_id"], "ecoguard-normalization-v2")
        self.assertEqual(field["candidates"][0]["selection_rank"], 1)
        self.assertTrue(field["candidates"][0]["selected"])

    def test_material_conflict_and_rounding_variance_are_distinguished(self):
        conflicts = {
            issue.get("field")
            for issue in self.result["issues"]
            if issue["code"] == "cross_document_conflict"
        }
        self.assertEqual(conflicts, {"shipment_mass_t"})
        observation = next(
            item
            for item in self.result["observations"]
            if item["field"] == "actual_intensity_tco2e_per_t"
        )
        self.assertEqual(observation["code"], "within_tolerance_variance")
        self.assertEqual(
            observation["alternatives"][0]["absolute_difference"], "0.000737"
        )

    def test_ambiguous_raw_line_and_missing_verification_enter_review(self):
        codes = {(issue["code"], issue.get("field")) for issue in self.result["issues"]}
        self.assertIn(("parse_failure", "actual_intensity_tco2e_per_t"), codes)
        self.assertIn(("missing_required_evidence", "verification_reference"), codes)
        self.assertEqual(self.result["summary"]["status"], "review")
        self.assertEqual(self.result["summary"]["issue_count"], 3)

    def test_validation_ledger_covers_every_required_field(self):
        required = [
            check
            for check in self.result["validation_ledger"]
            if check["check_id"].startswith("required.")
        ]
        self.assertEqual(len(required), self.result["summary"]["required_field_count"])
        failed = {check["check_id"] for check in required if check["status"] == "fail"}
        self.assertEqual(failed, {"required.verification_reference"})

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

    def test_invalid_cn_confidence_and_price_units_are_reviewed(self):
        payload = {
            "case_id": "INVALID",
            "records": [
                {
                    "document": "memo",
                    "location": "line 1",
                    "label": "CN code",
                    "value": "not available",
                    "confidence": "NaN",
                },
                {
                    "document": "memo",
                    "location": "line 2",
                    "label": "CBAM 인증서 가격",
                    "value": "EUR 87.50 total",
                    "confidence": 1.0,
                },
                {
                    "document": "memo",
                    "location": "line 3",
                    "label": "원산지 탄소가격",
                    "value": "EUR 12 / kg",
                    "confidence": 1.0,
                },
            ],
        }
        result = normalize_records(payload)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("parse_failure", codes)
        self.assertIn("invalid_confidence", codes)
        self.assertIsNone(result["fields"]["cn_code"]["value"])
        self.assertIsNone(result["fields"]["certificate_price_eur_per_tco2e"]["value"])
        self.assertIsNone(result["fields"]["carbon_price_paid_eur_per_tco2e"]["value"])

    def test_policy_rejects_invalid_authority_and_tolerance(self):
        invalid = copy.deepcopy(self.policy)
        invalid["source_authority"]["memo"] = -1
        with self.assertRaises(ValueError):
            normalize_records(self.extracted, invalid)
        invalid = copy.deepcopy(self.policy)
        invalid["field_overrides"]["shipment_mass_t"][
            "absolute_conflict_tolerance"
        ] = "NaN"
        with self.assertRaises(ValueError):
            normalize_records(self.extracted, invalid)


if __name__ == "__main__":
    unittest.main()
