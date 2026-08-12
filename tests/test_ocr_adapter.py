import copy
import json
import tempfile
import unittest
from pathlib import Path

from ecoguard.ingestion import extract_document_bundle
from ecoguard.ocr_adapter import (
    FIELD_BENCHMARK_SCHEMA_VERSION,
    SYNTHETIC_BENCHMARK_SCOPE,
    adapt_ocr_file,
    benchmark_document_bundle,
    benchmark_fields,
    generic_json_to_document_bundle,
    pdftotext_to_document_bundle,
    tesseract_tsv_to_document_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
TSV_FIXTURE = ROOT / "data/benchmarks/ocr/synthetic_tesseract.tsv"
REFERENCE_FIXTURE = ROOT / "data/benchmarks/ocr/synthetic_field_reference.json"


def _reference():
    return json.loads(REFERENCE_FIXTURE.read_text(encoding="utf-8"))


def _adapt_tsv():
    return adapt_ocr_file(
        TSV_FIXTURE,
        input_format="tesseract-tsv",
        case_id="ECO-OCR-SYN-001",
        document_id="synthetic_ocr_invoice",
        document_type="commercial_invoice",
        language="ko-en",
    )


class OcrAdapterTests(unittest.TestCase):
    def test_tesseract_words_become_stable_lines_with_mean_confidence(self):
        bundle = _adapt_tsv()
        document = bundle["documents"][0]
        self.assertEqual(bundle["schema_version"], "ocr-document-bundle/1.0")
        self.assertEqual(document["document_id"], "synthetic_ocr_invoice")
        self.assertEqual(len(document["pages"]), 1)
        lines = document["pages"][0]["lines"]
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[1]["text"], "NET WT : 190 MT")
        self.assertEqual(lines[1]["confidence"], 0.968)

        extraction = extract_document_bundle(bundle)
        self.assertEqual(extraction["summary"]["line_count"], 5)
        self.assertEqual(extraction["summary"]["matched_line_count"], 4)
        self.assertEqual(extraction["summary"]["unmatched_line_count"], 1)

    def test_synthetic_fixture_exercises_every_error_bucket(self):
        result = benchmark_document_bundle(
            _adapt_tsv(),
            _reference(),
            scope=SYNTHETIC_BENCHMARK_SCOPE,
        )
        evaluation = result["field_evaluation"]
        self.assertEqual(evaluation["schema_version"], FIELD_BENCHMARK_SCHEMA_VERSION)
        self.assertEqual(
            evaluation["counts"],
            {
                "expected_fields": 4,
                "predicted_fields": 4,
                "true_positive": 2,
                "false_positive": 2,
                "false_negative": 2,
            },
        )
        self.assertEqual(
            evaluation["metrics"],
            {"precision": 0.5, "recall": 0.5, "f1": 0.5},
        )
        self.assertEqual(
            evaluation["error_counts"],
            {"value_mismatch": 1, "missing": 1, "spurious": 1},
        )
        self.assertEqual(evaluation["errors"]["value_mismatch"][0]["label"], "CN code")
        self.assertEqual(
            evaluation["errors"]["missing"][0]["label"],
            "CBAM 인증서 가격",
        )
        self.assertEqual(evaluation["errors"]["spurious"][0]["label"], "LNG 사용량")
        self.assertEqual(
            evaluation["confidence_summary"],
            {
                "correct_mean": 0.9665,
                "incorrect_prediction_mean": 0.932,
                "missing_fields_have_no_confidence": True,
            },
        )
        self.assertTrue(result["scope"]["fixture_provenance_verified"])
        self.assertFalse(result["scope"]["ocr_engine_invoked_by_ecoguard"])
        self.assertFalse(result["scope"]["ocr_model_accuracy_claim"])

    def test_generic_json_accepts_nested_and_flat_contracts(self):
        nested = generic_json_to_document_bundle(
            {
                "pages": [
                    {
                        "page": 2,
                        "provider_metadata": "ignored",
                        "lines": [
                            {
                                "line": 7,
                                "text": "NET WT : 190 MT",
                                "confidence": 98,
                            },
                            {"text": "CN code : 7318.15.52"},
                        ],
                    }
                ]
            },
            case_id="generic-nested",
            document_id="document-a",
            document_type="commercial_invoice",
            confidence_scale="percent",
            default_confidence=0.25,
        )
        lines = nested["documents"][0]["pages"][0]["lines"]
        self.assertEqual([line["line"] for line in lines], [7, 8])
        self.assertEqual(lines[0]["confidence"], 0.98)
        self.assertEqual(lines[1]["confidence"], 0.25)

        flat = generic_json_to_document_bundle(
            [
                {"page": 2, "text": "CN code : 7318.15.52", "confidence": 0.8},
                {"page": 1, "text": "NET WT : 190 MT", "confidence": 0.9},
                {"page": 2, "text": "전기사용량 : 970000 kWh"},
            ],
            case_id="generic-flat",
            document_id="document-b",
            document_type="commercial_invoice",
        )
        pages = flat["documents"][0]["pages"]
        self.assertEqual([page["page"] for page in pages], [1, 2])
        self.assertEqual([line["line"] for line in pages[1]["lines"]], [1, 2])
        self.assertEqual(pages[1]["lines"][1]["confidence"], 0.0)

    def test_pdftotext_pages_skip_blanks_and_do_not_invent_confidence(self):
        bundle = pdftotext_to_document_bundle(
            "\n  NET WT : 190 MT\n\n\fCN code : 7318.15.52\n",
            case_id="plain-text",
            document_id="plain-document",
            document_type="commercial_invoice",
        )
        pages = bundle["documents"][0]["pages"]
        self.assertEqual([page["page"] for page in pages], [1, 2])
        self.assertEqual(pages[0]["lines"][0]["text"], "  NET WT : 190 MT")
        self.assertEqual(pages[0]["lines"][0]["confidence"], 0.0)
        self.assertEqual(
            extract_document_bundle(bundle)["summary"]["matched_line_count"], 2
        )

    def test_value_mismatch_counts_as_both_false_positive_and_false_negative(self):
        prediction = [
            {
                "document": "doc",
                "label": "NET WT",
                "value": "190  MT",
                "page": 1,
                "line": 1,
                "confidence": 0.9,
            },
            {
                "document": "doc",
                "label": "CN code",
                "value": "7318.15.5Z",
                "page": 1,
                "line": 2,
                "confidence": 0.4,
            },
        ]
        reference = {
            "schema_version": "ocr-field-reference/1.0",
            "case_id": "scoring",
            "notice": "Synthetic scoring fixture.",
            "fields": [
                {
                    "document": "doc",
                    "label": "NET WT",
                    "occurrence": 1,
                    "value": "190 MT",
                },
                {
                    "document": "doc",
                    "label": "CN code",
                    "occurrence": 1,
                    "value": "7318.15.52",
                },
            ],
        }
        result = benchmark_fields(prediction, reference)
        self.assertEqual(result["counts"]["true_positive"], 1)
        self.assertEqual(result["counts"]["false_positive"], 1)
        self.assertEqual(result["counts"]["false_negative"], 1)
        self.assertEqual(result["metrics"]["precision"], 0.5)
        self.assertEqual(result["metrics"]["recall"], 0.5)

    def test_malformed_inputs_and_ambiguous_coordinates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing columns"):
            tesseract_tsv_to_document_bundle(
                "level\ttext\n5\tNET\n",
                case_id="bad",
                document_id="bad",
                document_type="unknown",
            )

        duplicate_header = TSV_FIXTURE.read_text(encoding="utf-8").replace(
            "\ttext\n", "\ttext\ttext\n", 1
        )
        with self.assertRaisesRegex(ValueError, "duplicate column"):
            tesseract_tsv_to_document_bundle(
                duplicate_header,
                case_id="bad",
                document_id="bad",
                document_type="unknown",
            )

        invalid_confidence = TSV_FIXTURE.read_text(encoding="utf-8").replace(
            "\t96\tNET\n", "\t101\tNET\n", 1
        )
        with self.assertRaisesRegex(ValueError, r"within \[0, 100\]"):
            tesseract_tsv_to_document_bundle(
                invalid_confidence,
                case_id="bad",
                document_id="bad",
                document_type="unknown",
            )

        invalid_bbox = TSV_FIXTURE.read_text(encoding="utf-8").replace(
            "\t40\t40\t180\t30\t99\tSYNTHETIC", "\t-1\t40\t180\t30\t99\tSYNTHETIC", 1
        )
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            tesseract_tsv_to_document_bundle(
                invalid_bbox,
                case_id="bad",
                document_id="bad",
                document_type="unknown",
            )

        with self.assertRaisesRegex(ValueError, "duplicate line coordinate"):
            generic_json_to_document_bundle(
                {
                    "lines": [
                        {"page": 1, "line": 1, "text": "first"},
                        {"page": 1, "line": 1, "text": "second"},
                    ]
                },
                case_id="bad",
                document_id="bad",
                document_type="unknown",
            )

        with self.assertRaisesRegex(ValueError, "confidence_scale"):
            generic_json_to_document_bundle(
                {"lines": [{"text": "no measured confidence"}]},
                case_id="bad",
                document_id="bad",
                document_type="unknown",
                confidence_scale="guessed",
            )

        with self.assertRaisesRegex(ValueError, "must match its parent page"):
            generic_json_to_document_bundle(
                {"pages": [{"page": 1, "lines": [{"page": 2, "text": "x"}]}]},
                case_id="bad",
                document_id="bad",
                document_type="unknown",
            )

    def test_duplicate_reference_identity_and_case_mismatch_are_rejected(self):
        reference = _reference()
        duplicate = copy.deepcopy(reference)
        duplicate["fields"].append(copy.deepcopy(duplicate["fields"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate reference field identity"):
            benchmark_fields([], duplicate)

        wrong_case = copy.deepcopy(reference)
        wrong_case["case_id"] = "different"
        with self.assertRaisesRegex(ValueError, "case_id must match"):
            benchmark_document_bundle(_adapt_tsv(), wrong_case)

        for mutate in (
            lambda value: value.update(official_ground_truth=True),
            lambda value: value.update(notice={"official": True}),
            lambda value: value.update(fields=[]),
            lambda value: value["fields"][0].update(approved=True),
        ):
            with self.subTest(mutate=mutate):
                invalid = copy.deepcopy(reference)
                mutate(invalid)
                with self.assertRaises(ValueError):
                    benchmark_fields([], invalid)

        neutral = benchmark_document_bundle(_adapt_tsv(), reference)
        self.assertEqual(
            neutral["scope"]["classification"],
            "caller_supplied_reference_unverified",
        )
        self.assertFalse(neutral["scope"]["fixture_provenance_verified"])

    def test_file_adapter_rejects_unknown_format(self):
        with self.assertRaisesRegex(ValueError, "unsupported OCR input format"):
            adapt_ocr_file(
                TSV_FIXTURE,
                input_format="vendor-magic",
                case_id="bad",
                document_id="bad",
                document_type="unknown",
            )

    def test_generic_json_file_rejects_nonstandard_numeric_constants(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "bad.json"
            path.write_text(
                '{"lines":[{"text":"NET WT : 190 MT","confidence":NaN}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "non-finite JSON number"):
                adapt_ocr_file(
                    path,
                    input_format="generic-json",
                    case_id="bad",
                    document_id="bad",
                    document_type="unknown",
                )
            path.write_text(
                '{"lines":[{"text":"ORIGINAL","text":"SPOOF"}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                adapt_ocr_file(
                    path,
                    input_format="generic-json",
                    case_id="bad",
                    document_id="bad",
                    document_type="unknown",
                )

    def test_adapter_scalar_and_shape_contracts_fail_closed(self):
        common = {
            "case_id": "contract",
            "document_id": "document",
            "document_type": "unknown",
        }
        invalid_plain_text = (
            (None, {}, "pdftotext input"),
            ("", {}, "no adaptable lines"),
            ("one line", {"case_id": ""}, "non-blank string"),
            ("one line", {"fallback_confidence": True}, "within \\[0, 1\\]"),
            ("one line", {"fallback_confidence": "unknown"}, "within \\[0, 1\\]"),
            ("one line", {"fallback_confidence": 1.1}, "within \\[0, 1\\]"),
        )
        for text, overrides, message in invalid_plain_text:
            with self.subTest(text=text, overrides=overrides):
                arguments = {**common, **overrides}
                with self.assertRaisesRegex(ValueError, message):
                    pdftotext_to_document_bundle(text, **arguments)

        invalid_json = (
            (("not", "a", "list"), {}, "object or a list"),
            ({"pages": [], "lines": []}, {}, "either pages or lines"),
            ({"pages": "bad"}, {}, "pages must be a list"),
            ({"pages": ["bad"]}, {}, "page must be an object"),
            ({"pages": [{"page": 1}]}, {}, "page lines must be a list"),
            ({"pages": [{"lines": ["bad"]}]}, {}, "line must be an object"),
            ({}, {}, "lines or pages list"),
            ({"lines": ["bad"]}, {}, "line must be an object"),
            ({"lines": [{"page": False, "text": "x"}]}, {}, "positive integer"),
            ({"lines": [{"page": 0, "text": "x"}]}, {}, "positive integer"),
            ({"lines": [{"text": None}]}, {}, "text must be a string"),
            (
                {"lines": [{"text": "x", "confidence": True}]},
                {"confidence_scale": "percent"},
                "within \\[0, 100\\]",
            ),
            (
                {"lines": [{"text": "x", "confidence": "unknown"}]},
                {"confidence_scale": "percent"},
                "within \\[0, 100\\]",
            ),
        )
        for payload, overrides, message in invalid_json:
            with self.subTest(payload=payload, overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    generic_json_to_document_bundle(
                        payload,
                        **common,
                        **overrides,
                    )

    def test_tesseract_structure_errors_fail_before_ingestion(self):
        source = TSV_FIXTURE.read_text(encoding="utf-8")
        common = {
            "case_id": "contract",
            "document_id": "document",
            "document_type": "unknown",
        }
        with self.assertRaisesRegex(ValueError, "input must be a string"):
            tesseract_tsv_to_document_bundle(None, **common)

        invalid_level = source.replace("1\t1\t0\t0\t0\t0", "invalid\t1\t0\t0\t0\t0", 1)
        with self.assertRaisesRegex(ValueError, "invalid Tesseract level"):
            tesseract_tsv_to_document_bundle(invalid_level, **common)

        duplicate_word = source + ("5\t1\t1\t1\t1\t1\t40\t40\t180\t30\t99\tSYNTHETIC\n")
        with self.assertRaisesRegex(ValueError, "duplicate Tesseract word"):
            tesseract_tsv_to_document_bundle(duplicate_word, **common)

        header = source.splitlines()[0]
        blank_word_only = header + "\n5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t99\t\n"
        with self.assertRaisesRegex(ValueError, "no adaptable lines"):
            tesseract_tsv_to_document_bundle(blank_word_only, **common)

    def test_benchmark_contracts_and_empty_prediction_convention(self):
        reference = {
            "schema_version": "ocr-field-reference/1.0",
            "case_id": "empty",
            "notice": "Synthetic empty-prediction fixture.",
            "fields": [
                {
                    "document": "doc",
                    "label": "NET WT",
                    "occurrence": 1,
                    "value": "190 MT",
                }
            ],
        }
        empty = benchmark_fields([], reference)
        self.assertEqual(
            empty["metrics"], {"precision": None, "recall": 0.0, "f1": 0.0}
        )
        self.assertIsNone(empty["confidence_summary"]["correct_mean"])

        invalid_references = (
            ([], "field reference must be an object"),
            (
                {
                    "schema_version": "old",
                    "case_id": "x",
                    "notice": "test",
                    "fields": [],
                },
                "schema",
            ),
            (
                {
                    "schema_version": "ocr-field-reference/1.0",
                    "case_id": "x",
                    "notice": "test",
                    "fields": "bad",
                },
                "fields must be a non-empty list",
            ),
            (
                {
                    "schema_version": "ocr-field-reference/1.0",
                    "case_id": "x",
                    "notice": "test",
                    "fields": ["bad"],
                },
                "field must be an object",
            ),
            (
                {
                    "schema_version": "ocr-field-reference/1.0",
                    "case_id": "x",
                    "notice": "test",
                    "fields": [
                        {
                            "document": "doc",
                            "label": "NET WT",
                            "occurrence": 1,
                            "value": 190,
                        }
                    ],
                },
                "value must be a string",
            ),
        )
        for invalid, message in invalid_references:
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, message):
                    benchmark_fields([], invalid)

        with self.assertRaisesRegex(ValueError, "record must be an object"):
            benchmark_fields(["bad"], reference)
        invalid_prediction = {
            "document": "doc",
            "label": "NET WT",
            "value": 190,
            "page": 1,
            "line": 1,
            "confidence": 0.9,
        }
        with self.assertRaisesRegex(ValueError, "value must be a string"):
            benchmark_fields([invalid_prediction], reference)

        with self.assertRaisesRegex(ValueError, "document bundle must be an object"):
            benchmark_document_bundle([], reference)
        with self.assertRaisesRegex(ValueError, "field reference must be an object"):
            benchmark_document_bundle({}, [])


if __name__ == "__main__":
    unittest.main()
