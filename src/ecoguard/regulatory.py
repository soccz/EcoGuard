"""Validate the CBAM coverage map and the legal holdout benchmark.

This module checks repository evidence, not legal compliance.  It deliberately
uses only the Python standard library and EcoGuard's deterministic retriever.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .legal import LegalRetriever, evaluate
from .jsonio import strict_json_file


COVERAGE_SCHEMA_VERSION = "cbam-rule-coverage/1.0"
BLIND_SCHEMA_VERSION = "legal-blind-eval/1.0"
ALLOWED_COVERAGE_STATUSES = {"implemented", "partial", "not_implemented"}
ALLOWED_RELATIONSHIPS = {
    "aligned_subset",
    "arithmetic_analogy_only",
    "no_implementation",
    "technical_control_only",
}
CELEX_PATTERN = re.compile(r"^(?:0|3)[0-9]{4}[A-Z][0-9]{4}(?:-[0-9]{8})?$")
EXPECTED_COVERAGE_SOURCES = {
    "cbam-consolidated-2025-10-20": {
        "base_celex": "32023R0956",
        "celex": "02023R0956-20251020",
        "eli": "https://eur-lex.europa.eu/eli/reg/2023/956/2025-10-20/eng",
        "source_kind": "consolidated_documentation_text",
    },
    "cbam-amendment-2025-2083": {
        "celex": "32025R2083",
        "eli": "https://eur-lex.europa.eu/eli/reg/2025/2083/oj/eng",
        "source_kind": "official_journal_legal_act",
    },
    "cbam-methods-2025-2547": {
        "celex": "32025R2547",
        "eli": "https://eur-lex.europa.eu/eli/reg_impl/2025/2547/oj/eng",
        "source_kind": "official_journal_legal_act",
    },
    "cbam-verification-2025-2546": {
        "celex": "32025R2546",
        "eli": "https://eur-lex.europa.eu/eli/reg_impl/2025/2546/oj/eng",
        "source_kind": "official_journal_legal_act",
    },
    "cbam-price-2025-2548": {
        "celex": "32025R2548",
        "eli": "https://eur-lex.europa.eu/eli/reg_impl/2025/2548/oj/eng",
        "source_kind": "official_journal_legal_act",
    },
    "cbam-free-allocation-2025-2620": {
        "celex": "32025R2620",
        "eli": "https://eur-lex.europa.eu/eli/reg_impl/2025/2620/oj/eng",
        "source_kind": "official_journal_legal_act",
    },
    "cbam-default-values-2025-2621": {
        "celex": "32025R2621",
        "eli": "https://eur-lex.europa.eu/eli/reg_impl/2025/2621/oj/eng",
        "source_kind": "official_journal_legal_act",
    },
}
EXPECTED_FALSE_CLAIMS = {
    "complete_statutory_coverage",
    "legal_advice",
    "statutory_calculator",
    "payable_amount",
}
CODE_REFERENCE_PATTERN = re.compile(r"^src/ecoguard/[a-z0-9_]+\.py:[A-Za-z0-9_]+$")
TEST_REFERENCE_PATTERN = re.compile(
    r"^tests/test_[a-z0-9_]+\.py::[A-Za-z0-9_]+::test_[a-z0-9_]+$"
)


def load_json_document(path: str | Path) -> Any:
    """Load a UTF-8 JSON document."""
    return strict_json_file(path)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _iso_date(value: Any, label: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {label}") from exc


def _nonblank_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"blank or non-string value: {label}")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    required: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    if not required <= set(value) or set(value) - allowed:
        raise ValueError(f"{label} must use the supported keys")


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"expected a non-empty list: {label}")
    for index, item in enumerate(value):
        _nonblank_string(item, f"{label}[{index}]")
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate list value: {label}")
    return value


def _validate_coverage_source(source: Any, checked_on: str) -> str:
    if not isinstance(source, dict):
        raise ValueError("coverage source must be an object")
    source_keys = {
        "source_id",
        "title",
        "celex",
        "eli",
        "authority",
        "source_kind",
        "version_note",
        "checked_on",
    }
    _require_exact_keys(
        source,
        source_keys,
        "coverage source",
        optional={"base_celex"},
    )
    identifier = _nonblank_string(source.get("source_id"), "source.source_id")
    expected = EXPECTED_COVERAGE_SOURCES.get(identifier)
    if expected is None:
        raise ValueError(f"coverage source is not pinned: {identifier}")
    celex = _nonblank_string(source.get("celex"), f"{identifier}.celex")
    if CELEX_PATTERN.fullmatch(celex) is None:
        raise ValueError(f"invalid CELEX identifier: {identifier}")
    eli = _nonblank_string(source.get("eli"), f"{identifier}.eli")
    if not eli.startswith("https://eur-lex.europa.eu/eli/"):
        raise ValueError(f"source is not an official EUR-Lex ELI URL: {identifier}")
    if source.get("authority") != "EUR-Lex":
        raise ValueError(f"coverage source authority must be EUR-Lex: {identifier}")
    if source.get("source_kind") not in {
        "consolidated_documentation_text",
        "official_journal_legal_act",
    }:
        raise ValueError(f"invalid source kind: {identifier}")
    for field, expected_value in expected.items():
        if source.get(field) != expected_value:
            raise ValueError(
                f"coverage source {field} disagrees with pin: {identifier}"
            )
    if ("base_celex" in source) != ("base_celex" in expected):
        raise ValueError(f"coverage source base CELEX shape disagrees: {identifier}")
    _nonblank_string(source.get("title"), f"{identifier}.title")
    _nonblank_string(source.get("version_note"), f"{identifier}.version_note")
    if _iso_date(source.get("checked_on"), f"{identifier}.checked_on") != checked_on:
        raise ValueError(f"source check date disagrees with matrix: {identifier}")
    return identifier


def _validate_status_boundary(
    identifier: str,
    status: str,
    relationship: str,
    *,
    implemented_behavior: list[str],
    missing_behavior: list[str],
    present_inputs: list[str],
    missing_inputs: list[str],
) -> None:
    if status == "implemented" and (
        missing_behavior or missing_inputs or relationship != "aligned_subset"
    ):
        raise ValueError(f"implemented row has an incomplete boundary: {identifier}")
    if status == "not_implemented" and (
        implemented_behavior
        or not missing_behavior
        or not missing_inputs
        or relationship != "no_implementation"
    ):
        raise ValueError(
            f"not-implemented row claims implemented behavior: {identifier}"
        )
    if status == "partial" and (
        not implemented_behavior
        or not missing_behavior
        or not present_inputs
        or not missing_inputs
        or relationship == "no_implementation"
    ):
        raise ValueError(f"partial row is missing a two-sided boundary: {identifier}")


def _validate_requirement(requirement: Any, source_ids: set[str]) -> str:
    if not isinstance(requirement, dict):
        raise ValueError("coverage requirement must be an object")
    _require_exact_keys(
        requirement,
        {
            "requirement_id",
            "title",
            "regulatory_requirement",
            "citations",
            "implementation",
            "inputs",
            "formula",
            "tests",
            "expert_review",
        },
        "coverage requirement",
    )
    identifier = _nonblank_string(
        requirement.get("requirement_id"), "requirement.requirement_id"
    )
    _nonblank_string(requirement.get("title"), f"{identifier}.title")
    _nonblank_string(
        requirement.get("regulatory_requirement"),
        f"{identifier}.regulatory_requirement",
    )

    citations = requirement.get("citations")
    if not isinstance(citations, list) or not citations:
        raise ValueError(f"requirement has no citations: {identifier}")
    for citation in citations:
        if not isinstance(citation, dict):
            raise ValueError(f"citation must be an object: {identifier}")
        _require_exact_keys(
            citation,
            {"source_id", "provision"},
            f"{identifier}.citation",
        )
        source_id = _nonblank_string(
            citation.get("source_id"), f"{identifier}.citation.source_id"
        )
        if source_id not in source_ids:
            raise ValueError(f"requirement cites an unknown source: {identifier}")
        _nonblank_string(citation.get("provision"), f"{identifier}.citation.provision")

    implementation = requirement.get("implementation")
    if not isinstance(implementation, dict):
        raise ValueError(f"implementation must be an object: {identifier}")
    _require_exact_keys(
        implementation,
        {"status", "code_refs", "implemented_behavior", "missing_behavior"},
        f"{identifier}.implementation",
    )
    status = implementation.get("status")
    if status not in ALLOWED_COVERAGE_STATUSES:
        raise ValueError(f"invalid implementation status: {identifier}")
    _validate_code_references(implementation.get("code_refs"), identifier)
    implemented_behavior = _string_list(
        implementation.get("implemented_behavior"),
        f"{identifier}.implemented_behavior",
        allow_empty=status == "not_implemented",
    )
    missing_behavior = _string_list(
        implementation.get("missing_behavior"),
        f"{identifier}.missing_behavior",
        allow_empty=status == "implemented",
    )

    inputs = requirement.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"inputs must be an object: {identifier}")
    _require_exact_keys(
        inputs,
        {"present", "missing"},
        f"{identifier}.inputs",
    )
    present_inputs = _string_list(
        inputs.get("present"),
        f"{identifier}.inputs.present",
        allow_empty=True,
    )
    missing_inputs = _string_list(
        inputs.get("missing"),
        f"{identifier}.inputs.missing",
        allow_empty=status == "implemented",
    )

    formula = requirement.get("formula")
    if not isinstance(formula, dict):
        raise ValueError(f"formula must be an object: {identifier}")
    _require_exact_keys(
        formula,
        {"official_rule", "ecoguard_behavior", "relationship"},
        f"{identifier}.formula",
    )
    _nonblank_string(formula.get("official_rule"), f"{identifier}.official_rule")
    _nonblank_string(
        formula.get("ecoguard_behavior"), f"{identifier}.ecoguard_behavior"
    )
    relationship = formula.get("relationship")
    if relationship not in ALLOWED_RELATIONSHIPS:
        raise ValueError(f"invalid formula relationship: {identifier}")
    _validate_status_boundary(
        identifier,
        status,
        relationship,
        implemented_behavior=implemented_behavior,
        missing_behavior=missing_behavior,
        present_inputs=present_inputs,
        missing_inputs=missing_inputs,
    )

    _string_list(requirement.get("tests"), f"{identifier}.tests")
    for reference in requirement["tests"]:
        if TEST_REFERENCE_PATTERN.fullmatch(reference) is None:
            raise ValueError(f"invalid test reference: {identifier}")
    expert_review = requirement.get("expert_review")
    if not isinstance(expert_review, dict) or expert_review.get("required") is not True:
        raise ValueError(f"expert review must remain required: {identifier}")
    _require_exact_keys(
        expert_review,
        {"required", "topics"},
        f"{identifier}.expert_review",
    )
    _string_list(expert_review.get("topics"), f"{identifier}.expert_review.topics")
    return identifier


def _validate_code_references(value: Any, label: str) -> list[str]:
    references = _string_list(value, f"{label}.code_refs")
    if any(
        CODE_REFERENCE_PATTERN.fullmatch(reference) is None for reference in references
    ):
        raise ValueError(f"invalid code reference: {label}")
    return references


def _validate_claim_boundaries(claims: Any) -> None:
    if not isinstance(claims, dict):
        raise ValueError("coverage claims must be an object")
    if set(claims) != EXPECTED_FALSE_CLAIMS:
        raise ValueError("coverage claims must use the exact supported boundary keys")
    inflated = [key for key in EXPECTED_FALSE_CLAIMS if claims.get(key) is not False]
    if inflated:
        raise ValueError("coverage matrix must keep all statutory claims false")


def _validate_coverage_scope(scope: Any) -> None:
    if not isinstance(scope, dict):
        raise ValueError("coverage scope must be an object")
    _require_exact_keys(
        scope,
        {"assessment_type", "code_surface", "purpose", "excluded_claims"},
        "coverage scope",
    )
    if scope.get("assessment_type") != "selected_requirement_mapping":
        raise ValueError("coverage scope must be explicitly non-exhaustive")
    _nonblank_string(scope.get("code_surface"), "scope.code_surface")
    _nonblank_string(scope.get("purpose"), "scope.purpose")
    _string_list(scope.get("excluded_claims"), "scope.excluded_claims")


def _reject_duplicate_identifiers(identifiers: list[str], label: str) -> None:
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate {label} id")


def _validate_technical_controls(controls: Any) -> None:
    if not isinstance(controls, list) or not controls:
        raise ValueError("technical controls must be separated from legal coverage")
    for index, control in enumerate(controls):
        if not isinstance(control, dict):
            raise ValueError("technical control must be an object")
        _require_exact_keys(
            control,
            {"control_id", "description", "classification", "code_refs"},
            f"control[{index}]",
        )
        _nonblank_string(control.get("control_id"), f"control[{index}].control_id")
        _nonblank_string(control.get("description"), f"control[{index}].description")
        if control.get("classification") != "implemented_non_statutory_control":
            raise ValueError("technical control is mislabeled as statutory coverage")
        _validate_code_references(control.get("code_refs"), f"control[{index}]")


def validate_coverage_matrix(matrix: Any) -> dict[str, Any]:
    """Validate source binding and claim boundaries in a coverage matrix."""
    if not isinstance(matrix, dict):
        raise ValueError("coverage matrix must be an object")
    expected_keys = {
        "schema_version",
        "as_of",
        "title",
        "claims",
        "scope",
        "sources",
        "summary",
        "requirements",
        "technical_controls_outside_statutory_coverage",
    }
    if set(matrix) != expected_keys:
        raise ValueError("coverage matrix must use the exact supported top-level keys")
    if matrix.get("schema_version") != COVERAGE_SCHEMA_VERSION:
        raise ValueError("unsupported CBAM coverage schema version")
    _nonblank_string(matrix.get("title"), "coverage.title")
    checked_on = _iso_date(matrix.get("as_of"), "coverage.as_of")

    _validate_claim_boundaries(matrix.get("claims"))
    _validate_coverage_scope(matrix.get("scope"))

    sources = matrix.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("coverage matrix must contain official sources")
    source_ids = [_validate_coverage_source(source, checked_on) for source in sources]
    _reject_duplicate_identifiers(source_ids, "coverage source")
    if set(source_ids) != set(EXPECTED_COVERAGE_SOURCES):
        raise ValueError("coverage source set disagrees with pinned official sources")

    requirements = matrix.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("coverage matrix must contain requirements")
    requirement_ids = [
        _validate_requirement(requirement, set(source_ids))
        for requirement in requirements
    ]
    _reject_duplicate_identifiers(requirement_ids, "coverage requirement")

    counts = Counter(
        requirement["implementation"]["status"] for requirement in requirements
    )
    observed = {
        status: counts.get(status, 0) for status in sorted(ALLOWED_COVERAGE_STATUSES)
    }
    summary = matrix.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("coverage summary must be an object")
    _require_exact_keys(
        summary,
        {"requirement_count", "status_counts", "interpretation"},
        "coverage summary",
    )
    if summary.get("requirement_count") != len(requirements):
        raise ValueError("coverage requirement count is stale")
    if summary.get("status_counts") != observed:
        raise ValueError("coverage status counts are stale")
    _nonblank_string(summary.get("interpretation"), "coverage.summary.interpretation")

    _validate_technical_controls(
        matrix.get("technical_controls_outside_statutory_coverage")
    )

    return {
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "as_of": checked_on,
        "assessment_type": matrix["scope"]["assessment_type"],
        "claims": dict(sorted(matrix["claims"].items())),
        "interpretation": matrix["summary"]["interpretation"],
        "source_count": len(sources),
        "requirement_count": len(requirements),
        "status_counts": observed,
        "expert_review_required_count": len(requirements),
        "matrix_sha256": _sha256(matrix),
    }


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^0-9a-z가-힣]+", " ", normalized)
    return " ".join(normalized.split())


def _protected_corpus_phrases(corpus: list[dict[str, Any]]) -> set[str]:
    phrases: set[str] = set()
    for entry in corpus:
        for field in ("title", "summary_ko"):
            value = entry.get(field)
            if isinstance(value, str):
                phrases.add(_normalize_text(value))
        for value in entry.get("keywords", []):
            phrases.add(_normalize_text(value))
        for aliases in entry.get("concepts", {}).values():
            for value in aliases:
                phrases.add(_normalize_text(value))
    return {phrase for phrase in phrases if phrase}


def _validate_holdout_separation(
    fixture: dict[str, Any],
    corpus: list[dict[str, Any]],
    development_cases: list[dict[str, Any]],
) -> None:
    policy = fixture["construction"]["verbatim_policy"]
    minimum_characters = policy.get("minimum_protected_phrase_characters")
    if not isinstance(minimum_characters, int) or minimum_characters < 8:
        raise ValueError("blind fixture phrase threshold must be at least 8")

    development_queries = {
        _normalize_text(case["query"])
        for case in development_cases
        if isinstance(case, dict) and isinstance(case.get("query"), str)
    }
    protected_phrases = _protected_corpus_phrases(corpus)
    blind_queries: set[str] = set()
    for case in fixture["cases"]:
        query = _normalize_text(case["query"])
        if query in blind_queries:
            raise ValueError(
                f"blind fixture has duplicate normalized query: {case['id']}"
            )
        blind_queries.add(query)
        if query in development_queries:
            raise ValueError(f"blind query duplicates development data: {case['id']}")
        compact_query = query.replace(" ", "")
        for phrase in protected_phrases:
            compact_phrase = phrase.replace(" ", "")
            if (
                len(compact_phrase) >= minimum_characters
                and compact_phrase in compact_query
            ):
                raise ValueError(
                    "blind query copies a protected corpus phrase: "
                    f"{case['id']}: {phrase}"
                )


def _validate_blind_construction(construction: Any) -> None:
    if not isinstance(construction, dict):
        raise ValueError("blind fixture construction metadata is missing")
    expected_keys = {
        "evaluation_type",
        "authorship",
        "external_blind",
        "development_queries_reused",
        "description",
        "verbatim_policy",
        "limitations",
    }
    if set(construction) != expected_keys:
        raise ValueError("blind fixture construction keys are not supported")
    if construction.get("evaluation_type") != "post_hoc_blind_style_holdout":
        raise ValueError("benchmark must not be labeled as an external blind test")
    if construction.get("external_blind") is not False:
        raise ValueError("external blind authorship must not be claimed")
    if construction.get("authorship") != "repository_maintainer":
        raise ValueError("blind-style fixture authorship must be explicit")
    if construction.get("development_queries_reused") is not False:
        raise ValueError("development query reuse must be false")
    _nonblank_string(construction.get("description"), "construction.description")
    _string_list(construction.get("limitations"), "construction.limitations")
    verbatim_policy = construction.get("verbatim_policy")
    if not isinstance(verbatim_policy, dict):
        raise ValueError("blind fixture verbatim policy is missing")
    _require_exact_keys(
        verbatim_policy,
        {"minimum_protected_phrase_characters", "rule"},
        "construction.verbatim_policy",
    )
    _nonblank_string(verbatim_policy.get("rule"), "construction.verbatim_policy.rule")


def _validate_blind_binding(
    binding: Any,
    corpus: list[dict[str, Any]],
    development_cases: list[dict[str, Any]],
) -> tuple[str, str]:
    if not isinstance(binding, dict):
        raise ValueError("blind fixture corpus binding is missing")
    if set(binding) != {
        "corpus",
        "corpus_sha256",
        "development_fixture",
        "development_fixture_sha256",
    }:
        raise ValueError("blind fixture binding keys are not supported")
    corpus_hash = LegalRetriever(corpus).corpus_hash
    if binding.get("corpus_sha256") != corpus_hash:
        raise ValueError("blind fixture is bound to a different corpus")
    development_hash = _sha256(development_cases)
    if binding.get("development_fixture_sha256") != development_hash:
        raise ValueError("blind fixture is bound to a different development fixture")
    _nonblank_string(binding.get("corpus"), "binding.corpus")
    _nonblank_string(binding.get("development_fixture"), "binding.development_fixture")
    return corpus_hash, development_hash


def _validate_blind_case_ids(cases: list[dict[str, Any]]) -> None:
    case_ids = [case.get("id") for case in cases]
    if any(
        not isinstance(identifier, str) or not identifier for identifier in case_ids
    ):
        raise ValueError("blind fixture has a blank case id")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("blind fixture has duplicate case ids")


def _validated_blind_case_counts(
    declared_counts: Any, cases: list[dict[str, Any]]
) -> dict[str, int]:
    observed_counts = Counter(case["type"] for case in cases)
    expected_counts = {
        kind: observed_counts.get(kind, 0)
        for kind in ("positive", "distractor", "negative")
    }
    if declared_counts != expected_counts:
        raise ValueError("blind fixture case counts are stale")
    if any(count == 0 for count in expected_counts.values()):
        raise ValueError("blind fixture must include every evaluation case class")
    return expected_counts


def _validate_blind_thresholds(thresholds: Any) -> None:
    required_thresholds = {
        "minimum_recall_at_k",
        "minimum_negative_abstention_rate",
        "minimum_distractor_rejection_at_1",
        "minimum_expected_status_match_rate",
        "maximum_false_support_rate",
        "maximum_instrument_leakage_at_k",
    }
    if not isinstance(thresholds, dict) or set(thresholds) != required_thresholds:
        raise ValueError("blind fixture acceptance thresholds are incomplete")
    for name, value in thresholds.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"invalid blind fixture threshold: {name}")
        if not 0 <= float(value) <= 1:
            raise ValueError(f"invalid blind fixture threshold: {name}")


def validate_blind_fixture(
    fixture: Any,
    corpus: list[dict[str, Any]],
    development_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate holdout provenance, labels and separation from development data."""
    if not isinstance(fixture, dict):
        raise ValueError("blind fixture must be an object")
    expected_keys = {
        "schema_version",
        "benchmark_id",
        "created_on",
        "k",
        "binding",
        "construction",
        "case_counts",
        "acceptance_thresholds",
        "cases",
    }
    if set(fixture) != expected_keys:
        raise ValueError("blind fixture must use the exact supported top-level keys")
    if fixture.get("schema_version") != BLIND_SCHEMA_VERSION:
        raise ValueError("unsupported legal blind fixture schema version")
    benchmark_id = _nonblank_string(fixture.get("benchmark_id"), "benchmark_id")
    _iso_date(fixture.get("created_on"), "blind.created_on")
    k = fixture.get("k")
    if type(k) is not int or not 1 <= k <= len(corpus):
        raise ValueError("blind fixture k must be a positive in-corpus integer")

    construction = fixture.get("construction")
    _validate_blind_construction(construction)

    # The development fixture is part of the benchmark's separation claim. It
    # must remain a real, schema-valid evaluation set rather than an empty or
    # caller-substituted list that makes overlap checks vacuously pass.
    evaluate(corpus, development_cases, k=k)
    corpus_hash, development_hash = _validate_blind_binding(
        fixture.get("binding"), corpus, development_cases
    )

    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("blind fixture must contain cases")
    # The production evaluator performs the authoritative label validation.
    evaluate(corpus, cases, k=k)
    _validate_blind_case_ids(cases)

    _validate_holdout_separation(fixture, corpus, development_cases)
    expected_counts = _validated_blind_case_counts(fixture.get("case_counts"), cases)
    _validate_blind_thresholds(fixture.get("acceptance_thresholds"))

    return {
        "schema_version": BLIND_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "case_count": len(cases),
        "case_counts": expected_counts,
        "corpus_sha256": corpus_hash,
        "development_fixture_sha256": development_hash,
        "fixture_sha256": _sha256(fixture),
        "external_blind": False,
    }


