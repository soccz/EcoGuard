"""Small deterministic metric helpers for the synthetic fixture."""

from __future__ import annotations

import torch


def segmentation_metrics(
    logits: torch.Tensor, target: torch.Tensor
) -> dict[str, float | int]:
    if logits.shape != target.shape:
        raise ValueError("logits and target shapes must match")
    predicted = torch.sigmoid(logits) >= 0.5
    expected = target >= 0.5
    tp = int(torch.logical_and(predicted, expected).sum().item())
    fp = int(torch.logical_and(predicted, ~expected).sum().item())
    fn = int(torch.logical_and(~predicted, expected).sum().item())
    tn = int(torch.logical_and(~predicted, ~expected).sum().item())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": (
            round(2 * precision * recall / (precision + recall), 6)
            if precision + recall
            else 0.0
        ),
        "iou": round(tp / (tp + fp + fn), 6) if tp + fp + fn else 0.0,
        "pixel_accuracy": round((tp + tn) / target.numel(), 6),
    }
