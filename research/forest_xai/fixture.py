"""Deterministic, explicitly synthetic multispectral smoke-test fixture."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np
import torch


CHANNEL_NAMES = ("red", "green", "nir", "swir")
FIXTURE_SCOPE = "synthetic_smoke_test_not_real_satellite_data"


@dataclass(frozen=True)
class SyntheticBatch:
    before: torch.Tensor
    after: torch.Tensor
    mask: torch.Tensor
    sample_ids: tuple[str, ...]
    metadata: dict[str, object]


def _tensor_bytes(tensor: torch.Tensor) -> bytes:
    return tensor.detach().cpu().contiguous().numpy().tobytes(order="C")


def fixture_sha256(batch: SyntheticBatch) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(batch.metadata, sort_keys=True).encode("utf-8"))
    for name, tensor in (
        ("before", batch.before),
        ("after", batch.after),
        ("mask", batch.mask),
    ):
        digest.update(name.encode("ascii"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(_tensor_bytes(tensor))
    digest.update("\n".join(batch.sample_ids).encode("utf-8"))
    return digest.hexdigest()


def make_synthetic_batch(
    *, samples: int = 24, image_size: int = 16, seed: int = 20260812, split: str
) -> SyntheticBatch:
    """Create easy-to-audit paired arrays with rectangular synthetic loss patches."""
    if samples < 2:
        raise ValueError("samples must be at least 2")
    if image_size < 12 or image_size % 4:
        raise ValueError("image_size must be >= 12 and divisible by 4")
    if split not in {"train", "evaluation"}:
        raise ValueError("split must be train or evaluation")

    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:image_size, 0:image_size].astype(np.float32)
    xx /= image_size - 1
    yy /= image_size - 1
    before = np.empty((samples, 4, image_size, image_size), dtype=np.float32)
    after = np.empty_like(before)
    mask = np.zeros((samples, 1, image_size, image_size), dtype=np.float32)

    for index in range(samples):
        phase = np.float32(index * 0.17)
        texture = np.sin((xx + phase) * np.pi * 2) * np.cos((yy - phase) * np.pi)
        noise = rng.normal(0.0, 0.008, size=(4, image_size, image_size)).astype(
            np.float32
        )
        base = np.stack(
            (
                0.19 + 0.025 * texture,
                0.36 + 0.035 * texture,
                0.72 + 0.045 * texture,
                0.24 - 0.020 * texture,
            )
        ).astype(np.float32)
        before[index] = np.clip(base + noise, 0.0, 1.0)
        after_noise = rng.normal(0.0, 0.006, size=(4, image_size, image_size)).astype(
            np.float32
        )
        after[index] = np.clip(before[index] + after_noise, 0.0, 1.0)

        # Alternate positives and hard negatives to keep the sample-level
        # classifier balanced while preserving normal-noise negatives.
        if index % 2:
            height = 3 + index % 4
            width = 3 + (index * 3) % 4
            top = 1 + (index * 5) % (image_size - height - 1)
            left = 1 + (index * 7) % (image_size - width - 1)
            region = np.s_[top : top + height, left : left + width]
            mask[index, 0, region[0], region[1]] = 1.0
            after[index, 0, region[0], region[1]] += 0.24  # red increases
            after[index, 1, region[0], region[1]] -= 0.14  # green decreases
            after[index, 2, region[0], region[1]] -= 0.38  # NIR decreases
            after[index, 3, region[0], region[1]] += 0.22  # SWIR increases
            after[index] = np.clip(after[index], 0.0, 1.0)

    split_prefix = "TR" if split == "train" else "EV"
    sample_ids = tuple(f"SYN-{split_prefix}-{index:03d}" for index in range(samples))
    metadata: dict[str, object] = {
        "schema_version": "forest-xai-synthetic-fixture/1.0",
        "scope": FIXTURE_SCOPE,
        "split": split,
        "seed": seed,
        "samples": samples,
        "image_size": image_size,
        "channels": list(CHANNEL_NAMES),
        "change_pattern": "rectangular spectral shift on odd samples; even samples are negative",
        "real_satellite_data": False,
        "real_world_accuracy_claim": False,
    }
    return SyntheticBatch(
        before=torch.from_numpy(before),
        after=torch.from_numpy(after),
        mask=torch.from_numpy(mask),
        sample_ids=sample_ids,
        metadata=metadata,
    )
