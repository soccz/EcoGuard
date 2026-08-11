"""Command-line entry points for full and stage-level reproduction."""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Sequence

from .cbam import calculate_exposure
from .forest import analyze_forest_case, build_regions_geojson
from .ingestion import extract_document_bundle_file
from .legal import LegalRetriever, load_json
from .pipeline import repository_root, reproduce
from .preprocessing import normalize_file


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        help="write JSON to this path instead of stdout",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecoguard",
        description="Reproduce and inspect EcoGuard's synthetic evidence pipeline.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    reproduce_parser = subcommands.add_parser(
        "reproduce",
        help="run ingestion, normalization, legal, CBAM and forest stages",
    )
    reproduce_parser.add_argument(
        "--output",
        default="artifacts/generated",
        help="output directory (default: artifacts/generated)",
    )
    reproduce_parser.add_argument("--root", type=Path, help="repository root override")

    extract_parser = subcommands.add_parser(
        "extract",
        help="extract candidate records from a document-oriented OCR payload",
    )
    extract_parser.add_argument("input", type=Path)
    _add_output(extract_parser)

    normalize_parser = subcommands.add_parser(
        "normalize",
        help="normalize extracted records with an explicit selection policy",
    )
    normalize_parser.add_argument("input", type=Path)
    normalize_parser.add_argument("--policy", required=True, type=Path)
    _add_output(normalize_parser)

    cbam_parser = subcommands.add_parser(
        "cbam-calculate",
        help="calculate the non-statutory component and price-sensitivity trace",
    )
    cbam_parser.add_argument("input", type=Path, help="normalized evidence JSON")
    _add_output(cbam_parser)

    forest_parser = subcommands.add_parser(
        "forest-analyze",
        help="evaluate the synthetic NDVI mask and emit result JSON",
    )
    forest_parser.add_argument("manifest", type=Path)
    forest_parser.add_argument(
        "--geojson",
        action="store_true",
        help="emit the cell-level GeoJSON instead of the analysis JSON",
    )
    _add_output(forest_parser)

    search_parser = subcommands.add_parser(
        "legal-search",
        help="search curated CBAM/EUDR article metadata with decision trace",
    )
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=_positive_int, default=3)
    search_parser.add_argument("--root", type=Path)
    _add_output(search_parser)
    return parser


def _emit(payload: Any, output: Path | None) -> None:
    serialized = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    if output is None:
        print(serialized, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")


def _legal_corpus_path(root: Path | None) -> Path:
    root_path = root.resolve() if root else repository_root()
    candidate = root_path / "data/reference/legal_corpus.json"
    if candidate.is_file():
        return candidate
    if root is None:
        resource = files("ecoguard.resources").joinpath("legal_corpus.json")
        if resource.is_file():
            return Path(str(resource))
    raise FileNotFoundError(candidate)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "reproduce":
        paths = reproduce(args.output, root=args.root)
        print("EcoGuard reproduction completed:")
        for name, path in paths.items():
            print(f"- {name}: {path}")
        return 0

    if args.command == "extract":
        _emit(extract_document_bundle_file(args.input), args.output)
        return 0
    if args.command == "normalize":
        _emit(
            normalize_file(args.input, policy_path=args.policy),
            args.output,
        )
        return 0
    if args.command == "cbam-calculate":
        _emit(calculate_exposure(load_json(args.input)), args.output)
        return 0
    if args.command == "forest-analyze":
        result = analyze_forest_case(args.manifest)
        _emit(build_regions_geojson(result) if args.geojson else result, args.output)
        return 0

    corpus = load_json(_legal_corpus_path(args.root))
    response = LegalRetriever(corpus).retrieve(args.query, limit=args.limit)
    _emit(response, args.output)
    return 0
