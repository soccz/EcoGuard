#!/usr/bin/env python3
"""Validate and summarize committed EcoGuard proof artifacts offline."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any


CORE_OUTPUTS = {
    "cbam_exposure": "artifacts/examples/cbam_exposure.json",
    "evidence_report_html": "artifacts/examples/ecoguard_evidence_report.html",
    "evidence_report_json": "artifacts/examples/ecoguard_evidence_report.json",
    "extracted_records": "artifacts/examples/extracted_records.json",
    "forest_change": "artifacts/examples/forest_change.json",
    "forest_change_geojson": "artifacts/examples/forest_change.geojson",
    "forest_change_svg": "artifacts/examples/forest_change.svg",
    "legal_issue_citations": "artifacts/examples/legal_issue_citations.json",
    "legal_retrieval_evaluation": "artifacts/examples/legal_retrieval_evaluation.json",
    "normalized_evidence": "artifacts/examples/normalized_evidence.json",
}
BENCHMARK_OUTPUTS = {
    "cbam_rule_coverage_report": "artifacts/benchmarks/cbam_rule_coverage_report.json",
    "forest_geospatial_geojson": "artifacts/benchmarks/forest_geospatial.geojson",
    "forest_geospatial_summary": "artifacts/benchmarks/forest_geospatial_summary.json",
    "legal_blind_evaluation": "artifacts/benchmarks/legal_blind_evaluation.json",
    "ocr_field_benchmark": "artifacts/benchmarks/ocr_field_benchmark.json",
}


class ProofError(ValueError):
    """A committed proof artifact violated its public contract."""


def _reject_constant(value: str) -> None:
    raise ProofError(f"non-finite JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProofError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProofError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProofError(f"top-level JSON object required: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofError(message)


def _digest(path: Path) -> str:
    _require(path.is_file(), f"missing committed file: {path}")
    return sha256(path.read_bytes()).hexdigest()


def _check_file(path: Path, record: Any) -> str:
    _require(isinstance(record, dict), f"invalid manifest record: {path}")
    _require(set(record) == {"bytes", "sha256"}, f"unknown manifest keys: {path}")
    digest = _digest(path)
    _require(path.stat().st_size == record["bytes"], f"byte-size mismatch: {path}")
    _require(digest == record["sha256"], f"SHA-256 mismatch: {path}")
    return digest


def _manifest_hashes(
    root: Path,
    manifest_path: str,
    schema: str,
    files: dict[str, str],
) -> tuple[dict[str, str], dict[str, Any]]:
    manifest = _load_json(root / manifest_path)
    _require(manifest.get("schema_version") == schema, f"unsupported {manifest_path}")
    records = manifest.get("outputs")
    _require(isinstance(records, dict), f"missing {manifest_path}:outputs")
    _require(set(records) == set(files), f"file set mismatch: {manifest_path}:outputs")
    hashes = {
        name: _check_file(root / relative, records[name])
        for name, relative in files.items()
    }
    return hashes, manifest


def _lineage_values(root: Path) -> dict[str, Any]:
    extracted = _load_json(root / CORE_OUTPUTS["extracted_records"])
    normalized = _load_json(root / CORE_OUTPUTS["normalized_evidence"])
    summary = extracted["summary"]
    _require(
        (
            summary["document_count"],
            summary["line_count"],
            summary["matched_line_count"],
        )
        == (7, 37, 30),
        "unexpected ingestion summary",
    )
    field = normalized["fields"]["m5_process_direct_intensity_tco2e_per_t"]
    selected = field["selected_from"]
    records = [
        record
        for record in extracted["records"]
        if record["record_id"] == selected["record_id"]
    ]
    _require(len(records) == 1, "selected evidence does not resolve uniquely")
    record = records[0]
    _require(record["value"] == selected["raw_value"], "raw value lineage mismatch")
    for key in ("line_sha256", "document_sha256", "source_span"):
        _require(record[key] == selected[key], f"{key} lineage mismatch")
    raw_line = record["raw_line"]
    _require(_digest_text(raw_line) == record["line_sha256"], "raw-line hash mismatch")
    start, end = (record["source_span"][key] for key in ("value_start", "value_end"))
    _require(raw_line[start:end] == record["value"], "raw value span mismatch")
    _require(
        (field["value"], field["unit"]) == ("3.2", "tCO2e/t"),
        "normalized value mismatch",
    )
    return {
        "documents": summary["document_count"],
        "lines": summary["line_count"],
        "candidates": summary["matched_line_count"],
        "fields": normalized["summary"]["field_count"],
        "record_id": record["record_id"],
        "line_hash": record["line_sha256"],
        "span": f"[{start},{end})",
        "value": field["value"],
    }


def _digest_text(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _cbam_values(root: Path, lineage: dict[str, Any]) -> dict[str, Any]:
    cbam = _load_json(root / CORE_OUTPUTS["cbam_exposure"])
    trace = cbam["technical_inventory"]["calculation_trace"]
    _require(len(trace) == 11, "CBAM trace must contain 11 steps")
    direct = next(
        (step for step in trace if step.get("step_id") == "m5.process_direct"), None
    )
    _require(direct is not None, "missing CBAM step: m5.process_direct")
    linked = [
        operand
        for operand in direct["operands"]
        if operand.get("evidence_ref") == lineage["record_id"]
    ]
    _require(len(linked) == 1, "normalized field does not reach the CBAM leaf")
    _require(
        Decimal(linked[0]["exact"]) == Decimal(lineage["value"]), "CBAM leaf mismatch"
    )
    reconciliation = cbam["reconciliation"]
    checks = (
        "direct_plus_indirect_matches_total",
        "process_plus_precursor_matches_total",
        "intensity_matches",
        "mass_matches",
    )
    _require(
        all(reconciliation[key] is True for key in checks), "CBAM reconciliation failed"
    )
    total = cbam["technical_inventory"]["embedded_emissions_exact_tco2e"]
    _require(
        Decimal(trace[-1]["result_exact"]) == Decimal(total), "CBAM total mismatch"
    )
    return {
        "steps": len(trace),
        "direct": direct["display_value"],
        "total": total,
        "pipeline_version": cbam["reproduction"]["pipeline_version"],
    }


def _artifact_files(base: Path, payload: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name, record in payload["files"].items():
        relative = Path(record["path"])
        _require(
            not relative.is_absolute() and ".." not in relative.parts,
            "unsafe artifact path",
        )
        digest = _digest(base / relative)
        _require(
            digest == record["sha256"], f"research artifact hash mismatch: {relative}"
        )
        hashes[name] = digest
    return hashes


def _validate_research_claims(
    evaluation: dict[str, Any],
    latent: dict[str, Any],
    terrain: dict[str, Any],
) -> None:
    public = evaluation["claim_boundary"]
    _require(public["forest_cover_segmentation"] is True, "forest-cover scope missing")
    _require(
        public["real_public_satellite_pixels"] is True, "public-pixel scope missing"
    )
    _require(
        public["bi_temporal_change_detection"] is False, "bi-temporal claim inflation"
    )
    for key in (
        "post_award_reconstruction",
        "not_a_higan_reproduction",
        "not_photorealistic",
    ):
        _require(
            latent["claim_boundary"][key] is True, f"latent boundary missing: {key}"
        )
    for key in (
        "post_award_reconstruction",
        "not_satellite_derived_elevation",
        "synthetic_height_field",
        "bilinear_height_interpolation",
    ):
        _require(
            terrain["claim_boundary"][key] is True, f"terrain boundary missing: {key}"
        )


def _research_values(root: Path) -> dict[str, Any]:
    base = root / "research/forest_xai/artifacts/public_demo"
    evaluation = _load_json(base / "evaluation.json")
    explanation_base = base / "explanation"
    explanation = _load_json(explanation_base / "explanation.json")
    reconstruction = base / "reconstruction"
    latent = _load_json(reconstruction / "latent_interpolation.json")
    terrain = _load_json(reconstruction / "terrain_drape.json")
    _validate_research_claims(evaluation, latent, terrain)

    checkpoint = _digest(base / "sentinel2_forest_cover.pt")
    gan_checkpoint = _digest(reconstruction / "latent_gan.pt")
    _require(
        evaluation["checkpoint_sha256"] == checkpoint, "public checkpoint mismatch"
    )
    _require(
        explanation["checkpoint_sha256"] == checkpoint, "Grad-CAM checkpoint mismatch"
    )
    _require(
        latent["classifier_checkpoint_sha256"] == checkpoint,
        "latent classifier mismatch",
    )
    _require(
        latent["gan_checkpoint_sha256"] == gan_checkpoint, "GAN checkpoint mismatch"
    )
    explanation_hashes = _artifact_files(explanation_base, explanation)
    latent_hashes = _artifact_files(reconstruction, latent)
    terrain_hashes = _artifact_files(reconstruction, terrain)
    _require(
        latent["frames"]
        == len(latent["alphas"])
        == len(latent["forest_probabilities"])
        == 8,
        "latent frame count mismatch",
    )
    mesh = terrain["mesh"]
    _require(
        (mesh["vertex_count"], mesh["face_count"]) == (1089, 1024), "mesh mismatch"
    )
    return {
        "f1": evaluation["metrics"]["f1"],
        "iou": evaluation["metrics"]["iou"],
        "checkpoint": checkpoint,
        "gradcam": explanation_hashes["gradcam"],
        "frames": latent["frames"],
        "jvp": latent["jvp"]["unit_path_direction_derivative"],
        "latent": latent_hashes["contact_sheet"],
        "vertices": mesh["vertex_count"],
        "faces": mesh["face_count"],
        "drape": terrain_hashes["drape"],
    }


def collect_proof(root: str | Path) -> dict[str, Any]:
    """Return representative values after validating committed proof files."""
    root = Path(root).resolve()
    core_hashes, core_manifest = _manifest_hashes(
        root,
        "artifacts/examples/artifact_manifest.json",
        "artifact-manifest/1.0",
        CORE_OUTPUTS,
    )
    benchmark_hashes, _ = _manifest_hashes(
        root,
        "artifacts/benchmarks/benchmark_manifest.json",
        "benchmark-artifact-manifest/1.0",
        BENCHMARK_OUTPUTS,
    )
    lineage = _lineage_values(root)
    cbam = _cbam_values(root, lineage)
    _require(
        cbam["pipeline_version"] == core_manifest["pipeline_version"],
        "version mismatch",
    )

    ocr = _load_json(root / BENCHMARK_OUTPUTS["ocr_field_benchmark"])
    ocr_eval = ocr["field_evaluation"]
    legal = _load_json(root / BENCHMARK_OUTPUTS["legal_blind_evaluation"])
    _require(legal["passed"] is True, "legal thresholds failed")
    _require(
        legal["validation"]["external_blind"] is False, "legal holdout boundary changed"
    )
    _require(
        legal["metrics"]["negative_abstention_rate"] == 1, "legal abstention regressed"
    )
    citations = _load_json(root / CORE_OUTPUTS["legal_issue_citations"])
    bound = citations["source_binding"]["bound_sources"]
    _require(
        citations["source_binding"]["status"] == "verified"
        and all(
            source["eli"].startswith("https://eur-lex.europa.eu/") for source in bound
        ),
        "legal citations are not EUR-Lex-bound",
    )
    return {
        "pipeline_version": core_manifest["pipeline_version"],
        "lineage": lineage,
        "cbam": cbam,
        "ocr": {**ocr_eval["counts"], "f1": ocr_eval["metrics"]["f1"]},
        "legal": legal,
        "research": _research_values(root),
        "core_hashes": core_hashes,
        "benchmark_hashes": benchmark_hashes,
    }


def format_summary(proof: dict[str, Any]) -> str:
    """Format validated values for a human reviewer."""
    source, cbam, ocr = (proof[key] for key in ("lineage", "cbam", "ocr"))
    legal, research = proof["legal"], proof["research"]
    counts, metrics = legal["validation"]["case_counts"], legal["metrics"]
    return "\n".join(
        (
            f"EcoGuard committed proof — pipeline {proof['pipeline_version']} (offline)",
            f"[PASS] OCR/provenance  {source['documents']} docs · {source['lines']} lines · "
            f"{source['candidates']} candidates; value span {source['span']}; "
            f"line sha256 {source['line_hash'][:12]}…",
            f"[PASS] normalization→CBAM  {source['fields']} fields; {cbam['steps']}-step "
            f"DAG; m5.direct {cbam['direct']} · total {cbam['total']} tCO2e; reconciled; "
            f"artifacts/examples/cbam_exposure.json "
            f"{proof['core_hashes']['cbam_exposure'][:12]}…",
            f"[PASS] OCR adapter benchmark  TP/FP/FN {ocr['true_positive']}/"
            f"{ocr['false_positive']}/{ocr['false_negative']} · F1 {ocr['f1']} "
            "(intentional-error fixture, not OCR accuracy)",
            f"[PASS] legal citation/abstention  {counts['positive']} positive + "
            f"{counts['distractor']} distractor + {counts['negative']} negative; "
            f"Recall@3/MRR/abstention {metrics['recall_at_k']}/"
            f"{metrics['mean_reciprocal_rank']}/{metrics['negative_abstention_rate']}; "
            f"EUR-Lex-bound; artifacts/benchmarks/legal_blind_evaluation.json "
            f"{proof['benchmark_hashes']['legal_blind_evaluation'][:12]}… "
            "(maintainer-authored, not legal advice)",
            f"[PASS] Sentinel-2/Grad-CAM  single-date forest-cover F1 "
            f"{research['f1']} · IoU {research['iou']}; checkpoint "
            f"{research['checkpoint'][:12]}… · Grad-CAM {research['gradcam'][:12]}…",
            f"[PASS] post-award GAN/2.5D  {research['frames']} frames · JVP "
            f"{research['jvp']} · mesh {research['vertices']} vertices/"
            f"{research['faces']} faces; latent {research['latent'][:12]}… · drape "
            f"{research['drape'][:12]}… (not HiGAN, photorealism, or "
            "satellite-derived elevation)",
            f"[PASS] manifests  {len(proof['core_hashes'])} core + "
            f"{len(proof['benchmark_hashes'])} benchmark outputs match committed byte "
            "sizes and SHA-256 records",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    try:
        print(format_summary(collect_proof(args.root)))
    except (ProofError, KeyError, TypeError, ValueError) as exc:
        print(f"[FAIL] committed proof validation: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
