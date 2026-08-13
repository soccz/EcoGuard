"""Grad-CAM and local latent-direction/JVP probes for the synthetic model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import torch

from .checkpoint import file_sha256, load_checkpoint
from .determinism import configure_determinism, resolve_device
from .fixture import FIXTURE_SCOPE, fixture_sha256, make_synthetic_batch
from .models import (
    LatentEncoder,
    LatentGenerator,
    LatentScoreClassifier,
    TinyChangeSegmenter,
)
from .training import TrainConfig


def gradcam(
    model: TinyChangeSegmenter,
    before: torch.Tensor,
    after: torch.Tensor,
    *,
    target_mask: torch.Tensor | None = None,
) -> tuple[torch.Tensor, float]:
    """Compute positive-class segmentation Grad-CAM from the last feature map."""
    features = model.feature_maps(before, after)
    return gradcam_from_feature_map(model, features, target_mask=target_mask)


def gradcam_from_feature_map(
    model: torch.nn.Module,
    features: torch.Tensor,
    *,
    target_mask: torch.Tensor | None = None,
) -> tuple[torch.Tensor, float]:
    """Compute segmentation Grad-CAM for any model exposing a one-channel ``head``."""
    model.zero_grad(set_to_none=True)
    head = getattr(model, "head", None)
    if not isinstance(head, torch.nn.Module):
        raise ValueError("model must expose a torch.nn.Module head")
    logits = head(features)
    if logits.ndim != 4 or logits.shape[1] != 1:
        raise ValueError("model head must return [batch, 1, height, width] logits")
    if target_mask is None or not bool(target_mask.any()):
        region = torch.ones_like(logits)
    else:
        region = target_mask.to(dtype=logits.dtype, device=logits.device)
    target_score = (logits * region).sum() / region.sum().clamp_min(1)
    gradients = torch.autograd.grad(target_score, features)[0]
    weights = gradients.mean(dim=(2, 3), keepdim=True)
    heatmap = torch.relu((weights * features).sum(dim=1, keepdim=True))
    flat_max = heatmap.amax(dim=(2, 3), keepdim=True)
    flat_min = heatmap.amin(dim=(2, 3), keepdim=True)
    heatmap = (heatmap - flat_min) / (flat_max - flat_min).clamp_min(1e-12)
    return heatmap.detach(), float(target_score.detach().item())


def latent_direction_probe(
    encoder: LatentEncoder,
    generator: LatentGenerator,
    latent_classifier: LatentScoreClassifier,
    before: torch.Tensor,
    after: torch.Tensor,
    *,
    direction_name: str = "decrease",
    step: float = 0.35,
) -> tuple[dict[str, Any], torch.Tensor, torch.Tensor]:
    """Traverse a local score-gradient direction and report its exact JVP."""
    if direction_name not in {"increase", "decrease"}:
        raise ValueError("direction_name must be increase or decrease")
    if step <= 0:
        raise ValueError("step must be positive")

    latent = encoder(before, after).detach().requires_grad_(True)

    def score_function(z: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(latent_classifier(z)).mean()

    score = score_function(latent)
    gradient = torch.autograd.grad(score, latent, create_graph=False)[0]
    gradient_norm = gradient.norm().clamp_min(1e-12)
    sign = 1.0 if direction_name == "increase" else -1.0
    direction = sign * gradient / gradient_norm
    _, directional_derivative = torch.autograd.functional.jvp(
        score_function,
        (latent.detach(),),
        (direction.detach(),),
        create_graph=False,
        strict=True,
    )
    with torch.no_grad():
        generated = generator(latent)
        counterfactual = generator(latent + step * direction)
        original_score = score_function(latent)
        counterfactual_score = score_function(latent + step * direction)
    observed_delta = float((counterfactual_score - original_score).item())
    expected_sign = 1 if direction_name == "increase" else -1
    result = {
        "schema_version": "forest-xai-latent-direction-probe/1.0",
        "method_label": "local JVP latent explanation",
        "not_a_reproduction": True,
        "not_a_gan": True,
        "direction": direction_name,
        "step": step,
        "score_before": round(float(original_score.item()), 8),
        "score_after": round(float(counterfactual_score.item()), 8),
        "score_delta": round(observed_delta, 8),
        "local_jvp": round(float(directional_derivative.item()), 8),
        "latent_gradient_norm": round(float(gradient_norm.item()), 8),
        "observed_direction_matches_request": observed_delta * expected_sign >= 0,
        "claim_boundary": (
            "A local differentiable classifier-score probe on a tiny synthetic "
            "encoder/generator; not a causal explanation, semantic factor, named-paper "
            "reproduction, GAN result, or field result."
        ),
    }
    return result, generated.detach(), counterfactual.detach()


def _save_heatmap(path: Path, heatmap: torch.Tensor) -> None:
    values = heatmap.squeeze().detach().cpu().numpy()
    # Dependency-free blue→yellow→red palette for a single normalized activation map.
    red = np.clip(values * 2.0, 0.0, 1.0)
    green = np.clip(1.0 - np.abs(values - 0.5) * 2.0, 0.0, 1.0)
    blue = np.clip((0.5 - values) * 2.0, 0.0, 1.0)
    rgb = np.stack((red, green, blue), axis=-1)
    image = Image.fromarray(np.rint(rgb * 255).astype(np.uint8), mode="RGB")
    image.resize(
        (values.shape[1] * 16, values.shape[0] * 16), Image.Resampling.NEAREST
    ).save(path)


def _array_sha256(array: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("ascii"))
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def explain(
    checkpoint: Path,
    output_dir: Path,
    *,
    device_name: str = "cpu",
    sample_index: int = 0,
    direction_name: str = "decrease",
    step: float = 0.35,
) -> dict[str, Any]:
    device = resolve_device(device_name)
    segmenter, encoder, generator, latent_classifier, sidecar = load_checkpoint(
        checkpoint, device=device
    )
    config = TrainConfig(**sidecar["metadata"]["training_config"])
    configure_determinism(config.seed)
    batch = make_synthetic_batch(
        samples=config.evaluation_samples,
        image_size=config.image_size,
        seed=config.seed + 1,
        split="evaluation",
    )
    if sample_index < 0 or sample_index >= len(batch.sample_ids):
        raise ValueError("sample_index is outside the evaluation fixture")
    selection = slice(sample_index, sample_index + 1)
    before = batch.before[selection].to(device)
    after = batch.after[selection].to(device)
    target = batch.mask[selection].to(device)
    heatmap, gradcam_score = gradcam(segmenter, before, after, target_mask=target)
    latent_result, reconstructed, counterfactual = latent_direction_probe(
        encoder,
        generator,
        latent_classifier,
        before,
        after,
        direction_name=direction_name,
        step=step,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    heatmap_path = output_dir / "gradcam_heatmap.png"
    tensors_path = output_dir / "explanation_tensors.npz"
    _save_heatmap(heatmap_path, heatmap)
    arrays = {
        "before": before.cpu().numpy(),
        "after": after.cpu().numpy(),
        "target_mask": target.cpu().numpy(),
        "gradcam": heatmap.cpu().numpy(),
        "autoencoder_reconstruction": reconstructed.cpu().numpy(),
        "latent_counterfactual_probe": counterfactual.cpu().numpy(),
    }
    np.savez_compressed(tensors_path, **arrays)
    result = {
        "schema_version": "forest-xai-explanation/1.0",
        "scope": FIXTURE_SCOPE,
        "sample_id": batch.sample_ids[sample_index],
        "fixture_sha256": fixture_sha256(batch),
        "checkpoint_sha256": sidecar["checkpoint_sha256"],
        "gradcam": {
            "target": "positive change logit over the synthetic target region",
            "target_score": round(gradcam_score, 8),
            "heatmap_file": heatmap_path.name,
            "heatmap_sha256": file_sha256(heatmap_path),
            "tensor_sha256": _array_sha256(arrays["gradcam"]),
        },
        "latent_probe": latent_result,
        "tensors_file": tensors_path.name,
        "tensors_sha256": file_sha256(tensors_path),
        "warning": (
            "Synthetic smoke-test explanation only; no real satellite data, causal "
            "meaning, model accuracy, or EUDR determination is claimed."
        ),
    }
    (output_dir / "explanation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
