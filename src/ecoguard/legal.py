"""Auditable article-level legal citation retrieval and evaluation.

This module is a deterministic lexical retrieval baseline.  It does not call
an LLM, generate legal advice, or claim paragraph-level legal correctness.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable


RETRIEVER_VERSION = "legal-bm25f-v2.1"
PINNED_SOURCE_ELI = {
    "32023R0956": "https://eur-lex.europa.eu/eli/reg/2023/956/2025-10-20/eng",
    "32023R1115": "https://eur-lex.europa.eu/eli/reg/2023/1115/2025-12-26/eng",
    "32025R2547": "https://eur-lex.europa.eu/eli/reg_impl/2025/2547/oj/eng",
    "32025R2620": "https://eur-lex.europa.eu/eli/reg_impl/2025/2620/oj/eng",
}
PINNED_SOURCE_CELEX = set(PINNED_SOURCE_ELI)
CORPUS_SOURCE_CELEX = {
    "CBAM": "32023R0956",
    "EUDR": "32023R1115",
}
CORPUS_REGULATION_LABEL = {
    "CBAM": "Regulation (EU) 2023/956",
    "EUDR": "Regulation (EU) 2023/1115",
}
BM25_K1 = 1.2
NGRAM_WEIGHT = 0.18
DEFAULT_MIN_SCORE = 2.0
DEFAULT_MIN_MARGIN = 0.35
ARTICLE_MATCH_BONUS = 12.0
CONCEPT_PHRASE_BONUS = 4.0

FIELD_WEIGHTS = {
    "regulation": 5.0,
    "article": 8.0,
    "title": 4.0,
    "keywords": 3.0,
    "concepts": 4.0,
    "summary_ko": 1.0,
}

FIELD_LENGTH_NORMALIZATION = {
    "regulation": 0.0,
    "article": 0.0,
    "title": 0.2,
    "keywords": 0.2,
    "concepts": 0.2,
    "summary_ko": 0.75,
}

INSTRUMENT_ALIASES = {
    "CBAM": (
        "cbam",
        "탄소국경조정제도",
        "regulation eu 2023 956",
        "regulation 2023 956",
        "2023 956",
        "32023r0956",
    ),
    "EUDR": (
        "eudr",
        "산림전용방지규정",
        "산림 전용 방지 규정",
        "eu 산림 규정",
        "regulation eu 2023 1115",
        "regulation 2023 1115",
        "2023 1115",
        "32023r1115",
    ),
}

# These cues identify a legal/compliance question.  Generic words such as
# "방법" and "기준" are intentionally excluded because they caused hard
# negatives about maps, sensors and model performance to look in-domain.
LEGAL_INTENT_CUES = (
    "어떤 조항",
    "몇 조",
    "몇조",
    "의무",
    "제출",
    "누락",
    "빠졌",
    "빠졌다",
    "없으면",
    "없다",
    "없이",
    "신고",
    "증빙",
    "공제",
    "차감",
    "감축",
    "줄일 수",
    "검증",
    "확인 없이",
    "근거",
    "산정",
    "계산",
    "해야",
    "필요",
    "할 수 있",
    "인정",
    "비준수",
    "적합",
    "위반",
    "완화",
    "before placing",
    "must",
    "required",
    "evidence",
    "comply",
)

ARTICLE_REFERENCE = re.compile(
    r"(?:article|art\.?)\s*(\d+[a-z]?)|제\s*(\d+[a-z]?)\s*조",
    re.IGNORECASE,
)

REQUIRED_ENTRY_FIELDS = {
    "id",
    "instrument",
    "celex",
    "source_checked_on",
    "source_status",
    "regulation",
    "article",
    "paragraph",
    "title",
    "summary_ko",
    "keywords",
    "concepts",
    "url",
}


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    normalized = re.sub(r"[^0-9a-z가-힣]+", " ", normalized)
    return " ".join(normalized.split())


def _words(text: str) -> list[str]:
    return re.findall(r"[0-9a-z가-힣]+", _normalize_text(text))


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    """Match ASCII aliases on token boundaries while retaining Korean compounds."""
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    if re.fullmatch(r"[0-9a-z ]+", normalized_phrase):
        return bool(
            re.search(
                rf"(?<![0-9a-z]){re.escape(normalized_phrase)}(?![0-9a-z])",
                normalized_text,
            )
        )
    return normalized_phrase in normalized_text


def _ngrams(text: str) -> list[str]:
    grams: list[str] = []
    for word in _words(text):
        for size in (2, 3):
            if len(word) < size:
                continue
            grams.extend(
                word[index : index + size] for index in range(len(word) - size + 1)
            )
    return grams


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _article_number(value: str) -> str | None:
    match = re.search(r"\b(\d+[a-z]?)\b", value.casefold())
    return match.group(1) if match else None


def _concept_aliases(entry: dict[str, Any]) -> list[str]:
    return [
        alias for aliases in entry.get("concepts", {}).values() for alias in aliases
    ]


def _entry_fields(entry: dict[str, Any]) -> dict[str, str]:
    article_number = _article_number(entry["article"]) or ""
    return {
        "regulation": " ".join(
            [entry["instrument"], entry["regulation"], entry["celex"]]
        ),
        "article": " ".join(
            [
                entry["article"],
                entry["paragraph"],
                f"제{article_number}조" if article_number else "",
                f"{article_number}조" if article_number else "",
            ]
        ),
        "title": entry["title"],
        "keywords": " ".join(entry.get("keywords", [])),
        "concepts": " ".join(
            [*entry.get("concepts", {}).keys(), *_concept_aliases(entry)]
        ),
        "summary_ko": entry["summary_ko"],
    }


def _validate_concepts(identifier: str, concepts: Any) -> None:
    if not isinstance(concepts, dict) or not concepts:
        raise ValueError(f"concepts must be a non-empty object: {identifier}")
    for concept, aliases in concepts.items():
        if not concept or not isinstance(aliases, list) or not aliases:
            raise ValueError(f"invalid concept aliases: {identifier}: {concept}")
        if any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ValueError(f"blank concept alias: {identifier}: {concept}")


def _validate_corpus_entry(entry: dict[str, Any]) -> str:
    missing = sorted(REQUIRED_ENTRY_FIELDS - entry.keys())
    if missing:
        raise ValueError(
            f"legal corpus entry is missing fields: {entry.get('id', '?')}: "
            + ", ".join(missing)
        )
    identifier = entry["id"]
    instrument = entry["instrument"]
    if instrument not in INSTRUMENT_ALIASES:
        raise ValueError(f"unsupported legal instrument: {instrument}")
    identifier_match = re.fullmatch(rf"{instrument}-ART([0-9]+)", identifier)
    if identifier_match is None:
        raise ValueError(f"entry id and instrument disagree: {identifier}")
    if entry["celex"] != CORPUS_SOURCE_CELEX[instrument]:
        raise ValueError(f"entry instrument and CELEX disagree: {identifier}")
    if entry["regulation"] != CORPUS_REGULATION_LABEL[instrument]:
        raise ValueError(f"entry regulation label disagrees: {identifier}")
    if entry["article"] != f"Article {identifier_match.group(1)}":
        raise ValueError(f"entry id and article disagree: {identifier}")
    if not entry["url"].startswith("https://eur-lex.europa.eu/eli/reg/"):
        raise ValueError(f"legal source must be an EUR-Lex ELI URL: {identifier}")
    if "non-authoritative" not in entry["source_status"]:
        raise ValueError(f"team summary must be marked non-authoritative: {identifier}")
    if not isinstance(entry["keywords"], list) or not entry["keywords"]:
        raise ValueError(f"keywords must be a non-empty list: {identifier}")
    _validate_concepts(identifier, entry["concepts"])
    return identifier


def _validate_corpus(entries: list[dict[str, Any]]) -> None:
    if not entries:
        raise ValueError("legal corpus must not be empty")
    identifiers: set[str] = set()
    for entry in entries:
        identifier = _validate_corpus_entry(entry)
        if identifier in identifiers:
            raise ValueError(f"duplicate legal corpus id: {identifier}")
        identifiers.add(identifier)


def _valid_iso_date(value: Any, field: str) -> str:
    try:
        date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"legal source manifest has invalid {field}") from exc
    return str(value)


def _source_role_keys(celex: str) -> set[str]:
    if celex.startswith("32023"):
        return {"consolidated_as_of", "amending_acts"}
    return {"adopted_on", "official_journal_published_on"}


def _validate_source_metadata(source: dict[str, Any], celex: str) -> None:
    common_keys = {"name", "celex", "eli", "scope_note"}
    if set(source) != common_keys | _source_role_keys(celex):
        raise ValueError(f"legal source metadata is incomplete: {celex}")
    for text_field in ("name", "scope_note"):
        value = source[text_field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"legal source has invalid {text_field}: {celex}")
    if "amending_acts" in source:
        acts = source["amending_acts"]
        if (
            not isinstance(acts, list)
            or not acts
            or any(not isinstance(act, str) or not act.strip() for act in acts)
        ):
            raise ValueError(f"legal source has invalid amending_acts: {celex}")
    for date_field in (
        "consolidated_as_of",
        "adopted_on",
        "official_journal_published_on",
    ):
        if date_field in source:
            _valid_iso_date(source[date_field], f"{date_field}: {celex}")


def _legal_source_index(
    manifest: dict[str, Any]
) -> tuple[str, dict[str, dict[str, Any]]]:
    if not isinstance(manifest, dict):
        raise ValueError("legal source manifest must be an object")
    required_manifest_keys = {"source_checked_on", "sources", "summary_status"}
    if set(manifest) != required_manifest_keys:
        raise ValueError("legal source manifest has missing or unsupported properties")
    summary_status = manifest["summary_status"]
    if not isinstance(summary_status, str) or "non-authoritative" not in summary_status:
        raise ValueError("legal source manifest summary must be non-authoritative")
    checked_on = _valid_iso_date(manifest.get("source_checked_on"), "source_checked_on")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("legal source manifest must contain sources")
    by_celex: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("legal source manifest entries must be objects")
        celex = source.get("celex")
        eli = source.get("eli")
        if not re.fullmatch(r"3[0-9]{4}[A-Z][0-9]{4}", str(celex)):
            raise ValueError(f"legal source manifest has invalid CELEX: {celex}")
        if celex in by_celex:
            raise ValueError(f"duplicate legal source CELEX: {celex}")
        if not isinstance(eli, str) or eli != PINNED_SOURCE_ELI.get(str(celex)):
            raise ValueError(f"legal source manifest has invalid ELI: {celex}")
        _validate_source_metadata(source, str(celex))
        by_celex[str(celex)] = source
    return checked_on, by_celex


def validate_source_manifest(
    entries: list[dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, Any]:
    """Bind every corpus record to the pinned official-source metadata."""
    _validate_corpus(entries)
    checked_on, by_celex = _legal_source_index(manifest)
    source_ids = set(by_celex)
    if source_ids != PINNED_SOURCE_CELEX:
        missing = sorted(PINNED_SOURCE_CELEX - source_ids)
        unexpected = sorted(source_ids - PINNED_SOURCE_CELEX)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(
            "legal source manifest boundary disagrees: " + "; ".join(details)
        )

    counts: Counter[str] = Counter()
    for entry in entries:
        identifier = entry["id"]
        source = by_celex.get(entry["celex"])
        if source is None:
            raise ValueError(
                f"legal corpus CELEX is absent from manifest: {identifier}"
            )
        if entry["url"] != source["eli"]:
            raise ValueError(f"legal corpus ELI disagrees with manifest: {identifier}")
        if entry["source_checked_on"] != checked_on:
            raise ValueError(
                f"legal corpus source date disagrees with manifest: {identifier}"
            )
        counts[entry["celex"]] += 1

    return {
        "status": "verified",
        "source_checked_on": checked_on,
        "corpus_entry_count": len(entries),
        "bound_sources": [
            {
                "celex": celex,
                "eli": by_celex[celex]["eli"],
                "corpus_entry_count": counts.get(celex, 0),
                "binding_role": (
                    "corpus_source" if counts.get(celex, 0) else "methodology_boundary"
                ),
            }
            for celex in sorted(by_celex)
        ],
    }


def _document_frequency(
    vectors: list[dict[str, Counter[str]]],
) -> dict[str, int]:
    frequency: Counter[str] = Counter()
    for vector in vectors:
        present = {term for field_vector in vector.values() for term in field_vector}
        frequency.update(present)
    return dict(frequency)


def _idf(total: int, frequency: dict[str, int]) -> dict[str, float]:
    return {
        term: math.log(1 + (total - count + 0.5) / (count + 0.5))
        for term, count in frequency.items()
    }


def _average_lengths(
    vectors: list[dict[str, Counter[str]]],
) -> dict[str, float]:
    return {
        field: (sum(sum(vector[field].values()) for vector in vectors) / len(vectors))
        for field in FIELD_WEIGHTS
    }


def _instrument_from_id(identifier: str) -> str | None:
    prefix = identifier.split("-", 1)[0]
    return prefix if prefix in INSTRUMENT_ALIASES else None


class LegalRetriever:
    """Dependency-free BM25F citation retriever with explicit abstention."""

    def __init__(self, corpus: Iterable[dict[str, Any]]):
        incoming = [dict(entry) for entry in corpus]
        _validate_corpus(incoming)
        self.entries = sorted(incoming, key=lambda entry: entry["id"])
        self.corpus_hash = _sha256(self.entries)
        self.entry_hashes = {entry["id"]: _sha256(entry) for entry in self.entries}
        self._fields = [_entry_fields(entry) for entry in self.entries]
        self._word_vectors = [
            {field: Counter(_words(text)) for field, text in fields.items()}
            for fields in self._fields
        ]
        self._ngram_vectors = [
            {field: Counter(_ngrams(text)) for field, text in fields.items()}
            for fields in self._fields
        ]
        total = len(self.entries)
        self._word_idf = _idf(total, _document_frequency(self._word_vectors))
        self._ngram_idf = _idf(total, _document_frequency(self._ngram_vectors))
        self._word_average_lengths = _average_lengths(self._word_vectors)
        self._ngram_average_lengths = _average_lengths(self._ngram_vectors)

    @property
    def config(self) -> dict[str, Any]:
        return {
            "version": RETRIEVER_VERSION,
            "bm25_k1": BM25_K1,
            "ngram_weight": NGRAM_WEIGHT,
            "field_weights": dict(FIELD_WEIGHTS),
            "field_length_normalization": dict(FIELD_LENGTH_NORMALIZATION),
            "article_match_bonus": ARTICLE_MATCH_BONUS,
            "concept_phrase_bonus": CONCEPT_PHRASE_BONUS,
        }

    def _analyze_query(self, query: str) -> dict[str, Any]:
        normalized = _normalize_text(query)
        explicit_instruments: dict[str, list[str]] = {}
        for instrument, aliases in INSTRUMENT_ALIASES.items():
            matches = [
                alias for alias in aliases if _contains_phrase(normalized, alias)
            ]
            if matches:
                explicit_instruments[instrument] = sorted(set(matches))

        intent_matches = sorted(
            {cue for cue in LEGAL_INTENT_CUES if _contains_phrase(normalized, cue)}
        )
        concept_hits: list[dict[str, str]] = []
        concepts_by_instrument: dict[str, set[str]] = defaultdict(set)
        for entry in self.entries:
            for concept, aliases in entry["concepts"].items():
                matches = sorted(
                    {alias for alias in aliases if _contains_phrase(normalized, alias)}
                )
                if not matches:
                    continue
                concepts_by_instrument[entry["instrument"]].add(concept)
                concept_hits.append(
                    {
                        "entry_id": entry["id"],
                        "instrument": entry["instrument"],
                        "concept": concept,
                        "matched_phrase": matches[0],
                    }
                )

        article_references = sorted(
            {latin or korean for latin, korean in ARTICLE_REFERENCE.findall(normalized)}
        )
        instrument: str | None = None
        instrument_source: str | None = None
        gate_passed = False
        reason_code = "out_of_domain"

        if len(explicit_instruments) > 1:
            reason_code = "ambiguous_instrument"
        elif explicit_instruments:
            instrument = next(iter(explicit_instruments))
            instrument_source = "explicit"
            relevant_concepts = concepts_by_instrument.get(instrument, set())
            if article_references or (
                relevant_concepts and (intent_matches or len(relevant_concepts) >= 2)
            ):
                gate_passed = True
                reason_code = "domain_supported"
            else:
                reason_code = "underspecified"
        elif article_references:
            reason_code = "ambiguous_instrument"
        elif not intent_matches:
            reason_code = "out_of_domain"
        else:
            ranked_instruments = sorted(
                (
                    (len(concepts), name)
                    for name, concepts in concepts_by_instrument.items()
                ),
                reverse=True,
            )
            if ranked_instruments and ranked_instruments[0][0] >= 2:
                best_count, best_instrument = ranked_instruments[0]
                tied = [
                    name for count, name in ranked_instruments if count == best_count
                ]
                if len(tied) == 1:
                    instrument = best_instrument
                    instrument_source = "inferred_from_concepts"
                    gate_passed = True
                    reason_code = "domain_supported"
                else:
                    reason_code = "ambiguous_instrument"

        matched_domain_anchors = sorted(
            {
                *(
                    alias
                    for matches in explicit_instruments.values()
                    for alias in matches
                ),
                *intent_matches,
                *(hit["matched_phrase"] for hit in concept_hits),
            }
        )
        return {
            "raw": query,
            "normalized": normalized,
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "tokens": _words(query),
            "instrument": instrument,
            "instrument_source": instrument_source,
            "explicit_instruments": explicit_instruments,
            "article_references": article_references,
            "legal_intent_cues": intent_matches,
            "concept_hits": concept_hits,
            "concept_counts": {
                name: len(concepts)
                for name, concepts in sorted(concepts_by_instrument.items())
            },
            "matched_domain_anchors": matched_domain_anchors,
            "gate_passed": gate_passed,
            "reason_code": reason_code,
        }

    def _bm25_channel(
        self,
        query_counts: Counter[str],
        document: dict[str, Counter[str]],
        *,
        idf: dict[str, float],
        average_lengths: dict[str, float],
        channel: str,
        channel_weight: float,
    ) -> tuple[float, dict[str, float], list[dict[str, Any]]]:
        total_score = 0.0
        field_scores = {field: 0.0 for field in FIELD_WEIGHTS}
        term_trace: list[dict[str, Any]] = []
        for term, query_frequency in query_counts.items():
            if term not in idf:
                continue
            field_tf: dict[str, float] = {}
            for field, weight in FIELD_WEIGHTS.items():
                term_frequency = document[field].get(term, 0)
                if not term_frequency:
                    continue
                length = sum(document[field].values())
                average = average_lengths[field] or 1.0
                b = FIELD_LENGTH_NORMALIZATION[field]
                normalized_tf = term_frequency / (1 - b + b * length / average)
                field_tf[field] = weight * normalized_tf
            weighted_tf = sum(field_tf.values())
            if not weighted_tf:
                continue
            query_factor = 1.0 + 0.1 * (min(query_frequency, 2) - 1)
            score = (
                idf[term]
                * ((BM25_K1 + 1) * weighted_tf)
                / (BM25_K1 + weighted_tf)
                * query_factor
                * channel_weight
            )
            total_score += score
            contributions: dict[str, float] = {}
            for field, value in field_tf.items():
                contribution = score * value / weighted_tf
                field_scores[field] += contribution
                contributions[field] = round(contribution, 6)
            term_trace.append(
                {
                    "channel": channel,
                    "term": term,
                    "score": round(score, 6),
                    "fields": contributions,
                }
            )
        term_trace.sort(key=lambda row: (-row["score"], row["term"]))
        return (
            total_score,
            {field: round(score, 6) for field, score in field_scores.items()},
            term_trace,
        )

    def _score_entry(
        self,
        query_trace: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        entry = self.entries[index]
        word_score, word_fields, word_terms = self._bm25_channel(
            Counter(_words(query_trace["normalized"])),
            self._word_vectors[index],
            idf=self._word_idf,
            average_lengths=self._word_average_lengths,
            channel="word",
            channel_weight=1.0,
        )
        ngram_score, ngram_fields, ngram_terms = self._bm25_channel(
            Counter(_ngrams(query_trace["normalized"])),
            self._ngram_vectors[index],
            idf=self._ngram_idf,
            average_lengths=self._ngram_average_lengths,
            channel="character_ngram",
            channel_weight=NGRAM_WEIGHT,
        )

        matched_concepts: list[dict[str, str]] = []
        normalized_query = query_trace["normalized"]
        for concept, aliases in entry["concepts"].items():
            matches = sorted(
                {
                    alias
                    for alias in aliases
                    if _contains_phrase(normalized_query, alias)
                }
            )
            if matches:
                matched_concepts.append({"concept": concept, "phrase": matches[0]})
        phrase_bonus = CONCEPT_PHRASE_BONUS * len(matched_concepts)
        entry_article = _article_number(entry["article"])
        article_bonus = (
            ARTICLE_MATCH_BONUS
            if entry_article in query_trace["article_references"]
            else 0.0
        )
        total = word_score + ngram_score + phrase_bonus + article_bonus
        matched_keywords = [
            keyword
            for keyword in entry.get("keywords", [])
            if _contains_phrase(normalized_query, keyword)
        ]
        field_scores = {
            field: round(word_fields[field] + ngram_fields[field], 6)
            for field in FIELD_WEIGHTS
        }
        matched_terms = sorted(
            word_terms + ngram_terms,
            key=lambda row: (-row["score"], row["channel"], row["term"]),
        )
        return {
            "entry": entry,
            "score": total,
            "matched_keywords": matched_keywords,
            "score_trace": {
                "bm25_word": round(word_score, 6),
                "bm25_character_ngram": round(ngram_score, 6),
                "concept_phrase_bonus": round(phrase_bonus, 6),
                "article_match_bonus": round(article_bonus, 6),
                "field_scores": field_scores,
                "matched_concepts": matched_concepts,
                "matched_terms": matched_terms,
                "total_score": round(total, 6),
            },
        }

    def _public_result(
        self,
        row: dict[str, Any],
        *,
        rank: int,
        query_trace: dict[str, Any],
    ) -> dict[str, Any]:
        entry = row["entry"]
        citation = {
            "id": entry["id"],
            "instrument": entry["instrument"],
            "regulation": entry["regulation"],
            "celex": entry["celex"],
            "article": entry["article"],
            "paragraph": entry["paragraph"],
            "url": entry["url"],
            "source_checked_on": entry["source_checked_on"],
            "source_status": entry["source_status"],
            "corpus_entry_sha256": self.entry_hashes[entry["id"]],
        }
        return {
            "rank": rank,
            "id": entry["id"],
            "score": round(row["score"], 6),
            "regulation": entry["regulation"],
            "article": entry["article"],
            "paragraph": entry["paragraph"],
            "title": entry["title"],
            "summary_ko": entry["summary_ko"],
            "team_summary_ko": entry["summary_ko"],
            "url": entry["url"],
            "celex": entry["celex"],
            "source_checked_on": entry["source_checked_on"],
            "source_status": entry["source_status"],
            "matched_keywords": row["matched_keywords"],
            "matched_domain_anchors": query_trace["matched_domain_anchors"],
            "citation": citation,
            "score_trace": row["score_trace"],
        }

    def retrieve(
        self,
        query: str,
        limit: int = 3,
        *,
        min_score: float = DEFAULT_MIN_SCORE,
        min_margin: float = DEFAULT_MIN_MARGIN,
    ) -> dict[str, Any]:
        """Return ranked citations plus an explicit support/abstention trace."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if not query.strip():
            raise ValueError("query must not be blank")
        if not math.isfinite(min_score) or min_score < 0:
            raise ValueError("min_score must be a non-negative finite number")
        if not math.isfinite(min_margin) or min_margin < 0:
            raise ValueError("min_margin must be a non-negative finite number")

        query_trace = self._analyze_query(query)
        base = {
            "retriever": {
                **self.config,
                "corpus_sha256": self.corpus_hash,
                "corpus_entry_count": len(self.entries),
            },
            "query_trace": query_trace,
        }
        if not query_trace["gate_passed"]:
            return {
                **base,
                "decision": {
                    "status": "abstained",
                    "reason_code": query_trace["reason_code"],
                    "instrument": query_trace["instrument"],
                    "instrument_source": query_trace["instrument_source"],
                    "min_score": min_score,
                    "min_margin": min_margin,
                    "top_score": None,
                    "ranking_margin": None,
                },
                "results": [],
            }

        instrument = query_trace["instrument"]
        requested_articles = set(query_trace["article_references"])
        available_articles = {
            article
            for entry in self.entries
            if entry["instrument"] == instrument
            if (article := _article_number(entry["article"])) is not None
        }
        unavailable_articles = sorted(requested_articles - available_articles)
        if unavailable_articles:
            query_trace["available_article_references"] = sorted(available_articles)
            query_trace["unavailable_article_references"] = unavailable_articles
            return {
                **base,
                "decision": {
                    "status": "abstained",
                    "reason_code": "article_not_in_corpus",
                    "instrument": instrument,
                    "instrument_source": query_trace["instrument_source"],
                    "min_score": min_score,
                    "min_margin": min_margin,
                    "top_score": None,
                    "ranking_margin": None,
                },
                "results": [],
            }

        scored = [
            self._score_entry(query_trace, index)
            for index, entry in enumerate(self.entries)
            if entry["instrument"] == instrument
        ]
        scored.sort(key=lambda row: (-row["score"], row["entry"]["id"]))
        top_score = scored[0]["score"] if scored else 0.0
        second_score = scored[1]["score"] if len(scored) > 1 else 0.0
        margin = top_score - second_score
        eligible = [row for row in scored if row["score"] >= min_score]
        if not eligible:
            return {
                **base,
                "decision": {
                    "status": "abstained",
                    "reason_code": "low_score",
                    "instrument": instrument,
                    "instrument_source": query_trace["instrument_source"],
                    "min_score": min_score,
                    "min_margin": min_margin,
                    "top_score": round(top_score, 6),
                    "ranking_margin": round(margin, 6),
                },
                "results": [],
            }

        has_exact_article = bool(query_trace["article_references"])
        status = (
            "review"
            if len(eligible) > 1 and margin < min_margin and not has_exact_article
            else "supported"
        )
        reason_code = (
            "low_ranking_margin" if status == "review" else "citation_supported"
        )
        results = [
            self._public_result(row, rank=rank, query_trace=query_trace)
            for rank, row in enumerate(eligible[:limit], start=1)
        ]
        return {
            **base,
            "decision": {
                "status": status,
                "reason_code": reason_code,
                "instrument": instrument,
                "instrument_source": query_trace["instrument_source"],
                "min_score": min_score,
                "min_margin": min_margin,
                "top_score": round(top_score, 6),
                "ranking_margin": round(margin, 6),
            },
            "results": results,
        }

    def search(
        self,
        query: str,
        limit: int = 3,
        *,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> list[dict[str, Any]]:
        """Compatibility wrapper returning only supported/review citations."""
        return self.retrieve(
            query,
            limit=limit,
            min_score=min_score,
        )["results"]


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def _rate(numerator: int | float, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _trace_complete(result: dict[str, Any]) -> bool:
    citation = result.get("citation", {})
    score_trace = result.get("score_trace", {})
    return all(
        citation.get(key)
        for key in (
            "id",
            "regulation",
            "celex",
            "article",
            "paragraph",
            "url",
            "source_checked_on",
            "source_status",
            "corpus_entry_sha256",
        )
    ) and all(
        key in score_trace
        for key in (
            "bm25_word",
            "bm25_character_ngram",
            "concept_phrase_bonus",
            "article_match_bonus",
            "field_scores",
            "total_score",
        )
    )


def _validated_case_ids(
    case: dict[str, Any],
    field: str,
    identifier: str,
    known_ids: set[str],
) -> list[str]:
    identifiers = case.get(field, [])
    if not isinstance(identifiers, list) or any(
        not isinstance(value, str) or not value for value in identifiers
    ):
        raise ValueError(f"{field} must be a list of ids: {identifier}")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{field} contains duplicates: {identifier}")
    unknown = sorted(set(identifiers) - known_ids)
    if unknown:
        raise ValueError(
            f"{field} contains ids outside the corpus: {identifier}: "
            + ", ".join(unknown)
        )
    return identifiers


def _validate_negative_case(
    case: dict[str, Any], identifier: str, expected_ids: list[str]
) -> None:
    if expected_ids:
        raise ValueError(f"negative case must not expect citations: {identifier}")
    if case.get("expected_status") != "abstained":
        raise ValueError(f"negative case must expect abstention: {identifier}")


def _validate_retrieval_case(
    case: dict[str, Any], identifier: str, expected_ids: list[str]
) -> None:
    if not expected_ids:
        raise ValueError(f"retrieval case has no expected ids: {identifier}")
    expected_instrument = case.get("expected_instrument")
    if expected_instrument not in INSTRUMENT_ALIASES:
        raise ValueError(f"retrieval case has invalid instrument: {identifier}")
    if any(_instrument_from_id(value) != expected_instrument for value in expected_ids):
        raise ValueError(f"expected ids and instrument disagree: {identifier}")
    if case.get("expected_status") not in {"supported", "review"}:
        raise ValueError(f"retrieval case has invalid expected status: {identifier}")


def _validate_evaluation_case(
    case: Any,
    index: int,
    known_ids: set[str],
    seen_ids: set[str],
) -> None:
    if not isinstance(case, dict):
        raise ValueError(f"legal evaluation case {index} must be an object")
    identifier = case.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError(f"legal evaluation case {index} has a blank id")
    if identifier in seen_ids:
        raise ValueError(f"duplicate legal evaluation case id: {identifier}")
    seen_ids.add(identifier)
    query = case.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"legal evaluation case has a blank query: {identifier}")
    case_type = case.get("type")
    if case_type not in {"positive", "negative", "distractor"}:
        raise ValueError(f"unsupported legal evaluation case type: {case_type}")

    expected_ids = _validated_case_ids(case, "expected_ids", identifier, known_ids)
    forbidden_ids = _validated_case_ids(case, "forbidden_ids", identifier, known_ids)
    if set(expected_ids) & set(forbidden_ids):
        raise ValueError(f"expected and forbidden ids overlap: {identifier}")
    if case_type == "negative":
        _validate_negative_case(case, identifier, expected_ids)
    else:
        _validate_retrieval_case(case, identifier, expected_ids)


def _validate_evaluation_cases(
    cases: list[dict[str, Any]], retriever: LegalRetriever
) -> None:
    if not isinstance(cases, list) or not cases:
        raise ValueError("legal evaluation cases must be a non-empty list")
    known_ids = {entry["id"] for entry in retriever.entries}
    seen_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        _validate_evaluation_case(case, index, known_ids, seen_ids)


def evaluate(
    corpus: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    *,
    k: int = 3,
) -> dict[str, Any]:
    """Evaluate positive, negative and contrastive citation cases."""
    if k < 1:
        raise ValueError("k must be at least 1")
    retriever = LegalRetriever(corpus)
    _validate_evaluation_cases(cases, retriever)
    rows: list[dict[str, Any]] = []
    positive_count = 0
    retrieval_case_count = 0
    negative_count = 0
    distractor_count = 0
    hit_count = 0
    recall_total = 0.0
    reciprocal_rank_total = 0.0
    positive_covered = 0
    negative_abstained = 0
    false_support = 0
    distractor_rejected = 0
    instrument_case_count = 0
    instrument_leakage_count = 0
    traced_results = 0
    result_count = 0

    for case in cases:
        case_type = case["type"]
        expected = set(case.get("expected_ids", []))
        forbidden = set(case.get("forbidden_ids", []))
        response = retriever.retrieve(case["query"], limit=k)
        results = response["results"]
        ids = [result["id"] for result in results]
        status = response["decision"]["status"]
        result_count += len(results)
        traced_results += sum(_trace_complete(result) for result in results)

        recall: float | None = None
        reciprocal_rank: float | None = None
        hit: bool | None = None
        if case_type in {"positive", "distractor"}:
            retrieval_case_count += 1
            if case_type == "positive":
                positive_count += 1
            else:
                distractor_count += 1
            matching_ranks = [
                index + 1
                for index, identifier in enumerate(ids)
                if identifier in expected
            ]
            hit = bool(matching_ranks)
            recall = len(expected.intersection(ids)) / len(expected)
            reciprocal_rank = 1 / min(matching_ranks) if matching_ranks else 0.0
            hit_count += int(hit)
            recall_total += recall
            reciprocal_rank_total += reciprocal_rank
            if case_type == "positive":
                positive_covered += int(status != "abstained")
            else:
                distractor_rejected += int(not ids or ids[0] not in forbidden)
        else:
            negative_count += 1
            abstained = status == "abstained"
            negative_abstained += int(abstained)
            false_support += int(not abstained)

        expected_instrument = case.get("expected_instrument")
        if expected_instrument:
            instrument_case_count += 1
            if any(
                _instrument_from_id(identifier) != expected_instrument
                for identifier in ids
            ):
                instrument_leakage_count += 1

        rows.append(
            {
                "id": case["id"],
                "type": case_type,
                "tags": case.get("tags", []),
                "query": case["query"],
                "expected_status": case.get("expected_status"),
                "actual_status": status,
                "reason_code": response["decision"]["reason_code"],
                "expected_ids": case.get("expected_ids", []),
                "forbidden_ids": case.get("forbidden_ids", []),
                "retrieved_ids": ids,
                "hit_at_k": hit,
                "recall_at_k": round(recall, 4) if recall is not None else None,
                "reciprocal_rank": (
                    round(reciprocal_rank, 4) if reciprocal_rank is not None else None
                ),
                "decision": response["decision"],
                "query_trace": response["query_trace"],
                "results": results,
            }
        )

    return {
        "evaluation": "article-level deterministic citation retrieval",
        "retriever_version": RETRIEVER_VERSION,
        "corpus_sha256": retriever.corpus_hash,
        "k": k,
        "case_count": len(cases),
        "positive_case_count": positive_count,
        "retrieval_case_count": retrieval_case_count,
        "negative_case_count": negative_count,
        "distractor_case_count": distractor_count,
        # Compatibility name retained for prior report consumers.
        "hit_rate_at_k": _rate(hit_count, retrieval_case_count),
        "recall_at_k": _rate(recall_total, retrieval_case_count),
        "mean_reciprocal_rank": _rate(
            reciprocal_rank_total,
            retrieval_case_count,
        ),
        "positive_coverage": _rate(positive_covered, positive_count),
        "negative_abstention_rate": _rate(
            negative_abstained,
            negative_count,
        ),
        "false_support_rate": _rate(false_support, negative_count),
        "distractor_rejection_at_1": _rate(
            distractor_rejected,
            distractor_count,
        ),
        "instrument_leakage_at_k": _rate(
            instrument_leakage_count,
            instrument_case_count,
        ),
        "trace_coverage": _rate(traced_results, result_count),
        "counts": {
            "positive_covered": positive_covered,
            "negative_abstained": negative_abstained,
            "false_support": false_support,
            "distractor_rejected": distractor_rejected,
            "instrument_leakage": instrument_leakage_count,
            "traced_results": traced_results,
            "retrieved_results": result_count,
        },
        "scope": (
            "curated CBAM/EUDR article metadata; deterministic retrieval "
            "baseline; not an LLM and not legal advice"
        ),
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
    """Link known data-quality issues to auditable citation candidates."""
    retriever = LegalRetriever(corpus)
    items: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for issue in normalized["issues"]:
        key = (issue["code"], issue.get("field"))
        query = ISSUE_QUERIES.get(key)
        if not query:
            unmapped.append(
                {
                    "code": issue["code"],
                    "field": issue.get("field"),
                    "message": issue["message"],
                }
            )
            continue
        response = retriever.retrieve(query, limit=limit)
        items.append(
            {
                "issue": {
                    "code": issue["code"],
                    "field": issue.get("field"),
                    "message": issue["message"],
                },
                "query": query,
                "status": response["decision"]["status"],
                "reason_code": response["decision"]["reason_code"],
                "query_trace": response["query_trace"],
                "results": response["results"],
            }
        )
    return {
        "case_id": normalized["case_id"],
        "method": (
            "rule-mapped issue query + field-weighted BM25F article citation retrieval"
        ),
        "retriever_version": RETRIEVER_VERSION,
        "corpus_sha256": retriever.corpus_hash,
        "linked_issue_count": len(items),
        "supported_issue_count": sum(item["status"] == "supported" for item in items),
        "review_issue_count": sum(item["status"] == "review" for item in items),
        "abstained_issue_count": sum(item["status"] == "abstained" for item in items),
        "unmapped_issue_count": len(unmapped),
        "unmapped_issues": unmapped,
        "items": items,
        "scope": (
            "decision support over curated article metadata; not an LLM "
            "and not legal advice"
        ),
    }
