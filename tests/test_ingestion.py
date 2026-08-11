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


if __name__ == "__main__":
    unittest.main()
