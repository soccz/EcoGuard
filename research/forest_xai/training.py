"""CPU-friendly training and evaluation on the synthetic smoke fixture."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import torch
from torch import nn

from .checkpoint import load_checkpoint, save_checkpoint
from .determinism import configure_determinism, resolve_device
from .fixture import FIXTURE_SCOPE, fixture_sha256, make_synthetic_batch
from .metrics import segmentation_metrics
from .models import (
    LatentEncoder,
    LatentGenerator,
    LatentScoreClassifier,
    TinyChangeSegmenter,
)


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 20260812
    device: str = "cpu"
    epochs: int = 12
    train_samples: int = 24
    evaluation_samples: int = 8
    image_size: int = 16
    channels: int = 4
    segmenter_width: int = 8
    latent_width: int = 8
    latent_dim: int = 8
    learning_rate: float = 0.025
    reconstruction_weight: float = 0.20
    latent_classifier_weight: float = 0.25

    def validate(self) -> None:
        if self.epochs < 1:
            raise ValueError("epochs must be positive")
        if self.channels != 4:
            raise ValueError(
                "the committed synthetic fixture has exactly four channels"
            )
        if (
            self.learning_rate <= 0
            or self.reconstruction_weight < 0
            or self.latent_classifier_weight < 0
        ):
            raise ValueError("loss weights and learning rate must be valid")


def _make_models(config: TrainConfig, device: torch.device):
    segmenter = TinyChangeSegmenter(
        channels=config.channels, width=config.segmenter_width
    ).to(device)
    common = {
        "channels": config.channels,
        "width": config.latent_width,
        "latent_dim": config.latent_dim,
        "image_size": config.image_size,
    }
    return (
        segmenter,
        LatentEncoder(**common).to(device),
        LatentGenerator(**common).to(device),
        LatentScoreClassifier(
            latent_dim=config.latent_dim, width=config.latent_width
        ).to(device),
    )


def _evaluation_metrics(
    segmenter: TinyChangeSegmenter,
    encoder: LatentEncoder,
    generator: LatentGenerator,
    latent_classifier: LatentScoreClassifier,
    *,
    config: TrainConfig,
    device: torch.device,
) -> tuple[dict[str, float | int], str]:
    batch = make_synthetic_batch(
        samples=config.evaluation_samples,
        image_size=config.image_size,
        seed=config.seed + 1,
        split="evaluation",
    )
    before, after, target = (
        batch.before.to(device),
        batch.after.to(device),
        batch.mask.to(device),
    )
    with torch.no_grad():
        logits = segmenter(before, after)
        reconstructed = generator(encoder(before, after))
        latent_logits = latent_classifier(encoder(before, after))
        sample_target = (target.flatten(1).amax(dim=1) >= 0.5).to(latent_logits.dtype)
        original = torch.cat((before, after), dim=1)
        reconstruction_l1 = float(
            torch.nn.functional.l1_loss(reconstructed, original).item()
        )
        latent_accuracy = float(
            ((torch.sigmoid(latent_logits) >= 0.5) == (sample_target >= 0.5))
            .to(torch.float32)
            .mean()
            .item()
        )
    metrics = segmentation_metrics(logits.cpu(), target.cpu())
    metrics["reconstruction_l1"] = round(reconstruction_l1, 6)
    metrics["latent_classifier_accuracy"] = round(latent_accuracy, 6)
    return metrics, fixture_sha256(batch)


def train(output_dir: Path, config: TrainConfig) -> dict[str, Any]:
    config.validate()
    determinism = configure_determinism(config.seed)
    device = resolve_device(config.device)
    segmenter, encoder, generator, latent_classifier = _make_models(config, device)
    batch = make_synthetic_batch(
        samples=config.train_samples,
        image_size=config.image_size,
        seed=config.seed,
        split="train",
    )
    before, after, target = (
        batch.before.to(device),
        batch.after.to(device),
        batch.mask.to(device),
    )
    positive = target.sum()
    pos_weight = ((target.numel() - positive) / positive.clamp_min(1)).reshape(1)
    segmentation_loss = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(
        [
            *segmenter.parameters(),
            *encoder.parameters(),
            *generator.parameters(),
            *latent_classifier.parameters(),
        ],
        lr=config.learning_rate,
    )

    final_losses: dict[str, float] = {}
    for _ in range(config.epochs):
        optimizer.zero_grad(set_to_none=True)
        logits = segmenter(before, after)
        latent = encoder(before, after)
        reconstructed = generator(latent)
        seg_loss = segmentation_loss(logits, target)
        recon_loss = torch.nn.functional.l1_loss(
            reconstructed, torch.cat((before, after), dim=1)
        )
        latent_logits = latent_classifier(latent)
        sample_target = (target.flatten(1).amax(dim=1) >= 0.5).to(latent_logits.dtype)
        latent_loss = torch.nn.functional.binary_cross_entropy_with_logits(
            latent_logits, sample_target
        )
        loss = (
            seg_loss
            + config.reconstruction_weight * recon_loss
            + config.latent_classifier_weight * latent_loss
        )
        loss.backward()
        optimizer.step()
        final_losses = {
            "total": round(float(loss.detach().item()), 6),
            "segmentation_bce": round(float(seg_loss.detach().item()), 6),
            "reconstruction_l1": round(float(recon_loss.detach().item()), 6),
            "latent_classifier_bce": round(float(latent_loss.detach().item()), 6),
        }

    evaluation, evaluation_fixture_hash = _evaluation_metrics(
        segmenter,
        encoder,
        generator,
        latent_classifier,
        config=config,
        device=device,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "forest_xai_checkpoint.pt"
    checkpoint_metadata = {
        "research_track_version": "0.1.0",
        "scope": FIXTURE_SCOPE,
        "training_config": asdict(config),
        "resolved_device": str(device),
        "determinism": determinism,
        "torch_version": str(torch.__version__),
        "training_fixture_sha256": fixture_sha256(batch),
        "evaluation_fixture_sha256": evaluation_fixture_hash,
        "final_losses": final_losses,
        "evaluation": evaluation,
        "real_satellite_data": False,
        "real_world_performance_claim": False,
    }
    sidecar = save_checkpoint(
        checkpoint,
        segmenter=segmenter,
        encoder=encoder,
        generator=generator,
        latent_classifier=latent_classifier,
        metadata=checkpoint_metadata,
    )
    result = {
        "schema_version": "forest-xai-train-result/1.0",
        "scope": FIXTURE_SCOPE,
        "checkpoint": checkpoint.name,
        "checkpoint_metadata": f"{checkpoint.name}.metadata.json",
        "checkpoint_sha256": sidecar["checkpoint_sha256"],
        "state_dict_sha256": sidecar["state_dict_sha256"],
        "final_losses": final_losses,
        "evaluation": evaluation,
        "warning": "Synthetic smoke-test metrics are not satellite or deployment performance.",
    }
    (output_dir / "train_result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def evaluate(
    checkpoint: Path, output: Path, *, device_name: str = "cpu"
) -> dict[str, Any]:
    device = resolve_device(device_name)
    segmenter, encoder, generator, latent_classifier, sidecar = load_checkpoint(
        checkpoint, device=device
    )
    config = TrainConfig(**sidecar["metadata"]["training_config"])
    configure_determinism(config.seed)
    metrics, fixture_hash = _evaluation_metrics(
        segmenter,
        encoder,
        generator,
        latent_classifier,
        config=config,
        device=device,
    )
    result = {
        "schema_version": "forest-xai-evaluation/1.0",
        "scope": FIXTURE_SCOPE,
        "checkpoint_sha256": sidecar["checkpoint_sha256"],
        "evaluation_fixture_sha256": fixture_hash,
        "metrics": metrics,
        "warning": "Synthetic smoke-test metrics are not satellite or deployment performance.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
