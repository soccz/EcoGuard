import copy
import unittest
from pathlib import Path

from ecoguard.ingestion import extract_document_bundle_file
from ecoguard.legal import (
    CONCEPT_PHRASE_BONUS,
    LegalRetriever,
    evaluate,
    load_json,
    retrieve_issue_citations,
    validate_source_manifest,
)
from ecoguard.preprocessing import load_policy, normalize_records

ROOT = Path(__file__).resolve().parents[1]


class LegalRetrievalV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_json(ROOT / "data/reference/legal_corpus.json")
        cls.cases = load_json(ROOT / "data/reference/legal_eval.json")
        cls.source_manifest = load_json(ROOT / "data/reference/source_manifest.json")
        cls.retriever = LegalRetriever(cls.corpus)

    def test_corpus_is_bound_to_pinned_source_manifest(self):
        binding = validate_source_manifest(self.corpus, self.source_manifest)
        self.assertEqual(binding["status"], "verified")
        self.assertEqual(binding["corpus_entry_count"], 8)
        self.assertEqual(
            {
                source["celex"]: source["corpus_entry_count"]
                for source in binding["bound_sources"]
            },
            {
                "32023R0956": 4,
                "32023R1115": 4,
                "32025R2547": 0,
                "32025R2620": 0,
            },
        )
        self.assertEqual(
            {
                source["celex"]: source["binding_role"]
                for source in binding["bound_sources"]
            },
            {
                "32023R0956": "corpus_source",
                "32023R1115": "corpus_source",
                "32025R2547": "methodology_boundary",
                "32025R2620": "methodology_boundary",
            },
        )

        mutations = []
        wrong_celex = copy.deepcopy(self.source_manifest)
        wrong_celex["sources"][0]["celex"] = "32023R9999"
        mutations.append(wrong_celex)
        wrong_eli = copy.deepcopy(self.source_manifest)
        wrong_eli["sources"][0]["eli"] = "https://example.invalid/fake"
        mutations.append(wrong_eli)
        swapped_eli = copy.deepcopy(self.source_manifest)
        swapped_eli["sources"][0]["eli"], swapped_eli["sources"][3]["eli"] = (
            swapped_eli["sources"][3]["eli"],
            swapped_eli["sources"][0]["eli"],
        )
        mutations.append(swapped_eli)
        wrong_date = copy.deepcopy(self.source_manifest)
        wrong_date["source_checked_on"] = "1900-01-01"
        mutations.append(wrong_date)
        missing_boundary_source = copy.deepcopy(self.source_manifest)
        missing_boundary_source["sources"] = [
            source
            for source in missing_boundary_source["sources"]
            if source["celex"] != "32025R2547"
        ]
        mutations.append(missing_boundary_source)
        missing_scope = copy.deepcopy(self.source_manifest)
        del missing_scope["sources"][0]["scope_note"]
        mutations.append(missing_scope)
        missing_summary = copy.deepcopy(self.source_manifest)
        del missing_summary["summary_status"]
        mutations.append(missing_summary)
        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(ValueError):
                    validate_source_manifest(self.corpus, manifest)

    def test_corpus_keeps_eight_article_records_and_paragraph_metadata(self):
        expected = {
            "CBAM-ART6": "2",
            "CBAM-ART7": "1-7",
            "CBAM-ART8": "1",
            "CBAM-ART9": "1-5",
            "EUDR-ART4": "1-3",
            "EUDR-ART9": "1",
            "EUDR-ART10": "1-2",
            "EUDR-ART11": "1",
        }
        self.assertEqual(
            {entry["id"]: entry["paragraph"] for entry in self.corpus},
            expected,
        )
        for entry in self.corpus:
            with self.subTest(entry=entry["id"]):
                self.assertEqual(entry["source_checked_on"], "2026-08-11")
                self.assertTrue(
                    entry["url"].startswith("https://eur-lex.europa.eu/eli/reg/")
                )
                self.assertIn("non-authoritative", entry["source_status"])
                self.assertTrue(entry["concepts"])

    def test_corpus_instrument_cannot_be_bound_to_another_regulation(self):
        corpus = copy.deepcopy(self.corpus)
        corpus[0]["celex"] = "32023R1115"
        corpus[0]["url"] = "https://eur-lex.europa.eu/eli/reg/2023/1115/2025-12-26/eng"
        with self.assertRaisesRegex(ValueError, "instrument and CELEX"):
            validate_source_manifest(corpus, self.source_manifest)

        wrong_article = copy.deepcopy(self.corpus)
        wrong_article[0]["article"] = "Article 999"
        with self.assertRaisesRegex(ValueError, "id and article"):
            validate_source_manifest(wrong_article, self.source_manifest)

        wrong_label = copy.deepcopy(self.corpus)
        wrong_label[0]["regulation"] = "Totally different law"
        with self.assertRaisesRegex(ValueError, "regulation label"):
            validate_source_manifest(wrong_label, self.source_manifest)

    def test_eval_fixture_has_requested_case_classes(self):
        counts = {
            kind: sum(case["type"] == kind for case in self.cases)
            for kind in ("positive", "negative", "distractor")
        }
        self.assertEqual(
            counts,
            {"positive": 16, "negative": 10, "distractor": 8},
        )
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertIn("tags", case)
                self.assertIn("forbidden_ids", case)

    def test_positive_and_contrastive_cases_rank_expected_article_first(self):
        for case in self.cases:
            if case["type"] == "negative":
                continue
            with self.subTest(case=case["id"]):
                response = self.retriever.retrieve(case["query"], limit=3)
                self.assertEqual(response["decision"]["status"], "supported")
                self.assertIn(
                    response["results"][0]["id"],
                    case["expected_ids"],
                )
                self.assertNotIn(
                    response["results"][0]["id"],
                    case["forbidden_ids"],
                )
                self.assertEqual(
                    response["decision"]["instrument"],
                    case["expected_instrument"],
                )

    def test_hard_negatives_abstain_with_structured_reason(self):
        allowed_reasons = {
            "out_of_domain",
            "underspecified",
            "ambiguous_instrument",
            "low_score",
        }
        for case in self.cases:
            if case["type"] != "negative":
                continue
            with self.subTest(case=case["id"]):
                response = self.retriever.retrieve(case["query"])
                self.assertEqual(response["decision"]["status"], "abstained")
                self.assertIn(
                    response["decision"]["reason_code"],
                    allowed_reasons,
                )
                self.assertEqual(response["results"], [])
                self.assertEqual(self.retriever.search(case["query"]), [])

    def test_explicit_instrument_filter_prevents_cross_regulation_results(self):
        cases = [
            (
                "CBAM 실제 배출량에 공인 검증인의 검증서가 없다",
                "CBAM-",
            ),
            (
                "EUDR 생산지 좌표와 생산 기간 정보가 누락됐다",
                "EUDR-",
            ),
        ]
        for query, prefix in cases:
            with self.subTest(query=query):
                response = self.retriever.retrieve(query, limit=8)
                self.assertTrue(response["results"])
                self.assertTrue(
                    all(
                        result["id"].startswith(prefix)
                        for result in response["results"]
                    )
                )

    def test_exact_article_reference_routes_only_with_instrument(self):
        supported = self.retriever.retrieve("EUDR Article 9")
        self.assertEqual(supported["decision"]["status"], "supported")
        self.assertEqual(supported["results"][0]["id"], "EUDR-ART9")

        ambiguous = self.retriever.retrieve("Article 9")
        self.assertEqual(ambiguous["decision"]["status"], "abstained")
        self.assertEqual(
            ambiguous["decision"]["reason_code"],
            "ambiguous_instrument",
        )

    def test_unknown_explicit_article_abstains_instead_of_substituting(self):
        for query in ("CBAM Article 99", "EUDR Article 99"):
            with self.subTest(query=query):
                response = self.retriever.retrieve(query)
                self.assertEqual(response["decision"]["status"], "abstained")
                self.assertEqual(
                    response["decision"]["reason_code"], "article_not_in_corpus"
                )
                self.assertEqual(response["results"], [])
                self.assertEqual(
                    response["query_trace"]["unavailable_article_references"],
                    ["99"],
                )

    def test_ascii_instrument_alias_requires_token_boundaries(self):
        response = self.retriever.retrieve(
            "noncbam 신고 수량 근거가 필요하다",
            min_score=0,
        )
        self.assertEqual(response["query_trace"]["explicit_instruments"], {})
        self.assertNotEqual(
            response["query_trace"]["instrument_source"],
            "explicit",
        )

    def test_search_remains_a_list_compatibility_wrapper(self):
        query = "CBAM 신고서에서 물품 수량과 인증서 수량이 빠졌다"
        detailed = self.retriever.retrieve(query, limit=2)
        compact = self.retriever.search(query, limit=2)
        self.assertIsInstance(compact, list)
        self.assertEqual(compact, detailed["results"])

    def test_low_score_and_low_margin_are_explicit_decisions(self):
        query = "CBAM 내재배출량과 기본값 계산 근거가 필요하다"
        low_score = self.retriever.retrieve(query, min_score=1_000_000)
        self.assertEqual(low_score["decision"]["status"], "abstained")
        self.assertEqual(low_score["decision"]["reason_code"], "low_score")

        review = self.retriever.retrieve(
            query,
            min_score=0,
            min_margin=1_000_000,
        )
        self.assertEqual(review["decision"]["status"], "review")
        self.assertEqual(
            review["decision"]["reason_code"],
            "low_ranking_margin",
        )
        self.assertTrue(review["results"])

    def test_citation_and_score_trace_are_complete_and_add_up(self):
        response = self.retriever.retrieve(
            "CBAM 실제 배출량에 공인 검증인의 검증서가 없다",
            limit=1,
        )
        result = response["results"][0]
        citation = result["citation"]
        self.assertEqual(citation["id"], "CBAM-ART8")
        self.assertEqual(len(citation["corpus_entry_sha256"]), 64)
        self.assertEqual(len(response["retriever"]["corpus_sha256"]), 64)
        self.assertEqual(len(response["query_trace"]["query_sha256"]), 64)
        self.assertTrue(citation["url"].startswith("https://eur-lex.europa.eu/"))

        trace = result["score_trace"]
        component_sum = (
            trace["bm25_word"]
            + trace["bm25_character_ngram"]
            + trace["concept_phrase_bonus"]
            + trace["article_match_bonus"]
        )
        self.assertAlmostEqual(component_sum, trace["total_score"], places=5)
        self.assertAlmostEqual(result["score"], trace["total_score"], places=6)
        concepts = {row["concept"] for row in trace["matched_concepts"]}
        self.assertEqual(
            trace["concept_phrase_bonus"],
            CONCEPT_PHRASE_BONUS * len(concepts),
        )
        self.assertTrue(trace["field_scores"])
        self.assertTrue(trace["matched_terms"])

    def test_corpus_order_and_unicode_formatting_do_not_change_ranking(self):
        reversed_retriever = LegalRetriever(list(reversed(self.corpus)))
        self.assertEqual(
            reversed_retriever.corpus_hash,
            self.retriever.corpus_hash,
        )
        query = "EUDR Article 9"
        normal = self.retriever.search(query)
        reversed_results = reversed_retriever.search(query)
        self.assertEqual(
            [(row["id"], row["score"]) for row in normal],
            [(row["id"], row["score"]) for row in reversed_results],
        )
        full_width = self.retriever.search("ＥＵＤＲ　Ａｒｔｉｃｌｅ　９")
        self.assertEqual(full_width[0]["id"], normal[0]["id"])

    def test_invalid_corpus_and_query_configuration_are_rejected(self):
        duplicate = copy.deepcopy(self.corpus)
        duplicate.append(copy.deepcopy(self.corpus[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            LegalRetriever(duplicate)

        invalid_url = copy.deepcopy(self.corpus)
        invalid_url[0]["url"] = "https://example.com/not-eurlex"
        with self.assertRaisesRegex(ValueError, "EUR-Lex"):
            LegalRetriever(invalid_url)

        for mutate in (
            lambda entry: entry.update(official_translation=True),
            lambda entry: entry.update(title={"official": True}),
            lambda entry: entry["keywords"].append(entry["keywords"][0]),
            lambda entry: entry["concepts"][next(iter(entry["concepts"]))].append(
                entry["concepts"][next(iter(entry["concepts"]))][0]
            ),
        ):
            with self.subTest(mutate=mutate):
                invalid = copy.deepcopy(self.corpus)
                mutate(invalid[0])
                with self.assertRaises(ValueError):
                    LegalRetriever(invalid)

        with self.assertRaisesRegex(ValueError, "blank"):
            self.retriever.retrieve("  ")
        with self.assertRaisesRegex(ValueError, "limit"):
            self.retriever.retrieve("CBAM", limit=0)
        with self.assertRaisesRegex(ValueError, "limit"):
            self.retriever.retrieve("CBAM", limit=True)
        for invalid in (True, "2", None, float("nan"), float("inf"), -1):
            with self.subTest(min_score=invalid):
                with self.assertRaisesRegex(ValueError, "min_score"):
                    self.retriever.retrieve("CBAM", min_score=invalid)
        for invalid in (False, "0.35", None, float("nan"), float("inf"), -1):
            with self.subTest(min_margin=invalid):
                with self.assertRaisesRegex(ValueError, "min_margin"):
                    self.retriever.retrieve("CBAM", min_margin=invalid)

    def test_evaluation_reports_retrieval_and_selective_metrics(self):
        with self.assertRaisesRegex(ValueError, "k"):
            evaluate(self.corpus, self.cases, k=True)
        first = evaluate(self.corpus, self.cases, k=3)
        second = evaluate(self.corpus, self.cases, k=3)
        self.assertEqual(first, second)
        expected_metrics = {
            "hit_rate_at_k": 1.0,
            "recall_at_k": 1.0,
            "mean_reciprocal_rank": 1.0,
            "positive_coverage": 1.0,
            "negative_abstention_rate": 1.0,
            "false_support_rate": 0.0,
            "distractor_rejection_at_1": 1.0,
            "instrument_leakage_at_k": 0.0,
            "trace_coverage": 1.0,
        }
        for name, expected in expected_metrics.items():
            with self.subTest(metric=name):
                self.assertEqual(first[name], expected)
        self.assertEqual(first["case_count"], 34)
        self.assertEqual(first["positive_case_count"], 16)
        self.assertEqual(first["distractor_case_count"], 8)
        self.assertEqual(first["negative_case_count"], 10)
        self.assertEqual(first["retrieval_case_count"], 24)
        self.assertIn("not an LLM", first["scope"])
        self.assertIn("not legal advice", first["scope"])

        at_one = evaluate(self.corpus, self.cases, k=1)
        multi = next(
            row for row in at_one["cases"] if row["id"] == "positive-eudr-art10-02"
        )
        self.assertTrue(multi["hit_at_k"])
        self.assertEqual(multi["recall_at_k"], 0.5)
        self.assertEqual(multi["reciprocal_rank"], 1.0)

    def test_evaluation_rejects_duplicate_unknown_and_self_contradictory_labels(self):
        invalid_cases = []

        duplicate = copy.deepcopy(self.cases)
        duplicate[1]["id"] = duplicate[0]["id"]
        invalid_cases.append((duplicate, "duplicate"))

        unknown = copy.deepcopy(self.cases)
        unknown[0]["expected_ids"] = ["CBAM-ART999"]
        invalid_cases.append((unknown, "outside the corpus"))

        overlapping = copy.deepcopy(self.cases)
        overlapping[0]["forbidden_ids"] = overlapping[0]["expected_ids"][:]
        invalid_cases.append((overlapping, "overlap"))

        inflated_claim = copy.deepcopy(self.cases)
        inflated_claim[0]["externally_adjudicated"] = True
        invalid_cases.append((inflated_claim, "unsupported keys"))

        negative_with_target = copy.deepcopy(self.cases)
        negative = next(
            case for case in negative_with_target if case["type"] == "negative"
        )
        negative["expected_ids"] = ["EUDR-ART4"]
        invalid_cases.append((negative_with_target, "must not expect"))

        for cases, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    evaluate(self.corpus, cases)

    def test_normalization_issues_keep_supported_and_unmapped_boundaries(self):
        raw = extract_document_bundle_file(
            ROOT / "data/synthetic/trade_case_documents.json"
        )
        normalized = normalize_records(
            raw,
            load_policy(ROOT / "data/reference/normalization_policy.json"),
        )
        linked = retrieve_issue_citations(
            normalized,
            self.corpus,
            limit=3,
        )
        top_ids = {
            item["results"][0]["id"] for item in linked["items"] if item["results"]
        }
        self.assertEqual(top_ids, {"CBAM-ART6", "CBAM-ART8"})
        self.assertEqual(linked["supported_issue_count"], 2)
        self.assertGreater(linked["unmapped_issue_count"], 0)
        self.assertEqual(
            linked["linked_issue_count"] + linked["unmapped_issue_count"],
            len(normalized["issues"]),
        )
        self.assertIn("not an LLM", linked["scope"])

        synthetic_issue = {
            "case_id": "LEGAL-UNIT",
            "issues": [
                {
                    "code": "cross_document_conflict",
                    "field": "actual_intensity_tco2e_per_t",
                    "message": "conflict",
                }
            ],
        }
        mapped = retrieve_issue_citations(synthetic_issue, self.corpus)
        self.assertEqual(mapped["items"][0]["results"][0]["id"], "CBAM-ART7")


if __name__ == "__main__":
    unittest.main()
