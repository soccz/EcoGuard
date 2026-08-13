"""Compact neural networks used only by the optional research track."""

from __future__ import annotations

import torch
from torch import nn


def _validate_pair(before: torch.Tensor, after: torch.Tensor, channels: int) -> None:
    if before.shape != after.shape or before.ndim != 4:
        raise ValueError(
            "before and after must be equal [batch, channel, height, width]"
        )
    if before.shape[1] != channels:
        raise ValueError(f"expected {channels} multispectral channels")


class TinyChangeSegmenter(nn.Module):
    """Small fully convolutional binary change segmenter."""

    def __init__(self, *, channels: int = 4, width: int = 8) -> None:
        super().__init__()
        self.channels = channels
        self.width = width
        self.features = nn.Sequential(
            nn.Conv2d(channels * 3, width, kernel_size=3, padding=1),
            nn.SiLU(),
            nn.Conv2d(width, width, kernel_size=3, padding=1),
            nn.SiLU(),
        )
        self.head = nn.Conv2d(width, 1, kernel_size=1)

    def feature_maps(self, before: torch.Tensor, after: torch.Tensor) -> torch.Tensor:
        _validate_pair(before, after, self.channels)
        paired = torch.cat((before, after, after - before), dim=1)
        return self.features(paired)

    def forward(self, before: torch.Tensor, after: torch.Tensor) -> torch.Tensor:
        return self.head(self.feature_maps(before, after))


class TinyForestCoverSegmenter(nn.Module):
    """Small four-band forest-cover segmenter for the optional public-data axis."""

    def __init__(self, *, channels: int = 4, width: int = 8) -> None:
        super().__init__()
        self.channels = channels
        self.width = width
        self.features = nn.Sequential(
            nn.Conv2d(channels, width, kernel_size=3, padding=1),
            nn.SiLU(),
            nn.Conv2d(width, width, kernel_size=3, padding=1),
            nn.SiLU(),
        )
        self.head = nn.Conv2d(width, 1, kernel_size=1)

    def feature_maps(self, image: torch.Tensor) -> torch.Tensor:
        if image.ndim != 4 or image.shape[1] != self.channels:
            raise ValueError(f"image must be [batch, {self.channels}, height, width]")
        return self.features(image)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        return self.head(self.feature_maps(image))


class LatentEncoder(nn.Module):
    """Encode a before/after pair into a compact local latent vector."""

    def __init__(
        self,
        *,
        channels: int = 4,
        width: int = 8,
        latent_dim: int = 8,
        image_size: int = 16,
    ) -> None:
        super().__init__()
        if image_size % 4:
            raise ValueError("image_size must be divisible by 4")
        self.channels = channels
        self.width = width
        self.latent_dim = latent_dim
        self.image_size = image_size
        reduced = image_size // 4
        self.convs = nn.Sequential(
            nn.Conv2d(channels * 2, width, 3, stride=2, padding=1),
            nn.SiLU(),
            nn.Conv2d(width, width, 3, stride=2, padding=1),
            nn.SiLU(),
        )
        self.to_latent = nn.Linear(width * reduced * reduced, latent_dim)

    def forward(self, before: torch.Tensor, after: torch.Tensor) -> torch.Tensor:
        _validate_pair(before, after, self.channels)
        features = self.convs(torch.cat((before, after), dim=1))
        return self.to_latent(features.flatten(1))


class LatentGenerator(nn.Module):
    """Decode a local latent vector back to a paired multispectral tensor."""

    def __init__(
        self,
        *,
        channels: int = 4,
        width: int = 8,
        latent_dim: int = 8,
        image_size: int = 16,
    ) -> None:
        super().__init__()
        if image_size % 4:
            raise ValueError("image_size must be divisible by 4")
        self.channels = channels
        self.width = width
        self.latent_dim = latent_dim
        self.image_size = image_size
        self.reduced = image_size // 4
        self.from_latent = nn.Linear(latent_dim, width * self.reduced * self.reduced)
        self.deconvs = nn.Sequential(
            nn.ConvTranspose2d(width, width, 4, stride=2, padding=1),
            nn.SiLU(),
            nn.ConvTranspose2d(width, channels * 2, 4, stride=2, padding=1),
            nn.Sigmoid(),
        )

    def forward(self, latent: torch.Tensor) -> torch.Tensor:
        if latent.ndim != 2 or latent.shape[1] != self.latent_dim:
            raise ValueError(f"latent must be [batch, {self.latent_dim}]")
        features = self.from_latent(latent).reshape(
            latent.shape[0], self.width, self.reduced, self.reduced
        )
        return self.deconvs(features)

    def split_pair(self, generated: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if generated.ndim != 4 or generated.shape[1] != self.channels * 2:
            raise ValueError("generated tensor has the wrong paired-channel shape")
        return generated[:, : self.channels], generated[:, self.channels :]


class LatentScoreClassifier(nn.Module):
    """Small classifier whose local score direction is probed with an exact JVP."""

    def __init__(self, *, latent_dim: int = 8, width: int = 8) -> None:
        super().__init__()
        self.latent_dim = latent_dim
        self.width = width
        self.layers = nn.Sequential(
            nn.Linear(latent_dim, width),
            nn.SiLU(),
            nn.Linear(width, 1),
        )

    def forward(self, latent: torch.Tensor) -> torch.Tensor:
        if latent.ndim != 2 or latent.shape[1] != self.latent_dim:
            raise ValueError(f"latent must be [batch, {self.latent_dim}]")
        return self.layers(latent).squeeze(1)
