"""Tamper-evident checkpoint serialization for the optional research models."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import torch

from .models import (
    LatentEncoder,
    LatentGenerator,
    LatentScoreClassifier,
    TinyChangeSegmenter,
)
from .jsonio import load_json_object


CHECKPOINT_SCOPE = "synthetic_smoke_test_not_real_satellite_model"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_dict_sha256(state_dicts: Mapping[str, Mapping[str, torch.Tensor]]) -> str:
    """Hash names, shapes, dtypes, and canonical CPU tensor bytes."""
    digest = hashlib.sha256()
    for group_name in sorted(state_dicts):
        for tensor_name in sorted(state_dicts[group_name]):
            tensor = state_dicts[group_name][tensor_name].detach().cpu().contiguous()
            descriptor = {
                "group": group_name,
                "name": tensor_name,
                "shape": list(tensor.shape),
                "dtype": str(tensor.dtype),
            }
            digest.update(json.dumps(descriptor, sort_keys=True).encode("utf-8"))
            digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def sidecar_path(checkpoint: Path) -> Path:
    return checkpoint.with_name(f"{checkpoint.name}.metadata.json")


def save_checkpoint(
    checkpoint: Path,
    *,
    segmenter: TinyChangeSegmenter,
    encoder: LatentEncoder,
    generator: LatentGenerator,
    latent_classifier: LatentScoreClassifier,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    state_dicts = {
        "segmenter": segmenter.state_dict(),
        "encoder": encoder.state_dict(),
        "generator": generator.state_dict(),
        "latent_classifier": latent_classifier.state_dict(),
    }
    state_hash = state_dict_sha256(state_dicts)
    payload = {
        "schema_version": "forest-xai-checkpoint/1.0",
        "scope": CHECKPOINT_SCOPE,
        "architecture": {
            "channels": segmenter.channels,
            "segmenter_width": segmenter.width,
            "latent_width": encoder.width,
            "latent_dim": encoder.latent_dim,
            "latent_classifier_width": latent_classifier.width,
            "image_size": encoder.image_size,
        },
        "metadata": {**metadata, "state_dict_sha256": state_hash},
        "state_dicts": state_dicts,
    }
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    checkpoint.write_bytes(buffer.getvalue())
    checkpoint_hash = file_sha256(checkpoint)
    sidecar = {
        "schema_version": "forest-xai-checkpoint-metadata/1.0",
        "scope": CHECKPOINT_SCOPE,
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": checkpoint_hash,
        "state_dict_sha256": state_hash,
        "metadata": payload["metadata"],
    }
    sidecar_path(checkpoint).write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return sidecar


def load_checkpoint(checkpoint: Path, *, device: torch.device) -> tuple[
    TinyChangeSegmenter,
    LatentEncoder,
    LatentGenerator,
    LatentScoreClassifier,
    dict[str, Any],
]:
    metadata_path = sidecar_path(checkpoint)
    if not checkpoint.is_file() or not metadata_path.is_file():
        raise ValueError("checkpoint and checkpoint metadata sidecar are both required")
    sidecar = load_json_object(metadata_path)
    if (
        set(sidecar)
        != {
            "schema_version",
            "scope",
            "checkpoint_file",
            "checkpoint_sha256",
            "state_dict_sha256",
            "metadata",
        }
        or sidecar.get("checkpoint_file") != checkpoint.name
    ):
        raise ValueError("checkpoint metadata sidecar contract is invalid")
    actual_hash = file_sha256(checkpoint)
    if actual_hash != sidecar.get("checkpoint_sha256"):
        raise ValueError("checkpoint SHA-256 does not match metadata sidecar")

    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if payload.get("schema_version") != "forest-xai-checkpoint/1.0":
        raise ValueError("unsupported checkpoint schema")
    if (
        payload.get("scope") != CHECKPOINT_SCOPE
        or sidecar.get("scope") != CHECKPOINT_SCOPE
    ):
        raise ValueError("checkpoint is not labeled as the synthetic research scope")
    if payload.get("metadata") != sidecar.get("metadata"):
        raise ValueError("checkpoint metadata differs from the embedded metadata")
    state_hash = state_dict_sha256(payload["state_dicts"])
    expected_state_hashes = {
        sidecar.get("state_dict_sha256"),
        payload.get("metadata", {}).get("state_dict_sha256"),
    }
    if expected_state_hashes != {state_hash}:
        raise ValueError("checkpoint tensor hash does not match embedded metadata")

    architecture = payload["architecture"]
    segmenter = TinyChangeSegmenter(
        channels=architecture["channels"], width=architecture["segmenter_width"]
    )
    common = {
        "channels": architecture["channels"],
        "width": architecture["latent_width"],
        "latent_dim": architecture["latent_dim"],
        "image_size": architecture["image_size"],
    }
    encoder = LatentEncoder(**common)
    generator = LatentGenerator(**common)
    latent_classifier = LatentScoreClassifier(
        latent_dim=architecture["latent_dim"],
        width=architecture["latent_classifier_width"],
    )
    segmenter.load_state_dict(payload["state_dicts"]["segmenter"])
    encoder.load_state_dict(payload["state_dicts"]["encoder"])
    generator.load_state_dict(payload["state_dicts"]["generator"])
    latent_classifier.load_state_dict(payload["state_dicts"]["latent_classifier"])
    for model in (segmenter, encoder, generator, latent_classifier):
        model.to(device).eval()
    return segmenter, encoder, generator, latent_classifier, sidecar
