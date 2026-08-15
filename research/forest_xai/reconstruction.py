"""Post-award reconstructions of the presentation-era latent and relief ideas.

The award presentation described two forest visual concepts: interpolating a
generative latent (z) space toward realistic-looking forest frames, and lifting
flat satellite readings into a height-displaced field view. Neither concept has
competition-era code. This module rebuilds both mechanics today, at small scale
and fully deterministically, so the ideas exist as verifiable artifacts instead
of presentation language. Nothing here reproduces HiGAN, the presentation
scores, or satellite-derived elevation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
import torch
from torch import nn

from .checkpoint import file_sha256, state_dict_sha256
from .determinism import configure_determinism, resolve_device
from .jsonio import load_json_object
from .public_data import load_public_forest_fixture
from .public_training import _batch_hash, load_public_checkpoint

RECONSTRUCTION_SCOPE = "post_award_latent_and_relief_reconstruction"

RECONSTRUCTION_CLAIM_BOUNDARY = {
    "post_award_reconstruction": True,
    "presentation_concept_only": True,
    "not_a_higan_reproduction": True,
    "not_photorealistic": True,
    "not_evidence_of_presentation_metrics": True,
}


class TinyChipGenerator(nn.Module):
    """Map a small latent vector to one 4-band 64x64 chip in [0, 1]."""

    def __init__(self, latent_dim: int = 16, width: int = 16, channels: int = 4):
        super().__init__()
        if latent_dim < 2 or width < 4 or channels < 1:
            raise ValueError("latent_dim, width and channels are too small")
        self.latent_dim = latent_dim
        self.width = width
        self.channels = channels
        self.project = nn.Linear(latent_dim, width * 2 * 8 * 8)
        self.decode = nn.Sequential(
            nn.Upsample(scale_factor=2, mode="nearest"),
            nn.Conv2d(width * 2, width, 3, padding=1),
            nn.ReLU(),
            nn.Upsample(scale_factor=2, mode="nearest"),
            nn.Conv2d(width, width // 2, 3, padding=1),
            nn.ReLU(),
            nn.Upsample(scale_factor=2, mode="nearest"),
            nn.Conv2d(width // 2, channels, 3, padding=1),
            nn.Sigmoid(),
        )

    def forward(self, latent: torch.Tensor) -> torch.Tensor:
        if latent.ndim != 2 or latent.shape[1] != self.latent_dim:
            raise ValueError("latent must be shaped (batch, latent_dim)")
        grid = self.project(latent).reshape(latent.shape[0], self.width * 2, 8, 8)
        return self.decode(grid)


class TinyChipCritic(nn.Module):
    """Score one 4-band 64x64 chip as real-vs-generated logit."""

    def __init__(self, width: int = 16, channels: int = 4):
        super().__init__()
        if width < 4 or channels < 1:
            raise ValueError("width and channels are too small")
        self.width = width
        self.channels = channels
        self.encode = nn.Sequential(
            nn.Conv2d(channels, width // 2, 4, stride=2, padding=1),
            nn.LeakyReLU(0.2),
            nn.Conv2d(width // 2, width, 4, stride=2, padding=1),
            nn.LeakyReLU(0.2),
            nn.Conv2d(width, width * 2, 4, stride=2, padding=1),
            nn.LeakyReLU(0.2),
        )
        self.score = nn.Linear(width * 2 * 8 * 8, 1)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        features = self.encode(images).flatten(1)
        return self.score(features).squeeze(1)


@dataclass(frozen=True)
class LatentGanConfig:
    seed: int = 20260812
    device: str = "cpu"
    epochs: int = 120
    batch_size: int = 12
    learning_rate: float = 0.0002
    latent_dim: int = 16
    width: int = 16

    def validate(self) -> None:
        if self.epochs < 1 or self.epochs > 5_000:
            raise ValueError("epochs must be between 1 and 5000")
        if self.batch_size < 2 or self.batch_size > 64:
            raise ValueError("batch_size must be between 2 and 64")
        if not 0 < self.learning_rate <= 0.1:
            raise ValueError("learning_rate must be in (0, 0.1]")
        if self.latent_dim < 2 or self.latent_dim > 256:
            raise ValueError("latent_dim must be between 2 and 256")
        if self.width < 4 or self.width > 128:
            raise ValueError("width must be between 4 and 128")


def _gan_sidecar_path(checkpoint: Path) -> Path:
    return checkpoint.with_name(checkpoint.name + ".metadata.json")


def _save_latent_gan(
    checkpoint: Path,
    generator: TinyChipGenerator,
    critic: TinyChipCritic,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    state_dicts = {
        "generator": generator.state_dict(),
        "critic": critic.state_dict(),
    }
    state_hash = state_dict_sha256(state_dicts)
    payload = {
        "schema_version": "forest-xai-latent-gan-checkpoint/1.0",
        "scope": RECONSTRUCTION_SCOPE,
        "architecture": {
            "latent_dim": generator.latent_dim,
            "width": generator.width,
            "channels": generator.channels,
        },
        "metadata": {**metadata, "state_dict_sha256": state_hash},
        "state_dicts": state_dicts,
    }
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    checkpoint.write_bytes(buffer.getvalue())
    sidecar = {
        "schema_version": "forest-xai-latent-gan-metadata/1.0",
        "scope": RECONSTRUCTION_SCOPE,
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": file_sha256(checkpoint),
        "state_dict_sha256": state_hash,
        "metadata": payload["metadata"],
    }
    _gan_sidecar_path(checkpoint).write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return sidecar


def load_latent_gan(
    checkpoint: Path, device: torch.device
) -> tuple[TinyChipGenerator, TinyChipCritic, dict[str, Any]]:
    """Safely load the reconstruction GAN: hash first, weights_only after."""
    sidecar_file = _gan_sidecar_path(checkpoint)
    if not checkpoint.is_file() or not sidecar_file.is_file():
        raise ValueError("latent GAN checkpoint and metadata sidecar are required")
    sidecar = load_json_object(sidecar_file)
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
        raise ValueError("latent GAN metadata sidecar contract is invalid")
    if (
        sidecar.get("schema_version") != "forest-xai-latent-gan-metadata/1.0"
        or sidecar.get("scope") != RECONSTRUCTION_SCOPE
    ):
        raise ValueError("latent GAN scope is invalid")
    if file_sha256(checkpoint) != sidecar.get("checkpoint_sha256"):
        raise ValueError("latent GAN checkpoint SHA-256 mismatch")
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if (
        payload.get("schema_version") != "forest-xai-latent-gan-checkpoint/1.0"
        or payload.get("scope") != RECONSTRUCTION_SCOPE
    ):
        raise ValueError("latent GAN checkpoint contract is invalid")
    if payload.get("metadata") != sidecar.get("metadata"):
        raise ValueError("latent GAN metadata differs from embedded metadata")
    state_hash = state_dict_sha256(payload["state_dicts"])
    if {
        state_hash,
        sidecar.get("state_dict_sha256"),
        payload.get("metadata", {}).get("state_dict_sha256"),
    } != {state_hash}:
        raise ValueError("latent GAN tensor hash mismatch")
    architecture = payload["architecture"]
    generator = TinyChipGenerator(
        latent_dim=architecture["latent_dim"],
        width=architecture["width"],
        channels=architecture["channels"],
    )
    critic = TinyChipCritic(
        width=architecture["width"], channels=architecture["channels"]
    )
    generator.load_state_dict(payload["state_dicts"]["generator"])
    critic.load_state_dict(payload["state_dicts"]["critic"])
    generator.to(device).eval()
    critic.to(device).eval()
    return generator, critic, sidecar


def train_latent_gan(
    fixture_root: Path, output_dir: Path, config: LatentGanConfig
) -> dict[str, Any]:
    """Train the tiny chip GAN on the public fixture train split."""
    config.validate()
    determinism = configure_determinism(config.seed)
    device = resolve_device(config.device)
    training = load_public_forest_fixture(fixture_root, "train")
    images = training.images.to(device)
    generator = TinyChipGenerator(latent_dim=config.latent_dim, width=config.width).to(
        device
    )
    critic = TinyChipCritic(width=config.width).to(device)
    loss_function = nn.BCEWithLogitsLoss()
    optimizer_g = torch.optim.Adam(
        generator.parameters(), lr=config.learning_rate, betas=(0.5, 0.999)
    )
    optimizer_c = torch.optim.Adam(
        critic.parameters(), lr=config.learning_rate, betas=(0.5, 0.999)
    )
    sampler = torch.Generator(device="cpu").manual_seed(config.seed)
    critic_loss = generator_loss = 0.0
    for _ in range(config.epochs):
        order = torch.randperm(images.shape[0], generator=sampler)
        for start in range(0, images.shape[0], config.batch_size):
            batch_indices = order[start : start + config.batch_size].to(device)
            real = images[batch_indices]
            latent = torch.randn(
                real.shape[0], config.latent_dim, generator=sampler
            ).to(device)
            fake = generator(latent)
            optimizer_c.zero_grad(set_to_none=True)
            real_target = torch.ones(real.shape[0], device=device)
            fake_target = torch.zeros(real.shape[0], device=device)
            loss_c = loss_function(critic(real), real_target) + loss_function(
                critic(fake.detach()), fake_target
            )
            loss_c.backward()
            optimizer_c.step()
            optimizer_g.zero_grad(set_to_none=True)
            loss_g = loss_function(critic(fake), real_target)
            loss_g.backward()
            optimizer_g.step()
            critic_loss = float(loss_c.detach().item())
            generator_loss = float(loss_g.detach().item())
    generator.eval()
    critic.eval()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "latent_gan.pt"
    metadata = {
        "scope": RECONSTRUCTION_SCOPE,
        "claim_boundary": dict(RECONSTRUCTION_CLAIM_BOUNDARY),
        "training_config": asdict(config),
        "resolved_device": str(device),
        "determinism": determinism,
        "torch_version": str(torch.__version__),
        "train_fixture_sha256": _batch_hash(training),
        "final_critic_loss": round(critic_loss, 6),
        "final_generator_loss": round(generator_loss, 6),
        "parameter_count": sum(
            parameter.numel()
            for model in (generator, critic)
            for parameter in model.parameters()
        ),
    }
    sidecar = _save_latent_gan(checkpoint, generator, critic, metadata)
    return {
        "checkpoint": checkpoint.name,
        "checkpoint_sha256": sidecar["checkpoint_sha256"],
        "state_dict_sha256": sidecar["state_dict_sha256"],
        "scope": RECONSTRUCTION_SCOPE,
        "claim_boundary": dict(RECONSTRUCTION_CLAIM_BOUNDARY),
        "final_critic_loss": metadata["final_critic_loss"],
        "final_generator_loss": metadata["final_generator_loss"],
        "parameter_count": metadata["parameter_count"],
    }


def _rgb_composite(image: np.ndarray) -> np.ndarray:
    rgb = np.moveaxis(image[[0, 1, 2]], 0, -1)
    high = np.quantile(rgb, 0.98)
    return np.rint(np.clip(rgb / max(float(high), 1e-6), 0, 1) * 255).astype(np.uint8)


@dataclass(frozen=True)
class LatentInterpolationConfig:
    seed: int = 20260812
    device: str = "cpu"
    frames: int = 8

    def validate(self) -> None:
        if self.frames < 3 or self.frames > 32:
            raise ValueError("frames must be between 3 and 32")


def interpolate_latent_path(
    gan_checkpoint: Path,
    classifier_checkpoint: Path,
    output_dir: Path,
    config: LatentInterpolationConfig,
) -> dict[str, Any]:
    """Walk z0 -> z1, render frames, and probe the classifier response exactly."""
    config.validate()
    configure_determinism(config.seed)
    device = resolve_device(config.device)
    generator, _, gan_sidecar = load_latent_gan(gan_checkpoint, device)
    classifier, classifier_sidecar = load_public_checkpoint(
        classifier_checkpoint, device
    )
    metadata = classifier_sidecar["metadata"]
    mean = torch.tensor(metadata["normalization_mean"]).reshape(1, 4, 1, 1).to(device)
    std = torch.tensor(metadata["normalization_std"]).reshape(1, 4, 1, 1).to(device)
    sampler = torch.Generator(device="cpu").manual_seed(config.seed)
    endpoints = torch.randn(2, generator.latent_dim, generator=sampler).to(device)
    z_start, z_end = endpoints[0:1], endpoints[1:2]

    def forest_score(latent: torch.Tensor) -> torch.Tensor:
        frame = generator(latent)
        return torch.sigmoid(classifier((frame - mean) / std)).mean()

    alphas = [index / (config.frames - 1) for index in range(config.frames)]
    frames: list[np.ndarray] = []
    scores: list[float] = []
    with torch.no_grad():
        for alpha in alphas:
            latent = (1.0 - alpha) * z_start + alpha * z_end
            frame = generator(latent)
            frames.append(frame.cpu().numpy()[0])
            score = torch.sigmoid(classifier((frame - mean) / std)).mean()
            scores.append(float(score.item()))
    path_tangent = z_end - z_start
    path_length = path_tangent.norm().clamp_min(1e-12)
    unit_direction = path_tangent / path_length
    midpoint = 0.5 * (z_start + z_end)
    _, unit_direction_derivative = torch.autograd.functional.jvp(
        forest_score,
        (midpoint,),
        (unit_direction,),
        create_graph=False,
        strict=True,
    )
    tile_size, gutter = 256, 8
    columns = min(4, config.frames)
    rows = (config.frames + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (
            tile_size * columns + gutter * (columns - 1),
            tile_size * rows + gutter * (rows - 1),
        ),
        (244, 247, 244),
    )
    for index, frame in enumerate(frames):
        tile = Image.fromarray(_rgb_composite(frame)).resize(
            (tile_size, tile_size), Image.Resampling.NEAREST
        )
        row, column = divmod(index, columns)
        sheet.paste(tile, (column * (tile_size + gutter), row * (tile_size + gutter)))
    output_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = output_dir / "latent_interpolation.png"
    sheet.save(sheet_path)
    result = {
        "schema_version": "forest-xai-latent-interpolation/1.0",
        "scope": RECONSTRUCTION_SCOPE,
        "claim_boundary": {
            **RECONSTRUCTION_CLAIM_BOUNDARY,
            "real_public_satellite_training_pixels": True,
        },
        "method_label": (
            "latent z interpolation over a self-trained tiny GAN with an exact "
            "forest-score JVP probe"
        ),
        "gan_checkpoint_sha256": gan_sidecar["checkpoint_sha256"],
        "classifier_checkpoint_sha256": classifier_sidecar["checkpoint_sha256"],
        "seed": config.seed,
        "frames": config.frames,
        "alphas": [round(alpha, 6) for alpha in alphas],
        "forest_probabilities": [round(score, 6) for score in scores],
        "jvp": {
            "location_alpha": 0.5,
            "unit_path_direction_derivative": round(
                float(unit_direction_derivative.item()), 8
            ),
            "unit_direction_norm": 1.0,
            "latent_path_length": round(float(path_length.item()), 8),
        },
        "files": {
            "contact_sheet": {
                "path": sheet_path.name,
                "sha256": file_sha256(sheet_path),
            }
        },
    }
    (output_dir / "latent_interpolation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


@dataclass(frozen=True)
class ReliefDrapeConfig:
    seed: int = 20260812
    device: str = "cpu"
    sample_index: int = 3
    height_grid_size: int = 8
    vertical_scale: float = 1.0

    def validate(self) -> None:
        if self.height_grid_size < 2 or self.height_grid_size > 32:
            raise ValueError("height_grid_size must be between 2 and 32")
        if not 0.25 <= self.vertical_scale <= 4:
            raise ValueError("vertical_scale must be between 0.25 and 4")


def _save_npy(path: Path, array: np.ndarray) -> None:
    with path.open("wb") as handle:
        np.save(handle, array, allow_pickle=False)


def _terrain_mesh(
    height: np.ndarray, mesh_size: int = 33
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return normalized vertices, quad faces, and source sample indices."""
    if height.shape != (64, 64) or not np.isfinite(height).all():
        raise ValueError("terrain height must be one finite 64x64 array")
    indices = np.rint(np.linspace(0, 63, mesh_size)).astype(np.int32)
    axis = np.linspace(0, 1, mesh_size, dtype=np.float32)
    x_grid, y_grid = np.meshgrid(axis, axis)
    sampled_height = height[np.ix_(indices, indices)].astype(np.float32)
    vertices = np.stack((x_grid, y_grid, sampled_height), axis=-1)
    faces = np.asarray(
        [
            (
                row * mesh_size + column,
                row * mesh_size + column + 1,
                (row + 1) * mesh_size + column + 1,
                (row + 1) * mesh_size + column,
            )
            for row in range(mesh_size - 1)
            for column in range(mesh_size - 1)
        ],
        dtype=np.int32,
    )
    return vertices, faces, indices


