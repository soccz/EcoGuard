"""Train, verify, and explain the small public Sentinel-2 forest model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import torch
from torch import nn

from .checkpoint import file_sha256, state_dict_sha256
from .determinism import configure_determinism, resolve_device
from .explain import gradcam_from_feature_map
from .jsonio import load_json_object
from .models import TinyForestCoverSegmenter
from .public_data import (
    PUBLIC_FIXTURE_SCOPE,
    PublicForestBatch,
    load_public_forest_fixture,
)

PUBLIC_CHECKPOINT_SCOPE = "public_sentinel2_forest_cover_research_model"


@dataclass(frozen=True)
class PublicTrainConfig:
    seed: int = 20260812
    device: str = "cpu"
    epochs: int = 80
    learning_rate: float = 0.02
    width: int = 16

    def validate(self) -> None:
        if self.epochs < 1 or self.epochs > 2_000:
            raise ValueError("epochs must be between 1 and 2000")
        if not 0 < self.learning_rate <= 1:
            raise ValueError("learning_rate must be in (0, 1]")
        if self.width < 4 or self.width > 256:
            raise ValueError("width must be between 4 and 256")


def _normalization(batch: PublicForestBatch) -> tuple[torch.Tensor, torch.Tensor]:
    mean = batch.images.mean(dim=(0, 2, 3), keepdim=True)
    std = batch.images.std(dim=(0, 2, 3), keepdim=True).clamp_min(1e-6)
    return mean, std


def _normalize(
    images: torch.Tensor, mean: torch.Tensor, std: torch.Tensor
) -> torch.Tensor:
    return (images - mean.to(images.device)) / std.to(images.device)


def _metrics(
    logits: torch.Tensor, target: torch.Tensor, threshold: float
) -> dict[str, Any]:
    if logits.shape != target.shape or not 0 < threshold < 1:
        raise ValueError("public metric inputs are invalid")
    probability = torch.sigmoid(logits)
    predicted = probability >= threshold
    expected = target >= 0.5
    tp = int(torch.logical_and(predicted, expected).sum().item())
    fp = int(torch.logical_and(predicted, ~expected).sum().item())
    fn = int(torch.logical_and(~predicted, expected).sum().item())
    tn = int(torch.logical_and(~predicted, ~expected).sum().item())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    union = tp + fp + fn
    return {
        "threshold": round(threshold, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "iou": round(tp / union, 6) if union else 0.0,
        "pixel_accuracy": round((tp + tn) / target.numel(), 6),
        "mean_probability": round(float(probability.mean().item()), 6),
    }


def _select_threshold(
    logits: torch.Tensor, target: torch.Tensor
) -> tuple[float, dict[str, Any]]:
    candidates = [value / 100 for value in range(20, 81, 5)]
    scored = [
        (_metrics(logits, target, threshold), threshold) for threshold in candidates
    ]
    best_metrics, best_threshold = max(
        scored,
        key=lambda item: (item[0]["f1"], item[0]["iou"], -abs(item[1] - 0.5)),
    )
    return best_threshold, best_metrics


def _batch_hash(batch: PublicForestBatch) -> str:
    digest = hashlib.sha256()
    digest.update(batch.split.encode("ascii"))
    for tensor in (batch.images, batch.masks):
        array = tensor.detach().cpu().contiguous().numpy()
        digest.update(str(array.shape).encode("ascii"))
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(array.tobytes(order="C"))
    digest.update("\n".join(batch.sample_ids).encode("utf-8"))
    digest.update("\n".join(batch.source_filenames).encode("utf-8"))
    return digest.hexdigest()


def _public_sidecar(checkpoint: Path) -> Path:
    return checkpoint.with_name(f"{checkpoint.name}.metadata.json")


def _save_public_checkpoint(
    checkpoint: Path,
    model: TinyForestCoverSegmenter,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    states = {"model": model.state_dict()}
    state_hash = state_dict_sha256(states)
    payload = {
        "schema_version": "forest-xai-public-checkpoint/1.0",
        "scope": PUBLIC_CHECKPOINT_SCOPE,
        "architecture": {"channels": model.channels, "width": model.width},
        "metadata": {**metadata, "state_dict_sha256": state_hash},
        "state_dict": model.state_dict(),
    }
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(buffer.getvalue())
    sidecar = {
        "schema_version": "forest-xai-public-checkpoint-metadata/1.0",
        "scope": PUBLIC_CHECKPOINT_SCOPE,
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": file_sha256(checkpoint),
        "state_dict_sha256": state_hash,
        "metadata": payload["metadata"],
    }
    _public_sidecar(checkpoint).write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return sidecar


def load_public_checkpoint(
    checkpoint: Path, device: torch.device
) -> tuple[TinyForestCoverSegmenter, dict[str, Any]]:
    sidecar_path = _public_sidecar(checkpoint)
    if not checkpoint.is_file() or not sidecar_path.is_file():
        raise ValueError("public checkpoint and metadata sidecar are required")
    sidecar = load_json_object(sidecar_path)
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
        raise ValueError("public checkpoint metadata sidecar contract is invalid")
    if (
        sidecar.get("schema_version") != "forest-xai-public-checkpoint-metadata/1.0"
        or sidecar.get("scope") != PUBLIC_CHECKPOINT_SCOPE
    ):
        raise ValueError("public checkpoint scope is invalid")
    if file_sha256(checkpoint) != sidecar.get("checkpoint_sha256"):
        raise ValueError("public checkpoint SHA-256 mismatch")
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if (
        payload.get("schema_version") != "forest-xai-public-checkpoint/1.0"
        or payload.get("scope") != PUBLIC_CHECKPOINT_SCOPE
    ):
        raise ValueError("public checkpoint contract is invalid")
    if payload.get("metadata") != sidecar.get("metadata"):
        raise ValueError("public checkpoint metadata differs from embedded metadata")
    state_hash = state_dict_sha256({"model": payload["state_dict"]})
    if {
        state_hash,
        sidecar.get("state_dict_sha256"),
        payload.get("metadata", {}).get("state_dict_sha256"),
    } != {state_hash}:
        raise ValueError("public checkpoint tensor hash mismatch")
    architecture = payload["architecture"]
    model = TinyForestCoverSegmenter(
        channels=architecture["channels"], width=architecture["width"]
    )
    model.load_state_dict(payload["state_dict"])
    model.to(device).eval()
    return model, sidecar


def _evaluate_model(
    model: TinyForestCoverSegmenter,
    batch: PublicForestBatch,
    mean: torch.Tensor,
    std: torch.Tensor,
    threshold: float,
    device: torch.device,
) -> dict[str, Any]:
    with torch.no_grad():
        logits = model(_normalize(batch.images.to(device), mean, std)).cpu()
    return _metrics(logits, batch.masks, threshold)


def train_public(
    fixture_root: Path, output_dir: Path, config: PublicTrainConfig
) -> dict[str, Any]:
    config.validate()
    determinism = configure_determinism(config.seed)
    device = resolve_device(config.device)
    training = load_public_forest_fixture(fixture_root, "train")
    evaluation = load_public_forest_fixture(fixture_root, "evaluation")
    train_scenes = set(training.metadata["source_scene_ids"])
    evaluation_scenes = set(evaluation.metadata["source_scene_ids"])
    if train_scenes & evaluation_scenes:
        raise ValueError("public fixture has scene leakage")
    mean, std = _normalization(training)
    model = TinyForestCoverSegmenter(width=config.width).to(device)
    images = _normalize(training.images.to(device), mean, std)
    target = training.masks.to(device)
    positive = target.sum()
    loss_function = nn.BCEWithLogitsLoss(
        pos_weight=((target.numel() - positive) / positive.clamp_min(1)).reshape(1)
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    final_loss = 0.0
    for _ in range(config.epochs):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_function(model(images), target)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach().item())
    model.eval()
    with torch.no_grad():
        train_logits = model(images).cpu()
    threshold, training_metrics = _select_threshold(train_logits, training.masks)
    evaluation_metrics = _evaluate_model(
        model, evaluation, mean, std, threshold, device
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "sentinel2_forest_cover.pt"
    metadata = {
        "research_track_version": "0.1.0",
        "scope": PUBLIC_FIXTURE_SCOPE,
        "training_config": asdict(config),
        "resolved_device": str(device),
        "determinism": determinism,
        "torch_version": str(torch.__version__),
        "normalization_mean": [round(float(value), 8) for value in mean.flatten()],
        "normalization_std": [round(float(value), 8) for value in std.flatten()],
        "threshold_selected_on_training_split": threshold,
        "training_fixture_sha256": _batch_hash(training),
        "evaluation_fixture_sha256": _batch_hash(evaluation),
        "training_scene_ids": sorted(train_scenes),
        "evaluation_scene_ids": sorted(evaluation_scenes),
        "final_bce": round(final_loss, 6),
        "training_metrics": training_metrics,
        "evaluation_metrics": evaluation_metrics,
        "real_public_satellite_pixels": True,
        "bi_temporal_change_detection": False,
        "external_independent_validation": False,
    }
    sidecar = _save_public_checkpoint(checkpoint, model, metadata)
    result = {
        "schema_version": "forest-xai-public-train-result/1.0",
        "scope": PUBLIC_FIXTURE_SCOPE,
        "checkpoint": checkpoint.name,
        "checkpoint_metadata": _public_sidecar(checkpoint).name,
        "checkpoint_sha256": sidecar["checkpoint_sha256"],
        "state_dict_sha256": sidecar["state_dict_sha256"],
        "training_metrics": training_metrics,
        "evaluation_metrics": evaluation_metrics,
        "claim_boundary": evaluation.metadata["claim_boundary"],
    }
    (output_dir / "train_result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def evaluate_public(
    fixture_root: Path,
    checkpoint: Path,
    output: Path,
    device_name: str = "cpu",
) -> dict[str, Any]:
    device = resolve_device(device_name)
    model, sidecar = load_public_checkpoint(checkpoint, device)
    metadata = sidecar["metadata"]
    batch = load_public_forest_fixture(fixture_root, "evaluation")
    if _batch_hash(batch) != metadata["evaluation_fixture_sha256"]:
        raise ValueError("evaluation fixture differs from checkpoint metadata")
    mean = torch.tensor(metadata["normalization_mean"]).reshape(1, 4, 1, 1)
    std = torch.tensor(metadata["normalization_std"]).reshape(1, 4, 1, 1)
    metrics = _evaluate_model(
        model,
        batch,
        mean,
        std,
        metadata["threshold_selected_on_training_split"],
        device,
    )
    result = {
        "schema_version": "forest-xai-public-evaluation/1.0",
        "scope": PUBLIC_FIXTURE_SCOPE,
        "checkpoint_sha256": sidecar["checkpoint_sha256"],
        "evaluation_fixture_sha256": _batch_hash(batch),
        "source_scene_ids": batch.metadata["source_scene_ids"],
        "metrics": metrics,
        "claim_boundary": batch.metadata["claim_boundary"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _write_gray(path: Path, values: np.ndarray) -> None:
    Image.fromarray(np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8)).save(path)


def _write_rgb(path: Path, image: np.ndarray) -> None:
    rgb = np.moveaxis(image[[0, 1, 2]], 0, -1)
    high = np.quantile(rgb, 0.98)
    Image.fromarray(
        np.rint(np.clip(rgb / max(float(high), 1e-6), 0, 1) * 255).astype(np.uint8)
    ).save(path)


def explain_public(
    fixture_root: Path,
    checkpoint: Path,
    output_dir: Path,
    sample_index: int = 0,
    device_name: str = "cpu",
) -> dict[str, Any]:
    device = resolve_device(device_name)
    model, sidecar = load_public_checkpoint(checkpoint, device)
    metadata = sidecar["metadata"]
    batch = load_public_forest_fixture(fixture_root, "evaluation")
    if not 0 <= sample_index < len(batch.sample_ids):
        raise ValueError("sample_index is outside the public evaluation fixture")
    mean = torch.tensor(metadata["normalization_mean"]).reshape(1, 4, 1, 1)
    std = torch.tensor(metadata["normalization_std"]).reshape(1, 4, 1, 1)
    image = batch.images[sample_index : sample_index + 1].to(device)
    target = batch.masks[sample_index : sample_index + 1].to(device)
    normalized = _normalize(image, mean, std)
    features = model.feature_maps(normalized)
    heatmap, target_score = gradcam_from_feature_map(
        model, features, target_mask=target
    )
    with torch.no_grad():
        probability = torch.sigmoid(model(normalized)).cpu().numpy()[0, 0]
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "rgb": output_dir / "sentinel2_rgb.png",
        "reference": output_dir / "reference_mask.png",
        "probability": output_dir / "forest_probability.png",
        "gradcam": output_dir / "gradcam.png",
    }
    _write_rgb(paths["rgb"], image.cpu().numpy()[0])
    _write_gray(paths["reference"], target.cpu().numpy()[0, 0])
    _write_gray(paths["probability"], probability)
    _write_gray(paths["gradcam"], heatmap.cpu().numpy()[0, 0])
    result = {
        "schema_version": "forest-xai-public-explanation/1.0",
        "scope": PUBLIC_FIXTURE_SCOPE,
        "sample_id": batch.sample_ids[sample_index],
        "source_filename": batch.source_filenames[sample_index],
        "checkpoint_sha256": sidecar["checkpoint_sha256"],
        "gradcam_target": "mean forest logit over source reference-mask pixels",
        "gradcam_target_score": round(target_score, 8),
        "files": {
            name: {"path": path.name, "sha256": file_sha256(path)}
            for name, path in paths.items()
        },
        "claim_boundary": batch.metadata["claim_boundary"],
    }
    (output_dir / "explanation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
