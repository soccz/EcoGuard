"""Strict loader for the small, attributed public Sentinel-2 fixture.

This module deliberately lives outside :mod:`ecoguard`.  The release package
keeps its dependency-free runtime while this optional research track uses
NumPy and PyTorch to demonstrate a real satellite-data boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np
import torch

from .jsonio import load_json_object


PUBLIC_FIXTURE_SCOPE = "public_sentinel2_forest_cover_research_fixture"
EXPECTED_MANIFEST_KEYS = {
    "schema_version",
    "scope",
    "source",
    "derivation",
    "files",
    "splits",
    "claim_boundary",
}


@dataclass(frozen=True)
class PublicForestBatch:
    """A scene-separated split of real Sentinel-2 image chips and masks."""

    images: torch.Tensor
    masks: torch.Tensor
    sample_ids: tuple[str, ...]
    source_filenames: tuple[str, ...]
    split: str
    metadata: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    payload = load_json_object(path)
    if set(payload) != EXPECTED_MANIFEST_KEYS:
        raise ValueError("public fixture manifest has an unexpected top-level shape")
    if payload["schema_version"] != "forest-xai-public-fixture/1.0":
        raise ValueError("unsupported public fixture schema_version")
    if payload["scope"] != PUBLIC_FIXTURE_SCOPE:
        raise ValueError("public fixture scope disagrees with the loader")
    return payload


def _load_array(root: Path, files: dict[str, object], logical_name: str) -> np.ndarray:
    entry = files.get(logical_name)
    if not isinstance(entry, dict) or set(entry) != {
        "path",
        "sha256",
        "dtype",
        "shape",
    }:
        raise ValueError(f"invalid file entry: {logical_name}")
    relative = entry["path"]
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"invalid fixture path: {logical_name}")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"fixture path escapes its root: {logical_name}")
    if not path.is_file() or _sha256(path) != entry["sha256"]:
        raise ValueError(f"fixture hash mismatch: {logical_name}")
    array = np.load(path, allow_pickle=False)
    if str(array.dtype) != entry["dtype"] or list(array.shape) != entry["shape"]:
        raise ValueError(f"fixture array contract mismatch: {logical_name}")
    if not np.isfinite(array).all():
        raise ValueError(f"fixture contains non-finite values: {logical_name}")
    return array


def load_public_forest_fixture(root: Path, split: str) -> PublicForestBatch:
    """Load and hash-check a committed ``train`` or ``evaluation`` split.

    The fixture contains actual public Sentinel-2 chips, but it is a compact
    *forest-cover* segmentation sample.  It is not a bi-temporal forest-loss
    benchmark and must never be reported as one.
    """

    if split not in {"train", "evaluation"}:
        raise ValueError("split must be train or evaluation")
    root = root.resolve()
    manifest = _load_manifest(root / "manifest.json")
    files = manifest["files"]
    splits = manifest["splits"]
    if not isinstance(files, dict) or not isinstance(splits, dict):
        raise ValueError("public fixture files/splits must be objects")
    split_metadata = splits.get(split)
    if not isinstance(split_metadata, dict) or set(split_metadata) != {
        "sample_ids",
        "source_filenames",
        "source_scene_ids",
    }:
        raise ValueError(f"invalid split metadata: {split}")
    images = _load_array(root, files, f"{split}_images")
    masks = _load_array(root, files, f"{split}_masks")
    if images.ndim != 4 or images.shape[1:] != (4, 64, 64):
        raise ValueError("public fixture images must be [N,4,64,64]")
    if masks.shape != (images.shape[0], 1, 64, 64):
        raise ValueError("public fixture masks must be [N,1,64,64]")
    if images.min() < 0 or images.max() > 1 or not np.isin(masks, [0, 1]).all():
        raise ValueError("public fixture values are outside their declared ranges")
    sample_ids = split_metadata["sample_ids"]
    filenames = split_metadata["source_filenames"]
    scenes = split_metadata["source_scene_ids"]
    if not all(isinstance(values, list) for values in (sample_ids, filenames, scenes)):
        raise ValueError("public fixture split lists are malformed")
    if len(sample_ids) != images.shape[0] or len(filenames) != images.shape[0]:
        raise ValueError("public fixture split metadata count mismatch")
    if len(set(sample_ids)) != len(sample_ids) or not scenes:
        raise ValueError("public fixture sample IDs/scenes are invalid")
    return PublicForestBatch(
        images=torch.from_numpy(images.copy()),
        masks=torch.from_numpy(masks.copy()),
        sample_ids=tuple(sample_ids),
        source_filenames=tuple(filenames),
        split=split,
        metadata={
            "scope": manifest["scope"],
            "source": manifest["source"],
            "derivation": manifest["derivation"],
            "source_scene_ids": scenes,
            "claim_boundary": manifest["claim_boundary"],
        },
    )
