"""Orchestrate repository-owned, synthetic and blind-style benchmarks."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from .geospatial import analyze_geospatial_benchmark, build_geospatial_geojson
from .jsonio import strict_json_file
from .legal import validate_source_manifest
from .ocr_adapter import (
    SYNTHETIC_BENCHMARK_SCOPE,
    adapt_ocr_file,
    benchmark_document_bundle,
)
from .pipeline import repository_root
from .regulatory import evaluate_blind_fixture, validate_coverage_matrix

BENCHMARK_VERSION = "1.0.0"
INPUT_PATHS = {
    "ocr_tesseract_tsv": "data/benchmarks/ocr/synthetic_tesseract.tsv",
    "ocr_field_reference": ("data/benchmarks/ocr/synthetic_field_reference.json"),
    "forest_manifest": "data/benchmarks/forest/synthetic_geospatial_case.json",
    "forest_scene_pixels": ("data/benchmarks/forest/synthetic_scene_pixels.csv"),
    "forest_reference_mask": ("data/benchmarks/forest/synthetic_reference_mask.csv"),
    "legal_corpus": "data/reference/legal_corpus.json",
    "legal_development_eval": "data/reference/legal_eval.json",
    "legal_blind_eval": "data/benchmarks/legal_blind.json",
    "legal_source_manifest": "data/reference/source_manifest.json",
    "cbam_rule_coverage": "data/reference/cbam_rule_coverage.json",
}


def _strict_json(path: Path) -> Any:
    return strict_json_file(path)


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


def _file_manifest(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "bytes": path.stat().st_size,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in sorted(paths.items())
    }


def _input_files(root: Path) -> dict[str, Path]:
    paths = {name: root / relative for name, relative in INPUT_PATHS.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "benchmark fixtures are repository assets; missing: " + ", ".join(missing)
        )
    return paths


def run_benchmarks(
    output: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, Path]:
    """Run all public benchmark contracts and write byte-stable evidence."""
    root_path = Path(root).resolve() if root else repository_root()
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.mkdir(parents=True, exist_ok=True)
    inputs = _input_files(root_path)

    ocr_reference = _strict_json(inputs["ocr_field_reference"])
    ocr_bundle = adapt_ocr_file(
        inputs["ocr_tesseract_tsv"],
        input_format="tesseract-tsv",
        case_id=ocr_reference["case_id"],
        document_id="synthetic_ocr_invoice",
        document_type="commercial_invoice",
        language="ko-en",
    )
    ocr = benchmark_document_bundle(
        ocr_bundle,
        ocr_reference,
        scope=SYNTHETIC_BENCHMARK_SCOPE,
    )

    geospatial = analyze_geospatial_benchmark(inputs["forest_manifest"])
    geospatial_summary = geospatial["summary"]
    geospatial_geojson = build_geospatial_geojson(geospatial)

    corpus = _strict_json(inputs["legal_corpus"])
    development_cases = _strict_json(inputs["legal_development_eval"])
    blind_fixture = _strict_json(inputs["legal_blind_eval"])
    validate_source_manifest(corpus, _strict_json(inputs["legal_source_manifest"]))
    legal_blind = evaluate_blind_fixture(blind_fixture, corpus, development_cases)
    if not legal_blind["passed"]:
        raise ValueError("legal blind-style benchmark did not meet pinned thresholds")
    cbam_coverage = validate_coverage_matrix(_strict_json(inputs["cbam_rule_coverage"]))

    input_manifest = _file_manifest(inputs)
    reproduction = {
        "benchmark_version": BENCHMARK_VERSION,
        "inputs": input_manifest,
        "policy": {
            "committed_inputs": "synthetic_or_maintainer_authored_reference",
            "external_network_io": False,
            "timestamps_in_outputs": False,
        },
    }
    outputs = {
        "ocr_field_benchmark": output_path / "ocr_field_benchmark.json",
        "forest_geospatial_summary": (output_path / "forest_geospatial_summary.json"),
        "forest_geospatial_geojson": (output_path / "forest_geospatial.geojson"),
        "legal_blind_evaluation": output_path / "legal_blind_evaluation.json",
        "cbam_rule_coverage_report": (output_path / "cbam_rule_coverage_report.json"),
    }
    payloads = {
        "ocr_field_benchmark": ocr,
        "forest_geospatial_summary": geospatial_summary,
        "forest_geospatial_geojson": geospatial_geojson,
        "legal_blind_evaluation": legal_blind,
        "cbam_rule_coverage_report": cbam_coverage,
    }
    for name, payload in payloads.items():
        if isinstance(payload, dict):
            payload = {**payload, "reproduction": reproduction}
        _write_json(outputs[name], payload)

    manifest = {
        "schema_version": "benchmark-artifact-manifest/1.0",
        **reproduction,
        "outputs": _file_manifest(outputs),
        "verification": (
            "Run `ecoguard benchmark --root . --output artifacts/generated-benchmarks` "
            "and compare bytes with artifacts/benchmarks."
        ),
    }
    manifest_path = output_path / "benchmark_manifest.json"
    _write_json(manifest_path, manifest)
    outputs["benchmark_manifest"] = manifest_path
    return outputs
