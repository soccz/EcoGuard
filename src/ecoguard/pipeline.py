"""Orchestrate the deterministic EcoGuard evidence pipeline."""

from __future__ import annotations

import json
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from .cbam import calculate_exposure
from .forest import analyze_forest_case, build_regions_geojson, render_change_svg
from .ingestion import extract_document_bundle_file
from .legal import (
    evaluate,
    load_json,
    retrieve_issue_citations,
    validate_source_manifest,
)
from .preprocessing import load_policy, normalize_records
from .report import build_evidence_packet, render_html


PIPELINE_VERSION = "0.3.0"
SCHEMA_VERSION = "3.0.0"
INPUT_SPECS = (
    (
        "trade_case_documents",
        "data/synthetic/trade_case_documents.json",
        "trade_case_documents.json",
    ),
    (
        "normalization_policy",
        "data/reference/normalization_policy.json",
        "normalization_policy.json",
    ),
    ("legal_corpus", "data/reference/legal_corpus.json", "legal_corpus.json"),
    ("legal_eval", "data/reference/legal_eval.json", "legal_eval.json"),
    (
        "legal_source_manifest",
        "data/reference/source_manifest.json",
        "source_manifest.json",
    ),
    ("forest_case", "data/synthetic/forest_case.json", "forest_case.json"),
    (
        "forest_pixels",
        "data/synthetic/forest_pixels.csv",
        "forest_pixels.csv",
    ),
    (
        "forest_reference_mask",
        "data/synthetic/forest_reference_mask.csv",
        "forest_reference_mask.csv",
    ),
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _input_path(
    root: Path,
    relative_path: str,
    resource_name: str,
    *,
    allow_package_fallback: bool,
) -> Path:
    candidate = root / relative_path
    if candidate.is_file():
        return candidate
    if allow_package_fallback:
        resource = files("ecoguard.resources").joinpath(resource_name)
        if resource.is_file():
            return Path(str(resource))
    raise FileNotFoundError(candidate)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _file_manifest(paths: dict[str, Path]) -> dict[str, Any]:
    return {
        name: {
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for name, path in sorted(paths.items())
    }


def _stage_reproduction(
    reproduction: dict[str, Any],
    *input_names: str,
) -> dict[str, Any]:
    return {
        **reproduction,
        "input_subset": list(input_names),
    }


def reproduce(
    output: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, Path]:
    """Run all stages and write a byte-stable public evidence packet."""
    use_packaged_resources = root is None
    root_path = Path(root).resolve() if root else repository_root()
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.mkdir(parents=True, exist_ok=True)

    input_paths = {
        name: _input_path(
            root_path,
            relative_path,
            resource_name,
            allow_package_fallback=use_packaged_resources,
        )
        for name, relative_path, resource_name in INPUT_SPECS
    }
    reproduction = {
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "determinism": {
            "json_keys": "sorted",
            "json_allow_nan": False,
            "record_order": "document/page/line and row-major",
            "timestamps_in_artifacts": False,
        },
        "inputs": _file_manifest(input_paths),
    }

    extraction = extract_document_bundle_file(input_paths["trade_case_documents"])
    extraction["reproduction"] = _stage_reproduction(
        reproduction,
        "trade_case_documents",
    )
    normalized = normalize_records(
        extraction,
        load_policy(input_paths["normalization_policy"]),
    )
    normalized["reproduction"] = _stage_reproduction(
        reproduction,
        "trade_case_documents",
        "normalization_policy",
    )

    corpus = load_json(input_paths["legal_corpus"])
    evaluation_cases = load_json(input_paths["legal_eval"])
    legal_source_manifest = load_json(input_paths["legal_source_manifest"])
    source_binding = validate_source_manifest(corpus, legal_source_manifest)
    legal_evaluation = evaluate(corpus, evaluation_cases, k=3)
    legal_evaluation["source_binding"] = source_binding
    legal_evaluation["reproduction"] = _stage_reproduction(
        reproduction,
        "legal_corpus",
        "legal_eval",
        "legal_source_manifest",
    )
    legal_issue_citations = retrieve_issue_citations(normalized, corpus, limit=3)
    legal_issue_citations["source_binding"] = source_binding
    legal_issue_citations["reproduction"] = _stage_reproduction(
        reproduction,
        "trade_case_documents",
        "normalization_policy",
        "legal_corpus",
        "legal_source_manifest",
    )

    cbam = calculate_exposure(normalized)
    cbam["reproduction"] = _stage_reproduction(
        reproduction,
        "trade_case_documents",
        "normalization_policy",
    )

    forest = analyze_forest_case(input_paths["forest_case"])
    forest["reproduction"] = _stage_reproduction(
        reproduction,
        "forest_case",
        "forest_pixels",
        "forest_reference_mask",
    )
    forest_svg = render_change_svg(forest)
    forest_geojson = build_regions_geojson(forest)

    packet = build_evidence_packet(
        extraction,
        normalized,
        legal_evaluation,
        legal_issue_citations,
        cbam,
        forest,
    )
    packet["reproduction"] = reproduction

    paths = {
        "extracted_records": output_path / "extracted_records.json",
        "normalized_evidence": output_path / "normalized_evidence.json",
        "legal_retrieval_evaluation": (output_path / "legal_retrieval_evaluation.json"),
        "legal_issue_citations": output_path / "legal_issue_citations.json",
        "cbam_exposure": output_path / "cbam_exposure.json",
        "forest_change": output_path / "forest_change.json",
        "forest_change_geojson": output_path / "forest_change.geojson",
        "forest_change_svg": output_path / "forest_change.svg",
        "evidence_report_json": output_path / "ecoguard_evidence_report.json",
        "evidence_report_html": output_path / "ecoguard_evidence_report.html",
    }
    _write_json(paths["extracted_records"], extraction)
    _write_json(paths["normalized_evidence"], normalized)
    _write_json(paths["legal_retrieval_evaluation"], legal_evaluation)
    _write_json(paths["legal_issue_citations"], legal_issue_citations)
    _write_json(paths["cbam_exposure"], cbam)
    _write_json(paths["forest_change"], forest)
    _write_json(paths["forest_change_geojson"], forest_geojson)
    paths["forest_change_svg"].write_text(forest_svg + "\n", encoding="utf-8")
    _write_json(paths["evidence_report_json"], packet)
    paths["evidence_report_html"].write_text(
        render_html(packet, forest_svg),
        encoding="utf-8",
    )

    artifact_manifest = {
        "schema_version": "artifact-manifest/1.0",
        "pipeline_version": PIPELINE_VERSION,
        "inputs": reproduction["inputs"],
        "outputs": _file_manifest(paths),
        "verification": (
            "Re-run `python -m ecoguard reproduce` and compare SHA-256 values or "
            "execute `./scripts/verify_release.sh` for a wheel-installed exact diff."
        ),
    }
    manifest_path = output_path / "artifact_manifest.json"
    _write_json(manifest_path, artifact_manifest)
    paths["artifact_manifest"] = manifest_path
    return paths
