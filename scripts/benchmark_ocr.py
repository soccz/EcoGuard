#!/usr/bin/env python3
"""Adapt a local OCR interchange file and report exact field metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from ecoguard.ocr_adapter import (
    SYNTHETIC_BENCHMARK_SCOPE,
    SUPPORTED_FORMATS,
    adapt_ocr_file,
    benchmark_document_bundle,
)
from ecoguard.jsonio import strict_json_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/benchmarks/ocr/synthetic_tesseract.tsv"
DEFAULT_REFERENCE = ROOT / "data/benchmarks/ocr/synthetic_field_reference.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert local OCR/text output into EcoGuard's ingestion contract and "
            "score exact extracted fields. This command does not run an OCR engine."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=sorted(SUPPORTED_FORMATS),
        default="tesseract-tsv",
    )
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--case-id", help="default: case_id from --reference")
    parser.add_argument("--document-id", default="synthetic_ocr_invoice")
    parser.add_argument("--document-type", default="commercial_invoice")
    parser.add_argument("--language", default="ko-en")
    parser.add_argument(
        "--confidence-scale",
        choices=("unit", "percent"),
        default="unit",
        help="confidence scale for generic-json only (default: unit)",
    )
    parser.add_argument(
        "--default-confidence",
        type=float,
        default=0.0,
        help="fallback for missing JSON confidence or pdftotext (default: 0.0)",
    )
    parser.add_argument("--output", type=Path, help="write JSON instead of stdout")
    return parser


def _load_json(path: Path) -> dict[str, Any]:
    payload = strict_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("field reference must be a JSON object")
    return payload


def _emit(payload: dict[str, Any], output: Path | None) -> None:
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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reference = _load_json(args.reference)
    case_id = args.case_id or reference.get("case_id")
    bundle = adapt_ocr_file(
        args.input,
        input_format=args.input_format,
        case_id=case_id,
        document_id=args.document_id,
        document_type=args.document_type,
        language=args.language,
        confidence_scale=args.confidence_scale,
        default_confidence=args.default_confidence,
    )
    uses_committed_fixture = (
        args.input.resolve() == DEFAULT_INPUT.resolve()
        and args.reference.resolve() == DEFAULT_REFERENCE.resolve()
    )
    _emit(
        benchmark_document_bundle(
            bundle,
            reference,
            scope=SYNTHETIC_BENCHMARK_SCOPE if uses_committed_fixture else None,
        ),
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
