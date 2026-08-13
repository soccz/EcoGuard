"""Seed and device controls for the optional PyTorch research track."""

from __future__ import annotations

import os
import random

import numpy as np
import torch


def configure_determinism(seed: int) -> dict[str, object]:
    """Configure deterministic execution and return auditable settings."""
    if seed < 0:
        raise ValueError("seed must be non-negative")

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.set_num_threads(1)
    return {
        "seed": seed,
        "deterministic_algorithms": True,
        "cudnn_benchmark": False,
        "cudnn_deterministic": True,
        "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        "torch_num_threads": torch.get_num_threads(),
    }


def resolve_device(requested: str) -> torch.device:
    """Resolve an explicit device without silently changing user intent."""
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cpu":
        return torch.device("cpu")
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA was requested but is not available")
        return torch.device("cuda")
    raise ValueError("device must be one of: cpu, cuda, auto")
