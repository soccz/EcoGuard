import unittest
from pathlib import Path

from ecoguard.legal import (
    LegalRetriever,
    evaluate,
    load_json,
    retrieve_issue_citations,
)
from ecoguard.preprocessing import normalize_records


ROOT = Path(__file__).resolve().parents[1]


class LegalRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_json(ROOT / "data/reference/legal_corpus.json")
        cls.cases = load_json(ROOT / "data/reference/legal_eval.json")

    def test_expected_citation_is_top_result_for_curated_cases(self):
        retriever = LegalRetriever(self.corpus)
        for case in self.cases:
            with self.subTest(query=case["query"]):
                top = retriever.search(case["query"], limit=1)[0]
                self.assertIn(top["id"], case["expected_ids"])
                self.assertTrue(top["url"].startswith("https://eur-lex.europa.eu/"))

    def test_evaluation_is_reproducible_and_scoped(self):
        result = evaluate(self.corpus, self.cases, k=3)
        self.assertEqual(result["hit_rate_at_k"], 1.0)
        self.assertEqual(result["mean_reciprocal_rank"], 1.0)
        self.assertIn("not legal advice", result["scope"])

    def test_unrelated_or_invalid_query_abstains_or_errors(self):
        retriever = LegalRetriever(self.corpus)
        unrelated = [
            "오늘 점심 메뉴와 축구 결과",
            "여행 일정과 숙박 비용을 계산해줘",
            "실제 경기 결과를 확인하는 방법",
            "개인정보를 제3자에게 제공",
            "공동인증서 갱신",
            "제품 원산지 표시",
            "소프트웨어 검증인",
            "산림 여행지 추천",
            "농장 체험 예약",
            "제3자 인증서 발급",
        ]
        for query in unrelated:
            with self.subTest(query=query):
                self.assertEqual(retriever.search(query), [])
        with self.assertRaises(ValueError):
            retriever.search("  ")
        with self.assertRaises(ValueError):
            retriever.search("검증", limit=0)

    def test_paraphrased_queries_still_retrieve_expected_articles(self):
        retriever = LegalRetriever(self.corpus)
        cases = [
            ("공인된 제3자의 확인 없이 실제 탄소 수치를 신고할 수 있나", "CBAM-ART8"),
            ("농장이 어디인지 위경도와 생산 시기를 제출해야 하나", "EUDR-ART9"),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(retriever.search(query, limit=1)[0]["id"], expected)

    def test_normalization_issues_are_linked_to_case_citations(self):
        raw = load_json(ROOT / "data/synthetic/ocr_records.json")
        linked = retrieve_issue_citations(
            normalize_records(raw),
            self.corpus,
            limit=3,
        )
        top_ids = {item["results"][0]["id"] for item in linked["items"]}
        self.assertEqual(
            top_ids,
            {"CBAM-ART6", "CBAM-ART7", "CBAM-ART8"},
        )
        self.assertEqual(linked["supported_issue_count"], 3)

    def test_corpus_pins_current_consolidated_sources(self):
        for entry in self.corpus:
            with self.subTest(entry=entry["id"]):
                self.assertEqual(entry["source_checked_on"], "2026-08-11")
                self.assertIn("/eli/reg/", entry["url"])
                self.assertIn("non-authoritative", entry["source_status"])


if __name__ == "__main__":
    unittest.main()
