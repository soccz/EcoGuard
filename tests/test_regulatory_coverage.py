import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ecoguard.regulatory import (
    evaluate_blind_fixture,
    load_json_document,
    main,
    validate_blind_fixture,
    validate_coverage_matrix,
)


ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "data/reference/cbam_rule_coverage.json"
BLIND = ROOT / "data/benchmarks/legal_blind.json"
CORPUS = ROOT / "data/reference/legal_corpus.json"
DEVELOPMENT = ROOT / "data/reference/legal_eval.json"


class RegulatoryCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coverage = load_json_document(COVERAGE)
        cls.blind = load_json_document(BLIND)
        cls.corpus = load_json_document(CORPUS)
        cls.development = load_json_document(DEVELOPMENT)

    def test_coverage_matrix_binds_official_eur_lex_sources_and_check_date(self):
        validation = validate_coverage_matrix(self.coverage)
        self.assertEqual(validation["as_of"], "2026-08-12")
        self.assertEqual(validation["source_count"], 7)
        expected_celex = {
            "02023R0956-20251020",
            "32025R2083",
            "32025R2546",
            "32025R2547",
            "32025R2548",
            "32025R2620",
            "32025R2621",
        }
        self.assertEqual(
            {source["celex"] for source in self.coverage["sources"]},
            expected_celex,
        )
        for source in self.coverage["sources"]:
            with self.subTest(source=source["source_id"]):
                self.assertEqual(source["authority"], "EUR-Lex")
                self.assertTrue(
                    source["eli"].startswith("https://eur-lex.europa.eu/eli/")
                )
                self.assertEqual(source["checked_on"], "2026-08-12")

    def test_no_selected_statutory_pathway_is_claimed_complete(self):
        validation = validate_coverage_matrix(self.coverage)
        self.assertEqual(validation["requirement_count"], 15)
        self.assertEqual(
            validation["status_counts"],
            {"implemented": 0, "not_implemented": 7, "partial": 8},
        )
        self.assertTrue(
            all(
                requirement["expert_review"]["required"]
                for requirement in self.coverage["requirements"]
            )
        )
        self.assertTrue(
            all(value is False for value in self.coverage["claims"].values())
        )

    def test_committed_code_and_test_references_resolve(self):
        code_refs = {
            reference
            for requirement in self.coverage["requirements"]
            for reference in requirement["implementation"]["code_refs"]
        }
        code_refs.update(
            reference
            for control in self.coverage[
                "technical_controls_outside_statutory_coverage"
            ]
            for reference in control["code_refs"]
        )
        for reference in code_refs:
            relative, symbol = reference.split(":", 1)
            path = ROOT / relative
            with self.subTest(reference=reference):
                self.assertTrue(path.is_file())
                module_name = "ecoguard." + path.stem
                module = __import__(module_name, fromlist=[symbol])
                self.assertTrue(hasattr(module, symbol))

        test_refs = {
            reference
            for requirement in self.coverage["requirements"]
            for reference in requirement["tests"]
        }
        for reference in test_refs:
            relative, class_name, method_name = reference.split("::", 2)
            path = ROOT / relative
            module_name = f"_coverage_ref_{path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with self.subTest(reference=reference):
                self.assertTrue(hasattr(getattr(module, class_name), method_name))

    def test_partial_rows_name_present_and_missing_inputs(self):
        partial = [
            requirement
            for requirement in self.coverage["requirements"]
            if requirement["implementation"]["status"] == "partial"
        ]
        self.assertEqual(len(partial), 8)
        for requirement in partial:
            with self.subTest(requirement=requirement["requirement_id"]):
                self.assertTrue(requirement["inputs"]["present"])
                self.assertTrue(requirement["inputs"]["missing"])
                self.assertTrue(requirement["implementation"]["implemented_behavior"])
                self.assertTrue(requirement["implementation"]["missing_behavior"])
                self.assertNotEqual(
                    requirement["formula"]["relationship"], "no_implementation"
                )

        inflated = copy.deepcopy(self.coverage)
        row = next(
            requirement
            for requirement in inflated["requirements"]
            if requirement["formula"]["relationship"] == "technical_control_only"
        )
        row["implementation"]["status"] = "implemented"
        row["implementation"]["missing_behavior"] = []
        row["inputs"]["missing"] = []
        inflated["summary"] = {
            "implemented": 1,
            "partial": 7,
            "not_implemented": 7,
            "interpretation": inflated["summary"]["interpretation"],
        }
        with self.assertRaisesRegex(ValueError, "incomplete boundary"):
            validate_coverage_matrix(inflated)

    def test_absent_obligations_are_machine_readable(self):
        by_id = {
            requirement["requirement_id"]: requirement
            for requirement in self.coverage["requirements"]
        }
        absent = {
            "CBAM-SCOPE-001",
            "CBAM-DEMINIMIS-002",
            "CBAM-VERIFICATION-010",
            "CBAM-CERTIFICATE-PRICE-012",
            "CBAM-FREE-ALLOCATION-013",
            "CBAM-CERTIFICATE-COUNT-014",
            "CBAM-SURRENDER-015",
        }
        self.assertEqual(
            {
                identifier
                for identifier, requirement in by_id.items()
                if requirement["implementation"]["status"] == "not_implemented"
            },
            absent,
        )
        for identifier in absent:
            with self.subTest(requirement=identifier):
                requirement = by_id[identifier]
                self.assertEqual(
                    requirement["formula"]["relationship"], "no_implementation"
                )
                self.assertTrue(requirement["implementation"]["missing_behavior"])
                self.assertTrue(requirement["inputs"]["missing"])

    def test_scenario_factor_is_not_mislabeled_as_free_allocation(self):
        free_allocation = next(
            requirement
            for requirement in self.coverage["requirements"]
            if requirement["requirement_id"] == "CBAM-FREE-ALLOCATION-013"
        )
        self.assertEqual(free_allocation["implementation"]["status"], "not_implemented")
        behavior = free_allocation["formula"]["ecoguard_behavior"]
        self.assertIn("not a free-allocation factor", behavior)
        self.assertNotIn("2025/2620", behavior)

    def test_blind_style_fixture_is_separate_and_explicitly_not_external(self):
        validation = validate_blind_fixture(
            self.blind,
            self.corpus,
            self.development,
        )
        self.assertFalse(validation["external_blind"])
        self.assertEqual(validation["case_count"], 36)
        self.assertEqual(
            validation["case_counts"],
            {"positive": 16, "distractor": 8, "negative": 12},
        )
        self.assertEqual(
            validation["development_fixture_sha256"],
            self.blind["binding"]["development_fixture_sha256"],
        )
        development_ids = {case["id"] for case in self.development}
        self.assertTrue(
            development_ids.isdisjoint(case["id"] for case in self.blind["cases"])
        )

    def test_blind_style_evaluation_is_deterministic_and_meets_frozen_thresholds(self):
        first = evaluate_blind_fixture(
            self.blind,
            self.corpus,
            self.development,
        )
        second = evaluate_blind_fixture(
            self.blind,
            self.corpus,
            self.development,
        )
        self.assertEqual(first, second)
        self.assertTrue(first["passed"])
        self.assertTrue(all(first["threshold_checks"].values()))
        self.assertEqual(
            first["metrics"],
            {
                "recall_at_k": 1.0,
                "mean_reciprocal_rank": 1.0,
                "positive_coverage": 1.0,
                "negative_abstention_rate": 1.0,
                "false_support_rate": 0.0,
                "distractor_rejection_at_1": 1.0,
                "instrument_leakage_at_k": 0.0,
                "trace_coverage": 1.0,
                "expected_status_match_rate": 1.0,
            },
        )

        mislabeled = copy.deepcopy(self.blind)
        mislabeled["cases"][0]["expected_status"] = "review"
        mislabeled_result = evaluate_blind_fixture(
            mislabeled,
            self.corpus,
            self.development,
        )
        self.assertFalse(mislabeled_result["passed"])
        self.assertFalse(
            mislabeled_result["threshold_checks"]["expected_status_match_rate"]
        )
        self.assertLess(mislabeled_result["metrics"]["expected_status_match_rate"], 1.0)

    def test_validators_reject_claim_inflation_and_holdout_leakage(self):
        complete_claim = copy.deepcopy(self.coverage)
        complete_claim["claims"]["complete_statutory_coverage"] = True

        invented_claim = copy.deepcopy(self.coverage)
        invented_claim["claims"]["officially_compliant"] = True

        top_level_claim = copy.deepcopy(self.coverage)
        top_level_claim["officially_compliant"] = True

        unofficial_source = copy.deepcopy(self.coverage)
        unofficial_source["sources"][0]["eli"] = "https://example.invalid/law"

        stale_count = copy.deepcopy(self.coverage)
        stale_count["summary"]["requirement_count"] = 999

        mismatched_celex = copy.deepcopy(self.coverage)
        mismatched_celex["sources"][0]["celex"] = "32025R9999"

        nonexistent_code = copy.deepcopy(self.coverage)
        nonexistent_code["requirements"][0]["implementation"]["code_refs"] = [
            "not-a-code-reference"
        ]

        inconsistent_implemented = copy.deepcopy(self.coverage)
        inconsistent_implemented["requirements"][0]["implementation"][
            "status"
        ] = "implemented"
        inconsistent_implemented["summary"]["status_counts"] = {
            "implemented": 1,
            "not_implemented": 7,
            "partial": 7,
        }

        inflated_source = copy.deepcopy(self.coverage)
        inflated_source["sources"][0]["officially_verified"] = True

        inflated_requirement = copy.deepcopy(self.coverage)
        inflated_requirement["requirements"][0]["legally_compliant"] = True

        inflated_scope = copy.deepcopy(self.coverage)
        inflated_scope["scope"]["official_assessment"] = True

        non_string_interpretation = copy.deepcopy(self.coverage)
        non_string_interpretation["summary"]["interpretation"] = {
            "officially_compliant": True
        }

        external_claim = copy.deepcopy(self.blind)
        external_claim["construction"]["external_blind"] = True

        top_level_external_claim = copy.deepcopy(self.blind)
        top_level_external_claim["external_blind"] = True

        nested_external_claim = copy.deepcopy(self.blind)
        nested_external_claim["construction"]["independent_external_validation"] = True

        inflated_verbatim_policy = copy.deepcopy(self.blind)
        inflated_verbatim_policy["construction"]["verbatim_policy"][
            "semantic_independence_verified"
        ] = True

        sealed_binding_claim = copy.deepcopy(self.blind)
        sealed_binding_claim["binding"]["officially_sealed"] = True

        boolean_k = copy.deepcopy(self.blind)
        boolean_k["k"] = True

        boolean_threshold = copy.deepcopy(self.blind)
        boolean_threshold["acceptance_thresholds"]["minimum_recall_at_k"] = True

        wrong_corpus = copy.deepcopy(self.blind)
        wrong_corpus["binding"]["corpus_sha256"] = "0" * 64

        wrong_development_binding = copy.deepcopy(self.blind)
        wrong_development_binding["binding"]["development_fixture_sha256"] = "0" * 64

        reused_query = copy.deepcopy(self.blind)
        reused_query["cases"][0]["query"] = self.development[0]["query"]

        duplicate_blind_query = copy.deepcopy(self.blind)
        duplicate_blind_query["cases"][1]["query"] = duplicate_blind_query["cases"][0][
            "query"
        ]

        copied_summary = copy.deepcopy(self.blind)
        copied_summary["cases"][0]["query"] = self.corpus[0]["summary_ko"]

        for matrix in (
            complete_claim,
            invented_claim,
            top_level_claim,
            unofficial_source,
            stale_count,
            mismatched_celex,
            nonexistent_code,
            inconsistent_implemented,
            inflated_source,
            inflated_requirement,
            inflated_scope,
            non_string_interpretation,
        ):
            with self.subTest(matrix=matrix):
                with self.assertRaises(ValueError):
                    validate_coverage_matrix(matrix)

        for fixture in (
            external_claim,
            top_level_external_claim,
            nested_external_claim,
            inflated_verbatim_policy,
            sealed_binding_claim,
            boolean_k,
            boolean_threshold,
            wrong_corpus,
            wrong_development_binding,
            reused_query,
            duplicate_blind_query,
            copied_summary,
        ):
            with self.subTest(fixture=fixture):
                with self.assertRaises(ValueError):
                    validate_blind_fixture(
                        fixture,
                        self.corpus,
                        self.development,
                    )

        with self.assertRaises(ValueError):
            validate_blind_fixture(self.blind, self.corpus, [])
        fake_development = copy.deepcopy(self.development)
        fake_development[0]["query"] += " 변조"
        with self.assertRaisesRegex(ValueError, "development fixture"):
            validate_blind_fixture(self.blind, self.corpus, fake_development)

    def test_dependency_free_verifier_cli_returns_machine_readable_summary(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main([])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["coverage"]["requirement_count"], 15)
        self.assertTrue(result["legal_blind_evaluation"]["passed"])

    def test_json_loader_rejects_nonstandard_numeric_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nonfinite.json"
            path.write_text('{"threshold": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite JSON"):
                load_json_document(path)
            path.write_text('{"claims": {}, "claims": {}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                load_json_document(path)


if __name__ == "__main__":
    unittest.main()
