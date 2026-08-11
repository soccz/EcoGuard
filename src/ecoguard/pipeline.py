"""Orchestrate the reproducible EcoGuard evidence pipeline."""

from __future__ import annotations

import json
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from .cbam import calculate_exposure
from .forest import analyze_forest_change, render_change_svg
from .legal import evaluate, load_json, retrieve_issue_citations
from .preprocessing import normalize_file
from .report import build_evidence_packet, render_html

PIPELINE_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"


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


def reproduce(
    output: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, Path]:
    use_packaged_resources = root is None
    root_path = Path(root).resolve() if root else repository_root()
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.mkdir(parents=True, exist_ok=True)

    input_paths = {
        "ocr_records": _input_path(
            root_path,
            "data/synthetic/ocr_records.json",
            "ocr_records.json",
            allow_package_fallback=use_packaged_resources,
        ),
        "legal_corpus": _input_path(
            root_path,
            "data/reference/legal_corpus.json",
            "legal_corpus.json",
            allow_package_fallback=use_packaged_resources,
        ),
        "legal_eval": _input_path(
            root_path,
            "data/reference/legal_eval.json",
            "legal_eval.json",
            allow_package_fallback=use_packaged_resources,
        ),
        "legal_source_manifest": _input_path(
            root_path,
            "data/reference/source_manifest.json",
            "source_manifest.json",
            allow_package_fallback=use_packaged_resources,
        ),
        "forest_pixels": _input_path(
            root_path,
            "data/synthetic/forest_pixels.csv",
            "forest_pixels.csv",
            allow_package_fallback=use_packaged_resources,
        ),
    }
    reproduction = {
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "inputs": _file_manifest(input_paths),
    }

    normalized = normalize_file(input_paths["ocr_records"])
    normalized["reproduction"] = {
        **reproduction,
        "input_subset": ["ocr_records"],
    }
    corpus = load_json(input_paths["legal_corpus"])
    evaluation_cases = load_json(input_paths["legal_eval"])
    legal_evaluation = evaluate(corpus, evaluation_cases, k=3)
    legal_evaluation["reproduction"] = {
        **reproduction,
        "input_subset": ["legal_corpus", "legal_eval", "legal_source_manifest"],
    }
    legal_issue_citations = retrieve_issue_citations(normalized, corpus, limit=3)
    legal_issue_citations["reproduction"] = {
        **reproduction,
        "input_subset": ["ocr_records", "legal_corpus", "legal_source_manifest"],
    }
    cbam = calculate_exposure(normalized)
    cbam["reproduction"] = {
        **reproduction,
        "input_subset": ["ocr_records"],
    }
    forest = analyze_forest_change(input_paths["forest_pixels"])
    forest["reproduction"] = {
        **reproduction,
        "input_subset": ["forest_pixels"],
    }
    forest_svg = render_change_svg(forest)
    packet = build_evidence_packet(
        normalized,
        legal_evaluation,
        legal_issue_citations,
        cbam,
        forest,
    )
    packet["reproduction"] = reproduction

    paths = {
        "normalized_evidence": output_path / "normalized_evidence.json",
        "legal_retrieval_evaluation": (
            output_path / "legal_retrieval_evaluation.json"
        ),
        "legal_issue_citations": output_path / "legal_issue_citations.json",
        "cbam_exposure": output_path / "cbam_exposure.json",
        "forest_change": output_path / "forest_change.json",
        "forest_change_svg": output_path / "forest_change.svg",
        "evidence_report_json": output_path / "ecoguard_evidence_report.json",
        "evidence_report_html": output_path / "ecoguard_evidence_report.html",
    }
    _write_json(paths["normalized_evidence"], normalized)
    _write_json(paths["legal_retrieval_evaluation"], legal_evaluation)
    _write_json(paths["legal_issue_citations"], legal_issue_citations)
    _write_json(paths["cbam_exposure"], cbam)
    _write_json(paths["forest_change"], forest)
    paths["forest_change_svg"].write_text(forest_svg + "\n", encoding="utf-8")
    _write_json(paths["evidence_report_json"], packet)
    paths["evidence_report_html"].write_text(
        render_html(packet, forest_svg),
        encoding="utf-8",
    )
    return paths
