#!/usr/bin/env python3
"""Verify the committed post-award GAN and 2.5D reconstruction artifacts."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

import numpy as np
from PIL import Image


TRACK_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TRACK_ROOT.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _require_equal(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ValueError(f"{label} differs from the committed contract")


def _compare_png_replay(reference: Path, candidate: Path) -> dict[str, Any]:
    """Compare decoded pixels while allowing negligible CPU-kernel rounding."""
    with Image.open(reference) as image:
        expected = np.asarray(image.convert("RGB"), dtype=np.int16)
    with Image.open(candidate) as image:
        actual = np.asarray(image.convert("RGB"), dtype=np.int16)
    _require_equal("replayed PNG shape", list(actual.shape), list(expected.shape))
    difference = np.abs(actual - expected)
    metrics = {
        "max_channel_error": int(difference.max(initial=0)),
        "mean_absolute_error": round(float(difference.mean()), 8),
    }
    if metrics["max_channel_error"] > 2:
        raise ValueError("replayed PNG differs by more than 2/255 in one channel")
    return metrics


def _artifact_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("reconstruction artifact path is invalid")
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if resolved_root not in path.parents:
        raise ValueError("reconstruction artifact path escapes its root")
    return path


def _verify_file_entry(
    root: Path,
    logical_name: str,
    entry: Any,
    *,
    array: bool,
) -> Path:
    from research.forest_xai.checkpoint import file_sha256

    required = {"path", "sha256", "shape", "dtype"} if array else {"path", "sha256"}
    if not isinstance(entry, dict) or set(entry) != required:
        raise ValueError(f"invalid reconstruction file entry: {logical_name}")
    path = _artifact_path(root, entry["path"])
    if not path.is_file() or file_sha256(path) != entry["sha256"]:
        raise ValueError(f"reconstruction file SHA mismatch: {logical_name}")
    if array:
        values = np.load(path, allow_pickle=False)
        _require_equal(f"{logical_name} shape", list(values.shape), entry["shape"])
        _require_equal(f"{logical_name} dtype", str(values.dtype), entry["dtype"])
        if not np.isfinite(values).all():
            raise ValueError(f"non-finite reconstruction array: {logical_name}")
    return path


def _verify_machine_geometry(root: Path, terrain: dict[str, Any]) -> None:
    files = terrain["files"]
    height = np.load(_artifact_path(root, files["height"]["path"]), allow_pickle=False)
    probability = np.load(
        _artifact_path(root, files["probability"]["path"]), allow_pickle=False
    )
    vertices = np.load(
        _artifact_path(root, files["vertices"]["path"]), allow_pickle=False
    )
    faces = np.load(_artifact_path(root, files["faces"]["path"]), allow_pickle=False)
    if not (0 <= height).all() or not (height <= 1).all():
        raise ValueError("synthetic terrain height is outside [0, 1]")
    if not (0 <= probability).all() or not (probability <= 1).all():
        raise ValueError("forest probability is outside [0, 1]")
    if not (0 <= vertices).all() or not (vertices <= 1).all():
        raise ValueError("terrain vertices are outside normalized coordinates")
    if faces.min() < 0 or faces.max() >= vertices.shape[0] * vertices.shape[1]:
        raise ValueError("terrain face index is outside the vertex array")
    _require_equal(
        "terrain probability mean",
        round(float(probability.mean()), 6),
        terrain["mean_forest_probability"],
    )
    mesh = terrain["mesh"]
    _require_equal("terrain mesh grid", mesh["grid_size"], vertices.shape[0])
    _require_equal(
        "terrain vertex count",
        mesh["vertex_count"],
        vertices.shape[0] * vertices.shape[1],
    )
    _require_equal("terrain face count", mesh["face_count"], faces.shape[0])


def verify_committed_reconstruction(
    track_root: Path = TRACK_ROOT,
) -> dict[str, Any]:
    """Regenerate every derived artifact and compare the committed contract."""
    from research.forest_xai.determinism import resolve_device
    from research.forest_xai.jsonio import load_json_object
    from research.forest_xai.reconstruction import (
        RECONSTRUCTION_CLAIM_BOUNDARY,
        RECONSTRUCTION_SCOPE,
        LatentInterpolationConfig,
        ReliefDrapeConfig,
        interpolate_latent_path,
        load_latent_gan,
        render_relief_drape,
    )

    track_root = track_root.resolve()
    fixture_root = track_root / "data" / "public_fixture"
    artifact_root = track_root / "artifacts" / "public_demo"
    reconstruction_root = artifact_root / "reconstruction"
    gan_checkpoint = reconstruction_root / "latent_gan.pt"
    classifier_checkpoint = artifact_root / "sentinel2_forest_cover.pt"
    latent = load_json_object(reconstruction_root / "latent_interpolation.json")
    terrain = load_json_object(reconstruction_root / "terrain_drape.json")
    _, _, gan_sidecar = load_latent_gan(gan_checkpoint, resolve_device("cpu"))

    _require_equal(
        "latent JSON keys",
        set(latent),
        {
            "schema_version",
            "scope",
            "claim_boundary",
            "method_label",
            "gan_checkpoint_sha256",
            "classifier_checkpoint_sha256",
            "seed",
            "frames",
            "alphas",
            "forest_probabilities",
            "jvp",
            "files",
        },
    )
    _require_equal(
        "terrain JSON keys",
        set(terrain),
        {
            "schema_version",
            "scope",
            "claim_boundary",
            "method_label",
            "classifier_checkpoint_sha256",
            "evaluation_fixture_sha256",
            "sample_id",
            "sample_index",
            "seed",
            "height_grid_size",
            "vertical_scale",
            "height_generation",
            "mean_forest_probability",
            "mesh",
            "files",
        },
    )
    _require_equal("latent scope", latent["scope"], RECONSTRUCTION_SCOPE)
    _require_equal("terrain scope", terrain["scope"], RECONSTRUCTION_SCOPE)
    _require_equal(
        "GAN checkpoint binding",
        latent["gan_checkpoint_sha256"],
        gan_sidecar["checkpoint_sha256"],
    )
    _require_equal(
        "GAN claim boundary",
        gan_sidecar["metadata"]["claim_boundary"],
        RECONSTRUCTION_CLAIM_BOUNDARY,
    )
    _require_equal(
        "latent claim boundary",
        latent["claim_boundary"],
        {
            **RECONSTRUCTION_CLAIM_BOUNDARY,
            "real_public_satellite_training_pixels": True,
        },
    )
    _require_equal(
        "terrain claim boundary",
        terrain["claim_boundary"],
        {
            **RECONSTRUCTION_CLAIM_BOUNDARY,
            "synthetic_height_field": True,
            "not_satellite_derived_elevation": True,
            "bilinear_height_interpolation": True,
            "renders_committed_model_probability": True,
        },
    )
    if set(latent["files"]) != {"contact_sheet"}:
        raise ValueError("latent contact-sheet manifest is incomplete")
    committed_contact_sheet = _verify_file_entry(
        reconstruction_root,
        "contact_sheet",
        latent["files"]["contact_sheet"],
        array=False,
    )
    if set(terrain["files"]) != {
        "drape",
        "height",
        "probability",
        "vertices",
        "faces",
    }:
        raise ValueError("terrain file manifest is incomplete")
    _verify_file_entry(
        reconstruction_root, "drape", terrain["files"]["drape"], array=False
    )
    for name in ("height", "probability", "vertices", "faces"):
        _verify_file_entry(
            reconstruction_root, name, terrain["files"][name], array=True
        )
    _verify_machine_geometry(reconstruction_root, terrain)

    with tempfile.TemporaryDirectory(
        prefix="forest-xai-reconstruction-verify-"
    ) as temporary:
        generated_root = Path(temporary)
        generated_latent = interpolate_latent_path(
            gan_checkpoint,
            classifier_checkpoint,
            generated_root,
            LatentInterpolationConfig(seed=latent["seed"], frames=latent["frames"]),
        )
        _require_equal(
            "regenerated latent semantics",
            {key: value for key, value in generated_latent.items() if key != "files"},
            {key: value for key, value in latent.items() if key != "files"},
        )
        _require_equal(
            "regenerated contact-sheet path",
            generated_latent["files"]["contact_sheet"]["path"],
            latent["files"]["contact_sheet"]["path"],
        )
        latent_image_replay = _compare_png_replay(
            committed_contact_sheet,
            _artifact_path(
                generated_root,
                generated_latent["files"]["contact_sheet"]["path"],
            ),
        )
        generated_terrain = render_relief_drape(
            fixture_root,
            classifier_checkpoint,
            generated_root,
            ReliefDrapeConfig(
                seed=terrain["seed"],
                sample_index=terrain["sample_index"],
                height_grid_size=terrain["height_grid_size"],
                vertical_scale=terrain["vertical_scale"],
            ),
        )
        _require_equal("regenerated terrain result", generated_terrain, terrain)
        for name, entry in terrain["files"].items():
            generated_path = _artifact_path(generated_root, entry["path"])
            from research.forest_xai.checkpoint import file_sha256

            _require_equal(
                f"regenerated {name} SHA",
                file_sha256(generated_path),
                entry["sha256"],
            )

    return {
        "status": "verified",
        "scope": RECONSTRUCTION_SCOPE,
        "gan_checkpoint_sha256": gan_sidecar["checkpoint_sha256"],
        "gan_state_dict_sha256": gan_sidecar["state_dict_sha256"],
        "latent_frames": latent["frames"],
        "unit_path_jvp": latent["jvp"]["unit_path_direction_derivative"],
        "latent_contact_sheet_replay": latent_image_replay,
        "terrain_sample_id": terrain["sample_id"],
        "terrain_files_verified": len(terrain["files"]),
        "mesh": terrain["mesh"],
        "claim_boundary": RECONSTRUCTION_CLAIM_BOUNDARY,
    }


def verify_retraining(track_root: Path, output_dir: Path) -> dict[str, Any]:
    """Repeat the 120-epoch CPU GAN training and compare tensor-derived results."""
    from research.forest_xai.determinism import resolve_device
    from research.forest_xai.jsonio import load_json_object
    from research.forest_xai.reconstruction import (
        LatentGanConfig,
        LatentInterpolationConfig,
        interpolate_latent_path,
        load_latent_gan,
        train_latent_gan,
    )

    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("--retrain-output must be a new or empty directory")
    fixture_root = track_root / "data" / "public_fixture"
    artifact_root = track_root / "artifacts" / "public_demo"
    reconstruction_root = artifact_root / "reconstruction"
    committed_sidecar = load_json_object(
        reconstruction_root / "latent_gan.pt.metadata.json"
    )
    committed_latent = load_json_object(
        reconstruction_root / "latent_interpolation.json"
    )
    result = train_latent_gan(fixture_root, output_dir, LatentGanConfig(device="cpu"))
    retrained_checkpoint = output_dir / result["checkpoint"]
    _, _, retrained_sidecar = load_latent_gan(
        retrained_checkpoint, resolve_device("cpu")
    )
    _require_equal(
        "retrained tensor state",
        retrained_sidecar["state_dict_sha256"],
        committed_sidecar["state_dict_sha256"],
    )
    _require_equal(
        "retrained metadata",
        retrained_sidecar["metadata"],
        committed_sidecar["metadata"],
    )
    regenerated = interpolate_latent_path(
        retrained_checkpoint,
        artifact_root / "sentinel2_forest_cover.pt",
        output_dir / "derived",
        LatentInterpolationConfig(
            seed=committed_latent["seed"], frames=committed_latent["frames"]
        ),
    )
    _require_equal(
        "retrained latent semantics",
        {
            key: value
            for key, value in regenerated.items()
            if key not in {"gan_checkpoint_sha256", "files"}
        },
        {
            key: value
            for key, value in committed_latent.items()
            if key not in {"gan_checkpoint_sha256", "files"}
        },
    )
    image_replay = _compare_png_replay(
        reconstruction_root / committed_latent["files"]["contact_sheet"]["path"],
        output_dir / "derived" / regenerated["files"]["contact_sheet"]["path"],
    )
    return {
        "status": "state-metadata-semantics-identical",
        "committed_checkpoint_sha256": committed_sidecar["checkpoint_sha256"],
        "retrained_checkpoint_sha256": retrained_sidecar["checkpoint_sha256"],
        "state_dict_sha256": result["state_dict_sha256"],
        "epochs": 120,
        "device": "cpu",
        "latent_contact_sheet_replay": image_replay,
        "checkpoint_container_note": (
            "torch.save container bytes may differ; each file must match its own "
            "sidecar; tensor state, metadata, and numeric semantics are exact while "
            "the decoded contact sheet allows at most 2/255 channel error across CPU kernels"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the post-award latent GAN and synthetic-height 2.5D artifacts."
    )
    parser.add_argument("--track-root", type=Path, default=TRACK_ROOT)
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="also repeat the deterministic 120-epoch CPU GAN training",
    )
    parser.add_argument("--retrain-output", type=Path)
    args = parser.parse_args()
    if args.retrain_output is not None and not args.retrain:
        parser.error("--retrain-output requires --retrain")
    track_root = args.track_root.resolve()
    result = verify_committed_reconstruction(track_root)
    if args.retrain:
        context = (
            nullcontext(args.retrain_output.resolve())
            if args.retrain_output is not None
            else tempfile.TemporaryDirectory(
                prefix="forest-xai-reconstruction-retrain-"
            )
        )
        with context as destination:
            result["retraining"] = verify_retraining(track_root, Path(destination))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
