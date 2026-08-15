#!/usr/bin/env python3
"""Verify the committed public forest-cover fixture, model, and explanations."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

import numpy as np

TRACK_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TRACK_ROOT.parents[1]
RETRAINED_PARAMETER_ATOL = 5e-4
RETRAINED_LOSS_ATOL = 5e-5
RETRAINED_METRIC_ATOL = 5e-5
RETRAINED_PROBABILITY_ATOL = 5e-4
RETRAINED_CONFUSION_ATOL = 1
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

EXPECTED_BOUNDARY = {
    "real_public_satellite_pixels": True,
    "forest_cover_segmentation": True,
    "bi_temporal_change_detection": False,
    "deforestation_cause_or_legality": False,
    "external_independent_benchmark": False,
    "purpose": "small CPU-reproducible capability demonstration, not field validation",
}


def _require_equal(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ValueError(f"{label} differs from the committed contract")


def _compare_model_state_replay(
    expected_model: Any,
    actual_model: Any,
    *,
    tolerance: float = RETRAINED_PARAMETER_ATOL,
) -> dict[str, Any]:
    """Compare one retrained model across deterministic CPU kernel variants."""
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("model replay tolerance must be finite and positive")
    expected_state = expected_model.state_dict()
    actual_state = actual_model.state_dict()
    _require_equal("retrained state keys", set(actual_state), set(expected_state))
    max_error = 0.0
    total_error = 0.0
    element_count = 0
    for tensor_name, expected_tensor in expected_state.items():
        actual_tensor = actual_state[tensor_name]
        _require_equal(
            f"retrained {tensor_name} shape",
            list(actual_tensor.shape),
            list(expected_tensor.shape),
        )
        _require_equal(
            f"retrained {tensor_name} dtype",
            str(actual_tensor.dtype),
            str(expected_tensor.dtype),
        )
        expected = expected_tensor.detach().cpu().numpy()
        actual = actual_tensor.detach().cpu().numpy()
        if not np.isfinite(expected).all():
            raise ValueError(f"non-finite committed tensor: {tensor_name}")
        if not np.isfinite(actual).all():
            raise ValueError(f"non-finite retrained tensor: {tensor_name}")
        difference = np.abs(actual.astype(np.float64) - expected.astype(np.float64))
        max_error = max(max_error, float(difference.max(initial=0.0)))
        total_error += float(difference.sum())
        element_count += difference.size
    if max_error > tolerance:
        raise ValueError(f"retrained tensor state differs by more than {tolerance:g}")
    return {
        "comparison": f"absolute_tolerance_{tolerance:g}",
        "tensor_count": len(expected_state),
        "element_count": element_count,
        "max_absolute_error": round(max_error, 12),
        "mean_absolute_error": round(total_error / max(element_count, 1), 12),
    }


def _compare_numeric_replay(
    label: str,
    actual: Any,
    expected: Any,
    *,
    tolerance: float,
) -> dict[str, Any]:
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("numeric replay tolerance must be finite and positive")
    actual_values = np.asarray(actual, dtype=np.float64)
    expected_values = np.asarray(expected, dtype=np.float64)
    _require_equal(
        f"{label} shape", list(actual_values.shape), list(expected_values.shape)
    )
    if not np.isfinite(expected_values).all():
        raise ValueError(f"non-finite committed {label}")
    if not np.isfinite(actual_values).all():
        raise ValueError(f"non-finite retrained {label}")
    difference = np.abs(actual_values - expected_values)
    max_error = float(difference.max(initial=0.0))
    if max_error > tolerance:
        raise ValueError(f"retrained {label} differs by more than {tolerance:g}")
    return {
        "tolerance": tolerance,
        "max_absolute_error": round(max_error, 12),
        "mean_absolute_error": round(float(difference.mean()), 12),
    }


def _compare_metric_replay(label: str, actual: Any, expected: Any) -> dict[str, Any]:
    count_fields = ("tp", "fp", "fn", "tn")
    numeric_fields = (
        "f1",
        "iou",
        "mean_probability",
        "pixel_accuracy",
        "precision",
        "recall",
    )
    required = {*count_fields, *numeric_fields, "threshold"}
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        raise ValueError(f"{label} metrics must be objects")
    _require_equal(f"{label} metric keys", set(actual), required)
    _require_equal(f"committed {label} metric keys", set(expected), required)
    _require_equal(f"{label} threshold", actual["threshold"], expected["threshold"])
    count_errors: dict[str, int] = {}
    for field in count_fields:
        if type(actual[field]) is not int or type(expected[field]) is not int:
            raise ValueError(f"{label} {field} must be an integer")
        count_errors[field] = abs(actual[field] - expected[field])
        if count_errors[field] > RETRAINED_CONFUSION_ATOL:
            raise ValueError(
                f"retrained {label} {field} differs by more than "
                f"{RETRAINED_CONFUSION_ATOL}"
            )
    _require_equal(
        f"{label} positive population",
        actual["tp"] + actual["fn"],
        expected["tp"] + expected["fn"],
    )
    _require_equal(
        f"{label} negative population",
        actual["fp"] + actual["tn"],
        expected["fp"] + expected["tn"],
    )
    numeric = _compare_numeric_replay(
        f"{label} floating metrics",
        [actual[field] for field in numeric_fields],
        [expected[field] for field in numeric_fields],
        tolerance=RETRAINED_METRIC_ATOL,
    )
    return {
        "floating_metrics": numeric,
        "confusion_count_tolerance": RETRAINED_CONFUSION_ATOL,
        "confusion_count_errors": count_errors,
        "threshold": "exact",
    }


def _artifact_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("explanation artifact path is invalid")
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if resolved_root not in path.parents:
        raise ValueError("explanation artifact path escapes its root")
    return path


def verify_committed_public_demo(track_root: Path = TRACK_ROOT) -> dict[str, Any]:
    """Re-run inference and compare every committed public-demo contract."""
    from research.forest_xai.checkpoint import file_sha256
    from research.forest_xai.determinism import resolve_device
    from research.forest_xai.jsonio import load_json_object
    from research.forest_xai.public_data import (
        PUBLIC_FIXTURE_SCOPE,
        load_public_forest_fixture,
    )
    from research.forest_xai.public_training import (
        PUBLIC_CHECKPOINT_SCOPE,
        evaluate_public,
        explain_public,
        load_public_checkpoint,
    )

    track_root = track_root.resolve()
    fixture_root = track_root / "data" / "public_fixture"
    artifact_root = track_root / "artifacts" / "public_demo"
    checkpoint = artifact_root / "sentinel2_forest_cover.pt"
    explanation_root = artifact_root / "explanation"

    manifest = load_json_object(fixture_root / "manifest.json")
    training = load_public_forest_fixture(fixture_root, "train")
    evaluation = load_public_forest_fixture(fixture_root, "evaluation")
    _require_equal("fixture scope", manifest.get("scope"), PUBLIC_FIXTURE_SCOPE)
    _require_equal(
        "fixture claim boundary", manifest.get("claim_boundary"), EXPECTED_BOUNDARY
    )
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("public fixture source attribution is missing")
    _require_equal(
        "source DOI",
        source.get("original_doi"),
        "https://doi.org/10.5281/zenodo.4498086",
    )
    _require_equal("source license", source.get("license"), "CC BY 4.0")
    _require_equal(
        "source title",
        source.get("original_title"),
        "Amazon and Atlantic Forest image datasets for semantic segmentation",
    )
    _require_equal(
        "training image shape", tuple(training.images.shape), (24, 4, 64, 64)
    )
    _require_equal("training mask shape", tuple(training.masks.shape), (24, 1, 64, 64))
    _require_equal(
        "evaluation image shape", tuple(evaluation.images.shape), (12, 4, 64, 64)
    )
    _require_equal(
        "evaluation mask shape", tuple(evaluation.masks.shape), (12, 1, 64, 64)
    )
    train_scenes = set(training.metadata["source_scene_ids"])
    evaluation_scenes = set(evaluation.metadata["source_scene_ids"])
    if train_scenes & evaluation_scenes:
        raise ValueError("public fixture has scene leakage")
    if set(training.sample_ids) & set(evaluation.sample_ids):
        raise ValueError("public fixture has duplicate sample IDs across splits")

    committed_train = load_json_object(artifact_root / "train_result.json")
    committed_evaluation = load_json_object(artifact_root / "evaluation.json")
    committed_explanation = load_json_object(explanation_root / "explanation.json")
    sidecar = load_json_object(
        artifact_root / "sentinel2_forest_cover.pt.metadata.json"
    )
    _, loaded_sidecar = load_public_checkpoint(checkpoint, resolve_device("cpu"))
    _require_equal("checkpoint sidecar", loaded_sidecar, sidecar)
    _require_equal("checkpoint scope", sidecar.get("scope"), PUBLIC_CHECKPOINT_SCOPE)
    checkpoint_hash = file_sha256(checkpoint)
    _require_equal("checkpoint SHA", checkpoint_hash, sidecar.get("checkpoint_sha256"))
    _require_equal(
        "train result tensor-state SHA",
        committed_train.get("state_dict_sha256"),
        sidecar.get("state_dict_sha256"),
    )
    for label, document in (
        ("train result", committed_train),
        ("evaluation", committed_evaluation),
        ("explanation", committed_explanation),
    ):
        _require_equal(
            f"{label} checkpoint SHA",
            document.get("checkpoint_sha256"),
            checkpoint_hash,
        )
        if "claim_boundary" in document:
            _require_equal(
                f"{label} claim boundary",
                document.get("claim_boundary"),
                EXPECTED_BOUNDARY,
            )
    _require_equal(
        "sidecar evaluation metrics",
        sidecar["metadata"]["evaluation_metrics"],
        committed_evaluation["metrics"],
    )
    _require_equal(
        "train-result evaluation metrics",
        committed_train["evaluation_metrics"],
        committed_evaluation["metrics"],
    )

    with tempfile.TemporaryDirectory(prefix="forest-xai-public-verify-") as temporary:
        generated_root = Path(temporary)
        generated_evaluation = evaluate_public(
            fixture_root,
            checkpoint,
            generated_root / "evaluation.json",
            "cpu",
        )
        _require_equal(
            "checkpoint re-evaluation", generated_evaluation, committed_evaluation
        )
        try:
            sample_index = evaluation.sample_ids.index(
                committed_explanation["sample_id"]
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "committed explanation sample is not in evaluation split"
            ) from exc
        generated_explanation = explain_public(
            fixture_root,
            checkpoint,
            generated_root / "explanation",
            sample_index,
            "cpu",
        )
        _require_equal(
            "regenerated explanation", generated_explanation, committed_explanation
        )

        files = committed_explanation.get("files")
        if not isinstance(files, dict) or set(files) != {
            "rgb",
            "reference",
            "probability",
            "gradcam",
        }:
            raise ValueError("committed explanation file manifest is incomplete")
        for logical_name, entry in files.items():
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise ValueError(f"invalid explanation entry: {logical_name}")
            committed_path = _artifact_path(explanation_root, entry["path"])
            generated_path = _artifact_path(
                generated_root / "explanation", entry["path"]
            )
            _require_equal(
                f"committed {logical_name} SHA",
                file_sha256(committed_path),
                entry["sha256"],
            )
            _require_equal(
                f"regenerated {logical_name} SHA",
                file_sha256(generated_path),
                entry["sha256"],
            )

    return {
        "status": "verified",
        "scope": PUBLIC_FIXTURE_SCOPE,
        "checkpoint_sha256": checkpoint_hash,
        "training_shape": list(training.images.shape),
        "evaluation_shape": list(evaluation.images.shape),
        "training_scene_count": len(train_scenes),
        "evaluation_scene_count": len(evaluation_scenes),
        "scene_overlap": 0,
        "evaluation_metrics": committed_evaluation["metrics"],
        "explanation_sample_id": committed_explanation["sample_id"],
        "explanation_files_verified": len(committed_explanation["files"]),
        "claim_boundary": EXPECTED_BOUNDARY,
        "source_doi": source["original_doi"],
        "source_license": source["license"],
    }


def verify_retraining(track_root: Path, output_dir: Path) -> dict[str, Any]:
    """Repeat CPU training and compare invariant and bounded semantics."""
    import torch

    from research.forest_xai.determinism import resolve_device
    from research.forest_xai.jsonio import load_json_object
    from research.forest_xai.public_data import load_public_forest_fixture
    from research.forest_xai.public_training import (
        PublicTrainConfig,
        evaluate_public,
        load_public_checkpoint,
        train_public,
    )

    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("--retrain-output must be a new or empty directory")
    fixture_root = track_root / "data" / "public_fixture"
    result = train_public(
        fixture_root,
        output_dir,
        PublicTrainConfig(device="cpu"),
    )
    committed = load_json_object(
        track_root / "artifacts" / "public_demo" / "train_result.json"
    )
    variable_result_fields = {
        "checkpoint_sha256",
        "state_dict_sha256",
        "training_metrics",
        "evaluation_metrics",
    }
    _require_equal(
        "80-epoch retraining invariant result",
        {
            key: value
            for key, value in result.items()
            if key not in variable_result_fields
        },
        {
            key: value
            for key, value in committed.items()
            if key not in variable_result_fields
        },
    )
    training_metric_replay = _compare_metric_replay(
        "training", result["training_metrics"], committed["training_metrics"]
    )
    evaluation_metric_replay = _compare_metric_replay(
        "evaluation", result["evaluation_metrics"], committed["evaluation_metrics"]
    )
    retrained_checkpoint = output_dir / result["checkpoint"]
    retrained_model, retrained_sidecar = load_public_checkpoint(
        retrained_checkpoint, resolve_device("cpu")
    )
    committed_checkpoint = (
        track_root / "artifacts" / "public_demo" / "sentinel2_forest_cover.pt"
    )
    committed_model, committed_sidecar = load_public_checkpoint(
        committed_checkpoint, resolve_device("cpu")
    )
    state_replay = _compare_model_state_replay(committed_model, retrained_model)
    variable_metadata_fields = {
        "state_dict_sha256",
        "final_bce",
        "training_metrics",
        "evaluation_metrics",
    }
    _require_equal(
        "80-epoch retraining invariant metadata",
        {
            key: value
            for key, value in retrained_sidecar["metadata"].items()
            if key not in variable_metadata_fields
        },
        {
            key: value
            for key, value in committed_sidecar["metadata"].items()
            if key not in variable_metadata_fields
        },
    )
    _require_equal(
        "retrained training metric echo",
        retrained_sidecar["metadata"]["training_metrics"],
        result["training_metrics"],
    )
    _require_equal(
        "retrained evaluation metric echo",
        retrained_sidecar["metadata"]["evaluation_metrics"],
        result["evaluation_metrics"],
    )
    loss_replay = _compare_numeric_replay(
        "final BCE",
        retrained_sidecar["metadata"]["final_bce"],
        committed_sidecar["metadata"]["final_bce"],
        tolerance=RETRAINED_LOSS_ATOL,
    )

    training = load_public_forest_fixture(fixture_root, "train")
    evaluation = load_public_forest_fixture(fixture_root, "evaluation")
    mean = torch.tensor(committed_sidecar["metadata"]["normalization_mean"]).reshape(
        1, 4, 1, 1
    )
    std = torch.tensor(committed_sidecar["metadata"]["normalization_std"]).reshape(
        1, 4, 1, 1
    )

    def probability_map(model: Any, images: Any) -> np.ndarray:
        with torch.no_grad():
            return torch.sigmoid(model((images - mean) / std)).cpu().numpy()

    training_probability_replay = _compare_numeric_replay(
        "training probability map",
        probability_map(retrained_model, training.images),
        probability_map(committed_model, training.images),
        tolerance=RETRAINED_PROBABILITY_ATOL,
    )
    evaluation_probability_replay = _compare_numeric_replay(
        "evaluation probability map",
        probability_map(retrained_model, evaluation.images),
        probability_map(committed_model, evaluation.images),
        tolerance=RETRAINED_PROBABILITY_ATOL,
    )
    retrained_evaluation = evaluate_public(
        fixture_root,
        retrained_checkpoint,
        output_dir / "retrained_evaluation.json",
        "cpu",
    )
    committed_evaluation = load_json_object(
        track_root / "artifacts" / "public_demo" / "evaluation.json"
    )
    _require_equal(
        "retrained evaluation metric echo",
        retrained_evaluation["metrics"],
        result["evaluation_metrics"],
    )
    _require_equal(
        "80-epoch retraining invariant evaluation",
        {
            key: value
            for key, value in retrained_evaluation.items()
            if key not in {"checkpoint_sha256", "metrics"}
        },
        {
            key: value
            for key, value in committed_evaluation.items()
            if key not in {"checkpoint_sha256", "metrics"}
        },
    )
    return {
        "status": "immutable-metadata-and-bounded-numeric-semantics-verified",
        "committed_checkpoint_sha256": committed["checkpoint_sha256"],
        "retrained_checkpoint_sha256": result["checkpoint_sha256"],
        "committed_state_dict_sha256": committed["state_dict_sha256"],
        "retrained_state_dict_sha256": result["state_dict_sha256"],
        "state_replay": state_replay,
        "loss_replay": loss_replay,
        "training_metric_replay": training_metric_replay,
        "evaluation_metric_replay": evaluation_metric_replay,
        "training_probability_replay": training_probability_replay,
        "evaluation_probability_replay": evaluation_probability_replay,
        "epochs": 80,
        "device": "cpu",
        "checkpoint_container_note": (
            "each checkpoint and tensor state is hash-bound to its own sidecar; "
            "immutable metadata is exact; parameters, loss, probabilities, and "
            "derived metrics use documented measured tolerances across CPU kernels"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify committed public Sentinel-2 fixture hashes, model inference, "
            "and explanation artifacts."
        )
    )
    parser.add_argument(
        "--track-root",
        type=Path,
        default=TRACK_ROOT,
        help="forest_xai directory (defaults to the script's parent track)",
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="also repeat the deterministic 80-epoch CPU training",
    )
    parser.add_argument(
        "--retrain-output",
        type=Path,
        help="optional new/empty directory in which to keep retrained artifacts",
    )
    args = parser.parse_args()
    if args.retrain_output is not None and not args.retrain:
        parser.error("--retrain-output requires --retrain")

    track_root = args.track_root.resolve()
    result = verify_committed_public_demo(track_root)
    if args.retrain:
        context = (
            nullcontext(args.retrain_output.resolve())
            if args.retrain_output is not None
            else tempfile.TemporaryDirectory(prefix="forest-xai-public-retrain-")
        )
        with context as destination:
            result["retraining"] = verify_retraining(track_root, Path(destination))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