def _render_isometric_mesh(
    vertices: np.ndarray,
    colors: np.ndarray,
    sample_indices: np.ndarray,
    output: Path,
    vertical_scale: float,
) -> None:
    """Render a deterministic isometric preview from machine-readable geometry."""
    if vertices.ndim != 3 or vertices.shape[2] != 3:
        raise ValueError("terrain vertices must be shaped [rows, cols, 3]")
    if colors.shape != (64, 64, 3) or colors.dtype != np.uint8:
        raise ValueError("terrain colors must be one uint8 RGB image")
    width, height = 960, 640
    canvas = Image.new("RGB", (width, height), (244, 247, 244))
    draw = ImageDraw.Draw(canvas)

    def project(vertex: np.ndarray, drop: float = 0.0) -> tuple[int, int]:
        x_value, y_value, z_value = (float(value) for value in vertex)
        return (
            round(width / 2 + (x_value - y_value) * 360),
            round(
                215 + (x_value + y_value) * 165 - z_value * 175 * vertical_scale + drop
            ),
        )

    # A base shadow makes the synthetic height displacement legible without
    # pretending the surface is a satellite-derived terrain model.
    base = [
        project(np.asarray((0.0, 0.0, 0.0)), 28),
        project(np.asarray((1.0, 0.0, 0.0)), 28),
        project(np.asarray((1.0, 1.0, 0.0)), 28),
        project(np.asarray((0.0, 1.0, 0.0)), 28),
    ]
    draw.polygon(base, fill=(185, 197, 190))

    cells: list[tuple[int, int]] = [
        (row, column)
        for row in range(vertices.shape[0] - 1)
        for column in range(vertices.shape[1] - 1)
    ]
    cells.sort(key=lambda item: (sum(item), item[0]))
    for row, column in cells:
        polygon = [
            project(vertices[row, column]),
            project(vertices[row, column + 1]),
            project(vertices[row + 1, column + 1]),
            project(vertices[row + 1, column]),
        ]
        source_row = round(
            (int(sample_indices[row]) + int(sample_indices[row + 1])) / 2
        )
        source_column = round(
            (int(sample_indices[column]) + int(sample_indices[column + 1])) / 2
        )
        fill = tuple(int(value) for value in colors[source_row, source_column])
        draw.polygon(polygon, fill=fill)

    # Sparse mesh lines expose the geometry while keeping the imagery readable.
    line_color = (44, 77, 67)
    for row in range(0, vertices.shape[0], 4):
        draw.line(
            [project(vertex) for vertex in vertices[row]],
            fill=line_color,
            width=1,
        )
    for column in range(0, vertices.shape[1], 4):
        draw.line(
            [project(vertex) for vertex in vertices[:, column]],
            fill=line_color,
            width=1,
        )
    canvas.save(output)