def evaluate_blind_fixture(
    fixture: dict[str, Any],
    corpus: list[dict[str, Any]],
    development_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and score the separate legal holdout fixture."""
    validation = validate_blind_fixture(fixture, corpus, development_cases)
    result = evaluate(corpus, fixture["cases"], k=fixture.get("k", 3))
    thresholds = fixture["acceptance_thresholds"]
    expected_status_match_rate = round(
        sum(row["expected_status"] == row["actual_status"] for row in result["cases"])
        / result["case_count"],
        4,
    )
    checks = {
        "recall_at_k": result["recall_at_k"] >= thresholds["minimum_recall_at_k"],
        "negative_abstention_rate": result["negative_abstention_rate"]
        >= thresholds["minimum_negative_abstention_rate"],
        "distractor_rejection_at_1": result["distractor_rejection_at_1"]
        >= thresholds["minimum_distractor_rejection_at_1"],
        "false_support_rate": result["false_support_rate"]
        <= thresholds["maximum_false_support_rate"],
        "instrument_leakage_at_k": result["instrument_leakage_at_k"]
        <= thresholds["maximum_instrument_leakage_at_k"],
        "expected_status_match_rate": expected_status_match_rate
        >= thresholds["minimum_expected_status_match_rate"],
    }
    return {
        "benchmark_id": fixture["benchmark_id"],
        "validation": validation,
        "metrics": {
            name: result[name]
            for name in (
                "recall_at_k",
                "mean_reciprocal_rank",
                "positive_coverage",
                "negative_abstention_rate",
                "false_support_rate",
                "distractor_rejection_at_1",
                "instrument_leakage_at_k",
                "trace_coverage",
            )
        }
        | {"expected_status_match_rate": expected_status_match_rate},
        "threshold_checks": checks,
        "passed": all(checks.values()),
        "scope": (
            "Maintainer-authored post-hoc holdout for article retrieval; "
            "not external validation, answer-generation evaluation, or legal advice."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate CBAM coverage and score the legal blind-style holdout."
    )
    parser.add_argument("--coverage", default="data/reference/cbam_rule_coverage.json")
    parser.add_argument("--blind", default="data/benchmarks/legal_blind.json")
    parser.add_argument("--corpus", default="data/reference/legal_corpus.json")
    parser.add_argument("--development-eval", default="data/reference/legal_eval.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    coverage = validate_coverage_matrix(load_json_document(args.coverage))
    fixture = load_json_document(args.blind)
    blind = evaluate_blind_fixture(
        fixture,
        load_json_document(args.corpus),
        load_json_document(args.development_eval),
    )
    print(
        json.dumps(
            {"coverage": coverage, "legal_blind_evaluation": blind},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if blind["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
