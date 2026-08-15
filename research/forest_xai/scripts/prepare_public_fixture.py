#!/usr/bin/env python3
"""Rebuild the small public Sentinel-2 fixture from pinned Parquet shards."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

import numpy as np

SOURCES = {
    "train": {
        "url": "https://huggingface.co/datasets/NickBurns/amazon-sentinel2-forest-segmentation/resolve/516251c601e1d2fe579f8e2d15589140f94383b9/data/train-00000-of-00004.parquet",
        "sha256": "20cc1ba67d019602c7292b9ccf65fb34df344e96bad1e9208afac3d79cb18847",
        "rows": list(range(12)) + list(range(93, 105)),
    },
    "evaluation": {
        "url": "https://huggingface.co/datasets/NickBurns/amazon-sentinel2-forest-segmentation/resolve/516251c601e1d2fe579f8e2d15589140f94383b9/data/val-00000-of-00001.parquet",
        "sha256": "af8228317cfea898c0b3595bd1458861862214ff31f1aafdc39011415b559d10",
        "rows": list(range(20, 26)) + list(range(43, 49)),
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_hash: str) -> None:
    if destination.is_file() and sha256(destination) == expected_hash:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        urllib.request.urlopen(url, timeout=120) as response,
        destination.open("wb") as output,
    ):
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if sha256(destination) != expected_hash:
        destination.unlink(missing_ok=True)
        raise ValueError(f"downloaded shard hash mismatch: {destination.name}")


def downsample_image(image: np.ndarray) -> np.ndarray:
    if image.shape != (4, 512, 512):
        raise ValueError(f"unexpected source image shape: {image.shape}")
    # Sentinel-2 L2A digital numbers are stored as signed integers in this
    # mirror.  Use one fixed physical-domain scale, never split statistics.
    reflectance = np.clip(image.astype(np.float32) / 10_000.0, 0.0, 1.0)
    return reflectance.reshape(4, 64, 8, 64, 8).mean(axis=(2, 4), dtype=np.float32)


def downsample_mask(mask: np.ndarray) -> np.ndarray:
    if mask.shape != (512, 512) or not np.isin(mask, [0, 1]).all():
        raise ValueError("unexpected source mask contract")
    coverage = mask.reshape(64, 8, 64, 8).mean(axis=(1, 3))
    return (coverage >= 0.5).astype(np.float32)[None, ...]


def scene_id(filename: str) -> str:
    parts = filename.split("_")
    if len(parts) < 3:
        raise ValueError(f"unexpected source filename: {filename}")
    return "_".join(parts[:-2])


def save_npy(path: Path, array: np.ndarray) -> dict[str, object]:
    np.save(path, array, allow_pickle=False)
    return {
        "path": path.name,
        "sha256": sha256(path),
        "dtype": str(array.dtype),
        "shape": list(array.shape),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SystemExit("fixture preparation requires pyarrow==23.0.1") from exc

    args.output.mkdir(parents=True, exist_ok=True)
    file_entries: dict[str, object] = {}
    split_entries: dict[str, object] = {}
    for split, source in SOURCES.items():
        shard = args.cache / f"{split}.parquet"
        download(source["url"], shard, source["sha256"])
        table = parquet.read_table(shard, columns=["image", "label", "filename"])
        images: list[np.ndarray] = []
        masks: list[np.ndarray] = []
        filenames: list[str] = []
        for row in source["rows"]:
            image = np.asarray(table["image"][row].as_py())
            mask = np.asarray(table["label"][row].as_py())
            images.append(downsample_image(image))
            masks.append(downsample_mask(mask))
            filenames.append(table["filename"][row].as_py())
        image_array = np.stack(images).astype(np.float32)
        mask_array = np.stack(masks).astype(np.float32)
        file_entries[f"{split}_images"] = save_npy(
            args.output / f"{split}_images.npy", image_array
        )
        file_entries[f"{split}_masks"] = save_npy(
            args.output / f"{split}_masks.npy", mask_array
        )
        split_entries[split] = {
            "sample_ids": [
                f"S2-{split[:2].upper()}-{index:03d}" for index in range(len(images))
            ],
            "source_filenames": filenames,
            "source_scene_ids": sorted({scene_id(name) for name in filenames}),
        }

    train_scenes = set(split_entries["train"]["source_scene_ids"])
    evaluation_scenes = set(split_entries["evaluation"]["source_scene_ids"])
    if train_scenes & evaluation_scenes:
        raise ValueError("scene leakage between train and evaluation fixture")
    manifest = {
        "schema_version": "forest-xai-public-fixture/1.0",
        "scope": "public_sentinel2_forest_cover_research_fixture",
        "source": {
            "original_doi": "https://doi.org/10.5281/zenodo.4498086",
            "original_title": "Amazon and Atlantic Forest image datasets for semantic segmentation",
            "authors": [
                "Lucimara Bragagnolo",
                "Roberto Valmir da Silva",
                "Jose Mario Vicensi Grzybowski",
            ],
            "license": "CC BY 4.0",
            "machine_readable_mirror": "https://huggingface.co/datasets/NickBurns/amazon-sentinel2-forest-segmentation",
            "machine_readable_mirror_commit": "516251c601e1d2fe579f8e2d15589140f94383b9",
            "source_shards": SOURCES,
        },
        "derivation": {
            "input": "Sentinel-2 L2A B4/B3/B2/B8 chips and binary forest masks",
            "source_shape": [4, 512, 512],
            "committed_shape": [4, 64, 64],
            "image_operation": "clip(DN / 10000, 0, 1), then non-overlapping 8x8 mean",
            "mask_operation": "non-overlapping 8x8 forest coverage >= 0.5",
            "split_policy": "source scene IDs are disjoint between train and evaluation",
        },
        "files": file_entries,
        "splits": split_entries,
        "claim_boundary": {
            "real_public_satellite_pixels": True,
            "forest_cover_segmentation": True,
            "bi_temporal_change_detection": False,
            "deforestation_cause_or_legality": False,
            "external_independent_benchmark": False,
            "purpose": "small CPU-reproducible capability demonstration, not field validation",
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