def render_relief_drape(
    fixture_root: Path,
    classifier_checkpoint: Path,
    output_dir: Path,
    config: ReliefDrapeConfig,
) -> dict[str, Any]:
    """Drape imagery and model probability over a synthetic interpolated height."""
    config.validate()
    configure_determinism(config.seed)
    device = resolve_device(config.device)
    evaluation = load_public_forest_fixture(fixture_root, "evaluation")
    if not 0 <= config.sample_index < len(evaluation.sample_ids):
        raise ValueError("sample_index is outside the public evaluation fixture")
    classifier, classifier_sidecar = load_public_checkpoint(
        classifier_checkpoint, device
    )
    metadata = classifier_sidecar["metadata"]
    mean = torch.tensor(metadata["normalization_mean"]).reshape(1, 4, 1, 1).to(device)
    std = torch.tensor(metadata["normalization_std"]).reshape(1, 4, 1, 1).to(device)
    image = evaluation.images[config.sample_index : config.sample_index + 1]
    with torch.no_grad():
        probability = torch.sigmoid(classifier((image.to(device) - mean) / std))[
            0, 0
        ].cpu()
    sampler = torch.Generator(device="cpu").manual_seed(config.seed)
    coarse = torch.randn(
        1,
        1,
        config.height_grid_size,
        config.height_grid_size,
        generator=sampler,
    )
    coarse = nn.functional.avg_pool2d(coarse, 3, stride=1, padding=1)
    height = nn.functional.interpolate(
        coarse, size=(64, 64), mode="bilinear", align_corners=True
    )[0, 0]
    height = (height - height.min()) / (height.max() - height.min()).clamp_min(1e-12)
    base = _rgb_composite(image.numpy()[0]).astype(np.float32)
    heat = probability.numpy()
    overlay = base.copy()
    overlay[..., 0] = np.clip(base[..., 0] + heat * 140.0, 0, 255)
    overlay[..., 1] = base[..., 1] * (1.0 - 0.45 * heat)
    overlay[..., 2] = base[..., 2] * (1.0 - 0.45 * heat)
    colors = np.rint(0.55 * base + 0.45 * overlay).astype(np.uint8)
    output_dir.mkdir(parents=True, exist_ok=True)
    drape_path = output_dir / "terrain_drape.png"
    height_values = height.numpy().astype(np.float32)
    probability_values = probability.numpy().astype(np.float32)
    vertices, faces, sample_indices = _terrain_mesh(height_values)
    machine_artifacts = {
        "height": (output_dir / "terrain_height.npy", height_values),
        "probability": (
            output_dir / "terrain_probability.npy",
            probability_values,
        ),
        "vertices": (output_dir / "terrain_vertices.npy", vertices),
        "faces": (output_dir / "terrain_faces.npy", faces),
    }
    for path, array in machine_artifacts.values():
        _save_npy(path, array)
    _render_isometric_mesh(
        vertices,
        colors,
        sample_indices,
        drape_path,
        vertical_scale=config.vertical_scale,
    )
    file_manifest = {
        "drape": {"path": drape_path.name, "sha256": file_sha256(drape_path)}
    }
    for name, (path, array) in machine_artifacts.items():
        file_manifest[name] = {
            "path": path.name,
            "sha256": file_sha256(path),
            "shape": list(array.shape),
            "dtype": str(array.dtype),
        }
    result = {
        "schema_version": "forest-xai-relief-drape/1.0",
        "scope": RECONSTRUCTION_SCOPE,
        "claim_boundary": {
            **RECONSTRUCTION_CLAIM_BOUNDARY,
            "synthetic_height_field": True,
            "not_satellite_derived_elevation": True,
            "bilinear_height_interpolation": True,
            "renders_committed_model_probability": True,
        },
        "method_label": (
            "2.5D drape of real imagery and model probability over a synthetic "
            "bilinearly upsampled height field"
        ),
        "classifier_checkpoint_sha256": classifier_sidecar["checkpoint_sha256"],
        "evaluation_fixture_sha256": _batch_hash(evaluation),
        "sample_id": evaluation.sample_ids[config.sample_index],
        "sample_index": config.sample_index,
        "seed": config.seed,
        "height_grid_size": config.height_grid_size,
        "vertical_scale": config.vertical_scale,
        "height_generation": {
            "distribution": "torch.randn with fixed CPU generator",
            "coarse_shape": [config.height_grid_size, config.height_grid_size],
            "smoothing": "3x3 average pool, stride 1, padding 1",
            "upsampling": "bilinear to 64x64, align_corners true",
            "normalization": "min-max to [0,1]",
        },
        "mean_forest_probability": round(float(heat.mean()), 6),
        "mesh": {
            "grid_size": int(vertices.shape[0]),
            "vertex_count": int(vertices.shape[0] * vertices.shape[1]),
            "face_count": int(faces.shape[0]),
            "coordinates": "normalized image x/y plus normalized synthetic z",
        },
        "files": file_manifest,
    }
    (output_dir / "terrain_drape.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
