import copy
import json
import unittest
from pathlib import Path

from ecoguard.ingestion import extract_document_bundle, extract_document_bundle_file


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/synthetic/trade_case_documents.json"


class DocumentIngestionTests(unittest.TestCase):
    def test_document_bundle_becomes_auditable_candidate_records(self):
        result = extract_document_bundle_file(BUNDLE)
        self.assertEqual(result["schema_version"], "2.0.0")
        self.assertEqual(result["summary"]["document_count"], 7)
        self.assertEqual(result["summary"]["line_count"], 37)
        self.assertEqual(result["summary"]["matched_line_count"], 30)
        self.assertEqual(result["summary"]["unmatched_line_count"], 7)
        self.assertEqual(result["summary"]["extraction_coverage"], 0.8108)

        mass = next(
            record
            for record in result["records"]
            if record["document"] == "commercial_invoice"
            and record["label"] == "총 출하 중량"
        )
        self.assertEqual(mass["value"], "190,000 kg")
        self.assertEqual(mass["record_id"], "ev-commercial-invoice-p01-l004")
        self.assertEqual(mass["page"], 1)
        self.assertEqual(mass["line"], 4)
        self.assertEqual(len(mass["line_sha256"]), 64)
        self.assertEqual(len(mass["document_sha256"]), 64)
        span = mass["source_span"]
        self.assertEqual(
            mass["raw_line"][span["value_start"] : span["value_end"]],
            mass["value"],
        )

    def test_longest_alias_wins_and_parse_ambiguity_is_not_hidden(self):
        result = extract_document_bundle_file(BUNDLE)
        actual_labels = [
            record["label"]
            for record in result["records"]
            if record["document"] == "cbam_product_sheet" and record["page"] == 2
        ]
        self.assertIn("실측 배출계수", actual_labels)
        self.assertNotIn("배출계수", actual_labels)

        ambiguous = next(
            record
            for record in result["records"]
            if record["document"] == "energy_memo" and record["line"] == 1
        )
        self.assertEqual(ambiguous["label"], "배출계수")
        self.assertIn("배분근거", ambiguous["value"])

    def test_input_order_does_not_change_extraction(self):
        payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
        reordered = copy.deepcopy(payload)
        reordered["documents"].reverse()
        for document in reordered["documents"]:
            document["pages"].reverse()
            for page in document["pages"]:
                page["lines"].reverse()
        self.assertEqual(
            extract_document_bundle(payload),
            extract_document_bundle(reordered),
        )

    def test_duplicate_documents_pages_and_lines_are_rejected(self):
        payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
        duplicate_document = copy.deepcopy(payload)
        duplicate_document["documents"].append(
            copy.deepcopy(duplicate_document["documents"][0])
        )
        with self.assertRaisesRegex(ValueError, "duplicate document_id"):
            extract_document_bundle(duplicate_document)

        duplicate_line = copy.deepcopy(payload)
        duplicate_line["documents"][0]["pages"][0]["lines"].append(
            copy.deepcopy(duplicate_line["documents"][0]["pages"][0]["lines"][0])
        )
        with self.assertRaisesRegex(ValueError, "duplicate line"):
            extract_document_bundle(duplicate_line)

    def test_boolean_confidence_is_not_silently_treated_as_one(self):
        payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
        payload["documents"][0]["pages"][0]["lines"][0]["confidence"] = True
        with self.assertRaisesRegex(ValueError, "invalid line confidence"):
            extract_document_bundle(payload)

    def test_boolean_page_and_line_coordinates_are_rejected(self):
        for coordinate in ("page", "line"):
            with self.subTest(coordinate=coordinate):
                payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
                target = payload["documents"][0]["pages"][0]
                if coordinate == "page":
                    target["page"] = True
                else:
                    target["lines"][0]["line"] = True
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    extract_document_bundle(payload)

    def test_negative_numeric_sign_is_preserved_in_raw_value(self):
        for sign in ("-", "–", "—"):
            with self.subTest(sign=sign):
                payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
                target = next(
                    line
                    for document in payload["documents"]
                    for page in document["pages"]
                    for line in page["lines"]
                    if line["text"] == "M5 순중량 : 90 MT"
                )
                target["text"] = f"M5 순중량 : {sign}1 MT"
                result = extract_document_bundle(payload)
                record = next(
                    item for item in result["records"] if item["label"] == "M5 순중량"
                )
                self.assertEqual(record["value"], f"{sign}1 MT")

    def test_document_bundle_schema_version_and_extra_keys_are_rejected(self):
        for mutation, message in (
            (("schema_version", "legacy/0.1"), "schema_version"),
            (("unexpected", "value"), "unsupported document bundle properties"),
        ):
            with self.subTest(key=mutation[0]):
                payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
                payload[mutation[0]] = mutation[1]
                with self.assertRaisesRegex(ValueError, message):
                    extract_document_bundle(payload)

    def test_multiple_field_aliases_on_one_line_are_quarantined(self):
        payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
        target = next(
            line
            for document in payload["documents"]
            for page in document["pages"]
            for line in page["lines"]
            if line["text"] == "M5 순중량 : 90 MT"
        )
        target["text"] = "M5 순중량 및 출하량 : 90 MT"
        result = extract_document_bundle(payload)
        quarantined = next(
            item for item in result["unmatched_lines"] if item["line"] == target["line"]
        )
        self.assertEqual(quarantined["reason"], "multiple configured field aliases")
        self.assertFalse(
            any(record["raw_line"] == target["text"] for record in result["records"])
        )

    def test_ascii_aliases_require_word_boundaries(self):
        for text in (
            "CABINET WT : 777 MT",
            "PLANET WT : 777 MT",
            "internet WT : 777 MT",
        ):
            with self.subTest(text=text):
                payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
                target = next(
                    line
                    for document in payload["documents"]
                    for page in document["pages"]
                    for line in page["lines"]
                    if line["text"] == "총 출하 중량 : 190,000 kg"
                )
                target["text"] = text
                result = extract_document_bundle(payload)
                self.assertFalse(
                    any(record["raw_line"] == text for record in result["records"])
                )

    def test_korean_aliases_require_leading_label_boundaries(self):
        for text in (
            "미출하량 : 190 MT",
            "비배출계수 : 5 tCO2e/t",
            "예상전기사용량 : 970000 kWh",
            "비원산지 탄소가격 : EUR 0 / tCO2e",
            "M5 순중량계 : 90 MT",
        ):
            with self.subTest(text=text):
                payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
                target = next(
                    line
                    for document in payload["documents"]
                    for page in document["pages"]
                    for line in page["lines"]
                    if line["text"] == "M5 순중량 : 90 MT"
                )
                target["text"] = text
                result = extract_document_bundle(payload)
                self.assertFalse(
                    any(record["raw_line"] == text for record in result["records"])
                )


if __name__ == "__main__":
    unittest.main()
