"""Small, auditable article-level legal retriever and citation evaluation."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


# Character n-grams alone can make an unrelated sentence look similar to a
# legal summary. Require at least one explicit CBAM/EUDR cue before ranking.
STRONG_DOMAIN_ANCHORS = (
    "cbam",
    "eudr",
    "내재배출량",
    "실제 배출량",
    "배출계수",
    "탄소가격",
    "탄소 가격",
    "탄소배출",
    "탄소 배출",
    "실사 선언서",
    "위험 평가",
    "위험 완화",
    "산림 훼손",
    "embedded emissions",
    "carbon price",
    "geolocation",
    "deforestation",
    "due diligence",
)

WEAK_DOMAIN_ANCHORS = (
    "탄소",
    "배출",
    "인증서",
    "신고",
    "검증서",
    "검증인",
    "제3자",
    "제3국",
    "원산지",
    "생산지",
    "농장",
    "위경도",
    "좌표",
    "지리적 위치",
    "산림",
    "실사",
    "비준수",
    "certificate",
    "declaration",
    "verifier",
    "third country",
)


def _words(text: str) -> list[str]:
    return re.findall(r"[0-9a-zA-Z가-힣]+", text.lower())


def _features(text: str) -> Counter[str]:
    features: Counter[str] = Counter()
    for word in _words(text):
        features["w:" + word] += 3
        if len(word) >= 2:
            for size in (2, 3):
                for index in range(max(0, len(word) - size + 1)):
                    features["g:" + word[index : index + size]] += 1
    return features


def _entry_text(entry: dict[str, Any]) -> str:
    return " ".join(
        [
            entry["regulation"],
            entry["article"],
            entry.get("paragraph", ""),
            entry["title"],
            entry["summary_ko"],
            *entry.get("keywords", []),
        ]
    )


class LegalRetriever:
    """Lexical baseline whose scores and source URLs remain inspectable."""

    def __init__(self, corpus: Iterable[dict[str, Any]]):
        self.entries = list(corpus)
        self._vectors = [_features(_entry_text(entry)) for entry in self.entries]
        document_frequency: Counter[str] = Counter()
        for vector in self._vectors:
            document_frequency.update(vector.keys())
        total = len(self.entries)
        self._idf = {
            token: math.log((total + 1) / (frequency + 1)) + 1
            for token, frequency in document_frequency.items()
        }

    def search(
        self,
        query: str,
        limit: int = 3,
        *,
        min_score: float = 4.0,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if not query.strip():
            raise ValueError("query must not be blank")
        query_vector = _features(query)
        scored: list[tuple[float, dict[str, Any], list[str]]] = []
        lowered_query = query.lower()
        matched_strong = [
            anchor for anchor in STRONG_DOMAIN_ANCHORS if anchor in lowered_query
        ]
        matched_weak = [
            anchor for anchor in WEAK_DOMAIN_ANCHORS if anchor in lowered_query
        ]
        if not matched_strong and len(matched_weak) < 2:
            return []
        matched_domain_anchors = matched_strong + matched_weak
        for entry, vector in zip(self.entries, self._vectors, strict=True):
            score = 0.0
            matched: list[str] = []
            for token, count in query_vector.items():
                if token in vector:
                    score += min(count, vector[token]) * self._idf.get(token, 1.0)
            for keyword in entry.get("keywords", []):
                if keyword.lower() in lowered_query:
                    score += 12.0
                    matched.append(keyword)
            scored.append((score, entry, matched))

        scored.sort(key=lambda row: (-row[0], row[1]["id"]))
        supported = [
            row
            for row in scored
            if row[0] >= min_score
            and (matched_strong or len(row[2]) >= 2)
        ]
        return [
            {
                "rank": rank,
                "id": entry["id"],
                "score": round(score, 6),
                "regulation": entry["regulation"],
                "article": entry["article"],
                "paragraph": entry.get("paragraph"),
                "title": entry["title"],
                "summary_ko": entry["summary_ko"],
                "url": entry["url"],
                "celex": entry.get("celex"),
                "source_checked_on": entry.get("source_checked_on"),
                "source_status": entry.get("source_status"),
                "matched_keywords": matched,
                "matched_domain_anchors": matched_domain_anchors,
            }
            for rank, (score, entry, matched) in enumerate(
                supported[:limit],
                start=1,
            )
        ]


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def evaluate(
    corpus: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    *,
    k: int = 3,
) -> dict[str, Any]:
    retriever = LegalRetriever(corpus)
    rows: list[dict[str, Any]] = []
    hit_count = 0
    reciprocal_rank_total = 0.0
    for case in cases:
        results = retriever.search(case["query"], limit=k)
        ids = [result["id"] for result in results]
        expected = set(case["expected_ids"])
        matching_ranks = [
            index + 1 for index, identifier in enumerate(ids) if identifier in expected
        ]
        hit = bool(matching_ranks)
        hit_count += int(hit)
        if matching_ranks:
            reciprocal_rank_total += 1 / min(matching_ranks)
        rows.append(
            {
                "query": case["query"],
                "expected_ids": case["expected_ids"],
                "retrieved_ids": ids,
                "hit_at_k": hit,
                "results": results,
            }
        )

    count = len(cases)
    return {
        "evaluation": "article-level citation retrieval",
        "k": k,
        "case_count": count,
        "hit_rate_at_k": round(hit_count / count, 4) if count else 0.0,
        "mean_reciprocal_rank": (
            round(reciprocal_rank_total / count, 4) if count else 0.0
        ),
        "scope": "curated CBAM/EUDR article metadata; not legal advice",
        "cases": rows,
    }


ISSUE_QUERIES = {
    (
        "cross_document_conflict",
        "shipment_mass_t",
    ): "CBAM 신고 수량이 문서마다 다르면 신고 내용과 수량 근거는 어떤 조항을 확인해야 하나",
    (
        "cross_document_conflict",
        "actual_intensity_tco2e_per_t",
    ): "실제 내재배출량과 기본값 계산 근거가 충돌하면 어떤 조항을 확인해야 하나",
    (
        "missing_required_evidence",
        "verification_reference",
    ): "실제 배출량을 사용하려는데 검증서가 없으면 어떤 조항을 확인해야 하나",
}


def retrieve_issue_citations(
    normalized: dict[str, Any],
    corpus: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> dict[str, Any]:
    """Link known data-quality issues to ranked legal citations."""
    retriever = LegalRetriever(corpus)
    items: list[dict[str, Any]] = []
    for issue in normalized["issues"]:
        key = (issue["code"], issue.get("field"))
        query = ISSUE_QUERIES.get(key)
        if not query:
            continue
        results = retriever.search(query, limit=limit)
        items.append(
            {
                "issue": {
                    "code": issue["code"],
                    "field": issue.get("field"),
                    "message": issue["message"],
                },
                "query": query,
                "status": "supported" if results else "abstained",
                "results": results,
            }
        )
    return {
        "case_id": normalized["case_id"],
        "method": "rule-mapped issue query + article-level lexical retrieval",
        "linked_issue_count": len(items),
        "supported_issue_count": sum(
            item["status"] == "supported" for item in items
        ),
        "items": items,
        "scope": "decision support over a curated article metadata set; not legal advice",
    }
