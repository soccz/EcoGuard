import copy
import unittest
from hashlib import sha256
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

    def test_fixture_claim_counts_are_exact_and_auditable(self):
        self.assertEqual(self.extracted["summary"]["matched_line_count"], 30)
        self.assertEqual(self.result["summary"]["field_count"], 26)
        self.assertEqual(self.result["summary"]["issue_count"], 3)
        self.assertEqual(self.result["summary"]["observation_count"], 1)

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

    def test_invalid_confidence_and_ambiguous_numbers_are_unselectable(self):
        payload = {
            "case_id": "INVALID-CANDIDATES",
            "records": [
                {
                    "record_id": "bad-confidence",
                    "document": "memo",
                    "location": "line 1",
                    "label": "총 출하 중량",
                    "value": "190 t",
                    "confidence": "NaN",
                },
                {
                    "record_id": "ambiguous-value",
                    "document": "memo",
                    "location": "line 2",
                    "label": "원산지 탄소가격",
                    "value": "EUR 12/13 / tCO2e",
                    "confidence": 1.0,
                },
            ],
        }
        result = normalize_records(payload)
        self.assertIsNone(result["fields"]["shipment_mass_t"]["value"])
        self.assertEqual(
            result["fields"]["shipment_mass_t"]["transformation"],
            "confidence_invalid",
        )
        self.assertIsNone(result["fields"]["carbon_price_paid_eur_per_tco2e"]["value"])
        self.assertEqual(
            {issue["code"] for issue in result["issues"]}
            & {"invalid_confidence", "parse_failure"},
            {"invalid_confidence", "parse_failure"},
        )

        boolean_confidence = copy.deepcopy(payload)
        boolean_confidence["records"] = [boolean_confidence["records"][0]]
        boolean_confidence["records"][0]["confidence"] = True
        result = normalize_records(boolean_confidence)
        self.assertIsNone(result["fields"]["shipment_mass_t"]["value"])

    def test_numeric_grammar_preserves_supported_grouping_and_signs(self):
        cases = (
            ("NET WT", "190,000 kg", "shipment_mass_t", "190"),
            ("NET WT", "190 metric tons", "shipment_mass_t", "190"),
            (
                "M5 공정 직접배출",
                "-0.001 tCO2e/t",
                "m5_process_direct_intensity_tco2e_per_t",
                "-0.001",
            ),
            (
                "CBAM 인증서 가격",
                "EUR +87.50 / tCO2e",
                "certificate_price_eur_per_tco2e",
                "87.5",
            ),
            (
                "CBAM 인증서 가격",
                "EUR 87.50/tCO2e",
                "certificate_price_eur_per_tco2e",
                "87.5",
            ),
            (
                "CBAM 인증서 가격",
                "87.50 EUR / tCO2e",
                "certificate_price_eur_per_tco2e",
                "87.5",
            ),
            (
                "CBAM 인증서 가격",
                "87.50 € / tCO2e",
                "certificate_price_eur_per_tco2e",
                "87.5",
            ),
        )
        for label, raw_value, field, expected in cases:
            with self.subTest(raw_value=raw_value):
                result = normalize_records(
                    {
                        "case_id": "SUPPORTED-NUMBER",
                        "records": [
                            {
                                "document": "memo",
                                "location": "line 1",
                                "label": label,
                                "value": raw_value,
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
                self.assertEqual(result["fields"][field]["value"], expected)

        for sign in ("−", "‐", "‑", "‒", "–", "—", "－", "﹣", "➖"):
            with self.subTest(unicode_minus=sign):
                result = normalize_records(
                    {
                        "case_id": "UNICODE-MINUS",
                        "records": [
                            {
                                "document": "memo",
                                "location": "line 1",
                                "label": "CBAM 인증서 가격",
                                "value": f"EUR {sign}1 / tCO2e",
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
                self.assertEqual(
                    result["fields"]["certificate_price_eur_per_tco2e"]["value"],
                    "-1",
                )

    def test_unsupported_numeric_and_unit_tokens_are_not_partially_matched(self):
        for token in (
            ".5",
            "-.5",
            "1e3",
            "1,00",
            "- 1",
            "(0.5)",
            "（0.5）",
            "﹙0.5﹚",
            "87¹",
            "87①",
            "87₁",
            "①",
            "⁸⁷",
            "<190",
            "≤190",
            "at most 190",
            "up to 190",
            "190 이하",
            ">190",
            "at least 190",
            "190 이상",
            "190 미만",
            "190 초과",
            "maximum 190",
            "190 max",
            "minimum 190",
            "190 min",
            "no more than 190",
            "no less than 190",
            "less than 190",
            "more than 190",
            "greater than 190",
            "under 190",
            "over 190",
            "above 190",
            "below 190",
            "at or below 190",
            "at or above 190",
            "upper limit 190",
            "lower limit 190",
            "not exceeding 190",
            "not exceed 190",
            "최대 190",
            "190 최소",
            "190을 넘지 않음",
            "상한 190",
            "하한 190",
            "minus 0.5",
            "negative 0.5",
            "마이너스 0.5",
            "음수 0.5",
            "190 thousand",
            "190 million",
            "190 billion",
            "190 K",
            "190 천",
            "190 만",
            "190 백만",
            "not valid 190",
            "190 (not applicable)",
            "190 아님",
            "해당 없음 190",
            "미적용 190",
            "190 제외",
        ):
            with self.subTest(token=token):
                result = normalize_records(
                    {
                        "case_id": "UNSUPPORTED-NUMBER",
                        "records": [
                            {
                                "document": "memo",
                                "location": "line 1",
                                "label": "CBAM 인증서 가격",
                                "value": f"EUR {token} / tCO2e",
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
                field = result["fields"]["certificate_price_eur_per_tco2e"]
                self.assertIsNone(field["value"])
                self.assertEqual(field["transformation"], "parse_failed")
                parse_issue = next(
                    issue
                    for issue in result["issues"]
                    if issue["code"] == "parse_failure"
                )
                self.assertEqual(parse_issue["severity"], "review")
                self.assertIn("numeric", parse_issue["message"])

        ambiguous_units = (
            ("NET WT", "190 MT (not kg)", "shipment_mass_t"),
            (
                "M5 공정 직접배출",
                "5 tCO2e/t (not kgCO2e/kg)",
                "m5_process_direct_intensity_tco2e_per_t",
            ),
            (
                "CBAM 인증서 가격",
                "USD 87.50 / tCO2e (not EUR)",
                "certificate_price_eur_per_tco2e",
            ),
            (
                "CBAM 인증서 가격",
                "EUR 87.50 / tCO2e (not /kgCO2e)",
                "certificate_price_eur_per_tco2e",
            ),
            ("전기사용량", "970000 MWh, not kWh", "electricity_kwh"),
            ("LNG 사용량", "39,300 m3 (not Nm3)", "lng_nm3"),
            ("NET WT", "190 MT/day", "shipment_mass_t"),
            ("NET WT", "190 MT/", "shipment_mass_t"),
            ("NET WT", "190 MT/%", "shipment_mass_t"),
            ("NET WT", "190 MT/일", "shipment_mass_t"),
            ("NET WT", "190 MT∕일", "shipment_mass_t"),
            ("NET WT", "190 MT⁄일", "shipment_mass_t"),
            ("NET WT", "190 MT⧸일", "shipment_mass_t"),
            ("NET WT", "190 MT perday", "shipment_mass_t"),
            ("NET WT", "190 tonne-force", "shipment_mass_t"),
            ("NET WT", "190 US tons", "shipment_mass_t"),
            ("NET WT", "190 short tons", "shipment_mass_t"),
            ("NET WT", "190 long tons", "shipment_mass_t"),
            ("NET WT", "190 imperial tons", "shipment_mass_t"),
            (
                "M5 공정 직접배출",
                "5 tCO2e/t / kg",
                "m5_process_direct_intensity_tco2e_per_t",
            ),
            (
                "CBAM 인증서 가격",
                "EUR 87.50 / tCO2e / kg",
                "certificate_price_eur_per_tco2e",
            ),
            (
                "CBAM 인증서 가격",
                "EUR 87.50/tCO2e/",
                "certificate_price_eur_per_tco2e",
            ),
            (
                "CBAM 인증서 가격",
                "EUR 87.50/tCO2e/%",
                "certificate_price_eur_per_tco2e",
            ),
            ("전기사용량", "970000 kWh/day", "electricity_kwh"),
            ("전기사용량", "970000 kWh/", "electricity_kwh"),
            ("전기사용량", "970000 kWh/%", "electricity_kwh"),
            ("전기사용량", "970000 kWh/일", "electricity_kwh"),
            ("전기사용량", "970000 kWh∕day", "electricity_kwh"),
            ("전기사용량", "970000 kWh⁄day", "electricity_kwh"),
            ("전기사용량", "970000 kWh⧸day", "electricity_kwh"),
            ("LNG 사용량", "39.3 Nm3/hour", "lng_nm3"),
            ("LNG 사용량", "39.3 Nm3/", "lng_nm3"),
            ("LNG 사용량", "39.3 Nm3/%", "lng_nm3"),
            ("LNG 사용량", "39.3 Nm3/시간", "lng_nm3"),
            ("LNG 사용량", "39.3 Nm3∕시간", "lng_nm3"),
            ("LNG 사용량", "39.3 Nm3⁄시간", "lng_nm3"),
        )
        for label, raw_value, field_name in ambiguous_units:
            with self.subTest(raw_value=raw_value):
                result = normalize_records(
                    {
                        "case_id": "AMBIGUOUS-UNIT",
                        "records": [
                            {
                                "document": "memo",
                                "location": "line 1",
                                "label": label,
                                "value": raw_value,
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
                field = result["fields"][field_name]
                self.assertIsNone(field["value"])
                self.assertEqual(field["transformation"], "parse_failed")
                self.assertIn(
                    ("parse_failure", field_name, "review"),
                    {
                        (issue["code"], issue.get("field"), issue["severity"])
                        for issue in result["issues"]
                    },
                )

    def test_cn_code_requires_one_eight_digit_code(self):
        valid_cases = {
            "73181552": "73181552",
            "7318.15.52": "73181552",
            "7318 15 52": "73181552",
            "7318-15-52": "73181552",
        }
        for raw_value, expected in valid_cases.items():
            with self.subTest(valid=raw_value):
                result = normalize_records(
                    {
                        "case_id": "VALID-CN",
                        "records": [
                            {
                                "document": "invoice",
                                "location": "line 1",
                                "label": "CN code",
                                "value": raw_value,
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
                self.assertEqual(result["fields"]["cn_code"]["value"], expected)

        for raw_value in (
            "CN 7308 / 9098",
            "7308 / 9098",
            "73181552 / 73089098",
            "7318.15-52",
        ):
            with self.subTest(invalid=raw_value):
                result = normalize_records(
                    {
                        "case_id": "AMBIGUOUS-CN",
                        "records": [
                            {
                                "document": "invoice",
                                "location": "line 1",
                                "label": "CN code",
                                "value": raw_value,
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
                field = result["fields"]["cn_code"]
                self.assertIsNone(field["value"])
                self.assertEqual(field["transformation"], "parse_failed")
                parse_issue = next(
                    issue
                    for issue in result["issues"]
                    if issue["code"] == "parse_failure"
                )
                self.assertEqual(parse_issue["severity"], "review")
                self.assertIn("invalid or ambiguous CN code", parse_issue["message"])

    def test_optional_parse_failure_is_not_mislabeled_as_required_evidence(self):
        result = normalize_records(
            {
                "case_id": "OPTIONAL",
                "records": [
                    {
                        "document": "memo",
                        "location": "line 1",
                        "label": "전기사용량",
                        "value": "unknown",
                        "confidence": 1.0,
                    }
                ],
            }
        )
        self.assertIn("parse_failure", {issue["code"] for issue in result["issues"]})
        self.assertNotIn(
            ("missing_required_evidence", "electricity_kwh"),
            {(issue["code"], issue.get("field")) for issue in result["issues"]},
        )

    def test_tampered_adapter_provenance_cannot_enter_calculation_fields(self):
        record = copy.deepcopy(self.extracted["records"][0])
        record["raw_line"] += " tampered"
        tampered_cases = [record]
        updated_line_hash = copy.deepcopy(record)
        updated_line_hash["line_sha256"] = sha256(
            updated_line_hash["raw_line"].encode("utf-8")
        ).hexdigest()
        tampered_cases.append(updated_line_hash)

        for tampered in tampered_cases:
            with self.subTest(line_hash=tampered["line_sha256"]):
                payload = copy.deepcopy(self.extracted)
                payload["records"][0] = tampered
                result = normalize_records(payload)
                field = result["fields"]["m5_installation_id"]
                self.assertIsNone(field["value"])
                self.assertEqual(field["transformation"], "provenance_failed")
                self.assertIn(
                    "provenance_integrity_failure",
                    {issue["code"] for issue in result["issues"]},
                )

    def test_empty_extracted_value_requires_a_real_blank_marker(self):
        label = "검증서 번호"
        raw_value = "ABC-VERIFIED"
        raw_line = f"{label} : {raw_value}"
        value_start = raw_line.index(raw_value)
        record = {
            "record_id": "ev-forged-blank",
            "document": "forged_document",
            "document_type": "cbam_product_sheet",
            "location": "page 1 / line 1",
            "page": 1,
            "line": 1,
            "label": label,
            "value": "",
            "confidence": 0.99,
            "extractor": "deterministic_alias_adapter_v1",
            "source_span": {
                "alias_start": 0,
                "alias_end": len(label),
                "value_start": value_start,
                "value_end": len(raw_line),
            },
            "raw_line": raw_line,
            "line_sha256": sha256(raw_line.encode("utf-8")).hexdigest(),
            "document_sha256": "0" * 64,
        }
        result = normalize_records({"case_id": "FORGED", "records": [record]})
        self.assertIn(
            "provenance_integrity_failure",
            {issue["code"] for issue in result["issues"]},
        )

    def test_duplicate_record_ids_and_explicit_empty_policy_are_rejected(self):
        duplicate = copy.deepcopy(self.extracted)
        duplicate["records"][1]["record_id"] = duplicate["records"][0]["record_id"]
        with self.assertRaisesRegex(ValueError, "duplicate record_id"):
            normalize_records(duplicate, self.policy)
        with self.assertRaisesRegex(ValueError, "policy_id"):
            normalize_records(self.extracted, {})
        with self.assertRaisesRegex(ValueError, "records must be a list"):
            normalize_records({"case_id": "INVALID", "records": {}})

    def test_adapter_payload_schema_version_is_enforced(self):
        for schema_version in (None, "0.0.0", "ocr-document-bundle/1.0"):
            with self.subTest(schema_version=schema_version):
                payload = copy.deepcopy(self.extracted)
                if schema_version is None:
                    del payload["schema_version"]
                else:
                    payload["schema_version"] = schema_version
                with self.assertRaisesRegex(ValueError, "extracted evidence schema"):
                    normalize_records(payload, self.policy)

    def test_policy_rejects_invalid_authority_and_tolerance(self):
        invalid = copy.deepcopy(self.policy)
        invalid["selection_strategy"] = "select random candidate"
        with self.assertRaisesRegex(ValueError, "unsupported.*selection_strategy"):
            normalize_records(self.extracted, invalid)

        invalid = copy.deepcopy(self.policy)
        invalid["source_authority"]["memo"] = -1
        with self.assertRaises(ValueError):
            normalize_records(self.extracted, invalid)

        invalid = copy.deepcopy(self.policy)
        invalid["field_overrides"]["shipment_mass_t"]["absolute_conflict_tolerance"] = 1
        with self.assertRaisesRegex(ValueError, "invalid conflict tolerance"):
            normalize_records(self.extracted, invalid)

        invalid = copy.deepcopy(self.policy)
        invalid["unexpected"] = "not in the public schema"
        with self.assertRaisesRegex(ValueError, "unsupported normalization policy"):
            normalize_records(self.extracted, invalid)

        invalid = copy.deepcopy(self.policy)
        invalid["field_overrides"]["shipment_mass_t"]["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unsupported field override"):
            normalize_records(self.extracted, invalid)

        invalid = copy.deepcopy(self.policy)
        invalid["field_overrides"]["shipmnt_mass_t"] = {
            "absolute_conflict_tolerance": "999"
        }
        with self.assertRaisesRegex(ValueError, "normalization field override"):
            normalize_records(self.extracted, invalid)
        invalid = copy.deepcopy(self.policy)
        invalid["field_overrides"]["shipment_mass_t"][
            "absolute_conflict_tolerance"
        ] = "NaN"
        with self.assertRaises(ValueError):
            normalize_records(self.extracted, invalid)


if __name__ == "__main__":
    unittest.main()
