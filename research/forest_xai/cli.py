"""CLI for train, evaluate, and explain research smoke tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .explain import explain
from .public_training import (
    PublicTrainConfig,
    evaluate_public,
    explain_public,
    train_public,
)
from .training import TrainConfig, evaluate, train


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m research.forest_xai",
        description="Optional synthetic-only forest segmentation/XAI research track.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser(
        "train", help="train on the tiny synthetic fixture"
    )
    train_parser.add_argument("--output-dir", type=Path, required=True)
    train_parser.add_argument("--seed", type=int, default=20260812)
    train_parser.add_argument(
        "--device", choices=("cpu", "cuda", "auto"), default="cpu"
    )
    train_parser.add_argument("--epochs", type=int, default=12)
    train_parser.add_argument("--train-samples", type=int, default=24)
    train_parser.add_argument("--evaluation-samples", type=int, default=8)
    train_parser.add_argument("--image-size", type=int, default=16)

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="evaluate a verified checkpoint"
    )
    evaluate_parser.add_argument("--checkpoint", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    evaluate_parser.add_argument(
        "--device", choices=("cpu", "cuda", "auto"), default="cpu"
    )

    explain_parser = subparsers.add_parser(
        "explain", help="write Grad-CAM and latent probes"
    )
    explain_parser.add_argument("--checkpoint", type=Path, required=True)
    explain_parser.add_argument("--output-dir", type=Path, required=True)
    explain_parser.add_argument(
        "--device", choices=("cpu", "cuda", "auto"), default="cpu"
    )
    explain_parser.add_argument("--sample-index", type=int, default=1)
    explain_parser.add_argument(
        "--direction", choices=("increase", "decrease"), default="decrease"
    )
    explain_parser.add_argument("--step", type=float, default=0.35)

    public_train = subparsers.add_parser(
        "public-train", help="train the real Sentinel-2 forest-cover research model"
    )
    public_train.add_argument("--fixture-root", type=Path, required=True)
    public_train.add_argument("--output-dir", type=Path, required=True)
    public_train.add_argument("--seed", type=int, default=20260812)
    public_train.add_argument(
        "--device", choices=("cpu", "cuda", "auto"), default="cpu"
    )
    public_train.add_argument("--epochs", type=int, default=80)
    public_train.add_argument("--learning-rate", type=float, default=0.02)
    public_train.add_argument("--width", type=int, default=16)

    public_evaluate = subparsers.add_parser(
        "public-evaluate", help="evaluate the real Sentinel-2 forest-cover model"
    )
    public_evaluate.add_argument("--fixture-root", type=Path, required=True)
    public_evaluate.add_argument("--checkpoint", type=Path, required=True)
    public_evaluate.add_argument("--output", type=Path, required=True)
    public_evaluate.add_argument(
        "--device", choices=("cpu", "cuda", "auto"), default="cpu"
    )

    public_explain = subparsers.add_parser(
        "public-explain", help="write a Grad-CAM trace for the public evaluation split"
    )
    public_explain.add_argument("--fixture-root", type=Path, required=True)
    public_explain.add_argument("--checkpoint", type=Path, required=True)
    public_explain.add_argument("--output-dir", type=Path, required=True)
    public_explain.add_argument("--sample-index", type=int, default=0)
    public_explain.add_argument(
        "--device", choices=("cpu", "cuda", "auto"), default="cpu"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "train":
        result = train(
            args.output_dir,
            TrainConfig(
                seed=args.seed,
                device=args.device,
                epochs=args.epochs,
                train_samples=args.train_samples,
                evaluation_samples=args.evaluation_samples,
                image_size=args.image_size,
            ),
        )
    elif args.command == "evaluate":
        result = evaluate(args.checkpoint, args.output, device_name=args.device)
    elif args.command == "explain":
        result = explain(
            args.checkpoint,
            args.output_dir,
            device_name=args.device,
            sample_index=args.sample_index,
            direction_name=args.direction,
            step=args.step,
        )
    elif args.command == "public-train":
        result = train_public(
            args.fixture_root,
            args.output_dir,
            PublicTrainConfig(
                seed=args.seed,
                device=args.device,
                epochs=args.epochs,
                learning_rate=args.learning_rate,
                width=args.width,
            ),
        )
    elif args.command == "public-evaluate":
        result = evaluate_public(
            args.fixture_root, args.checkpoint, args.output, args.device
        )
    else:
        result = explain_public(
            args.fixture_root,
            args.checkpoint,
            args.output_dir,
            args.sample_index,
            args.device,
        )
    print(json.dumps(result, sort_keys=True))
    return 0
