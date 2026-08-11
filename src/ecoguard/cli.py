"""Command-line interface for reproduction and legal citation search."""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path
from typing import Sequence

from .legal import LegalRetriever, load_json
from .pipeline import repository_root, reproduce


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecoguard",
        description="Reproduce EcoGuard's synthetic evidence pipeline.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    reproduce_parser = subcommands.add_parser(
        "reproduce",
        help="run normalization, retrieval, CBAM and forest-change baselines",
    )
    reproduce_parser.add_argument(
        "--output",
        default="artifacts/generated",
        help="output directory (default: artifacts/generated)",
    )
    reproduce_parser.add_argument(
        "--root",
        type=Path,
        help="repository root override",
    )

    search_parser = subcommands.add_parser(
        "legal-search",
        help="search the curated CBAM/EUDR article metadata",
    )
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=_positive_int, default=3)
    search_parser.add_argument("--root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "reproduce":
        paths = reproduce(args.output, root=args.root)
        print("EcoGuard reproduction completed:")
        for name, path in paths.items():
            print(f"- {name}: {path}")
        return 0

    root = args.root.resolve() if args.root else repository_root()
    corpus_path = root / "data/reference/legal_corpus.json"
    if not corpus_path.is_file() and args.root is None:
        corpus_path = Path(
            str(files("ecoguard.resources").joinpath("legal_corpus.json"))
        )
    corpus = load_json(corpus_path)
    results = LegalRetriever(corpus).search(args.query, limit=args.limit)
    response = {
        "query": args.query,
        "abstained": not results,
        "reason": (
            "no result met the minimum evidence score" if not results else None
        ),
        "results": results,
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0
