"""Deterministic synthetic NDVI change detection and mask evaluation."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Iterable


Cell = tuple[int, int]
BAND_COLUMNS = (
    "row",
    "col",
    "red_before",
    "nir_before",
    "red_after",
    "nir_after",
)
REFERENCE_COLUMNS = ("row", "col", "reference_loss")
SCHEMA_VERSION = "2.0.0"
METRIC_DIGITS = 6


@dataclass(frozen=True)
class GridSpec:
    rows: int
    cols: int
    connectivity: int
    cell_width_m: Decimal
    cell_height_m: Decimal
    top_left_lon: Decimal
    top_left_lat: Decimal
    pixel_width_deg: Decimal
    pixel_height_deg: Decimal

    @property
    def pixel_area_m2(self) -> Decimal:
        return self.cell_width_m * self.cell_height_m

    @property
    def cells(self) -> frozenset[Cell]:
        return frozenset(
            (row, col) for row in range(self.rows) for col in range(self.cols)
        )


@dataclass(frozen=True)
class BandPixel:
    row: int
    col: int
    red_before: Decimal
    nir_before: Decimal
    red_after: Decimal
    nir_after: Decimal

    @property
    def cell(self) -> Cell:
        return self.row, self.col


@dataclass(frozen=True)
class PixelResult:
    row: int
    col: int
    ndvi_before: Decimal
    ndvi_after: Decimal
    ndvi_change: Decimal
    predicted_loss: bool
    reference_loss: bool | None = None

    @property
    def cell(self) -> Cell:
        return self.row, self.col

    @property
    def confusion_class(self) -> str | None:
        if self.reference_loss is None:
            return None
        if self.predicted_loss:
            return "tp" if self.reference_loss else "fp"
        return "fn" if self.reference_loss else "tn"


@dataclass(frozen=True)
class ForestCase:
    schema_version: str
    case_id: str
    classification: str
    relation_to_trade_case: str
    grid: GridSpec
    forest_threshold: Decimal
    loss_threshold: Decimal
    pixels: tuple[BandPixel, ...]
    reference_mask: frozenset[Cell]
    reference_provenance: str


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _positive_decimal(value: Any, field: str) -> Decimal:
    parsed = _decimal(value, field)
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{field} has missing or unsupported properties")


def _require_decimal_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a decimal string")
    return value


def _bounded_threshold(
    value: Any,
    field: str,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    parsed = _decimal(value, field)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field} must be within [{minimum}, {maximum}]")
    return parsed


def _ndvi_decimal(red: Decimal, nir: Decimal) -> Decimal:
    denominator = nir + red
    if denominator == 0:
        raise ValueError("NDVI is undefined when red + NIR is zero")
    with localcontext() as context:
        context.prec = 28
        return (nir - red) / denominator


def ndvi(red: float, nir: float) -> float:
    """Return NDVI for finite reflectance values in the closed interval [0, 1]."""
    red_value = _decimal(red, "red reflectance")
    nir_value = _decimal(nir, "NIR reflectance")
    if not Decimal("0") <= red_value <= Decimal("1"):
        raise ValueError("red reflectance must be within [0, 1]")
    if not Decimal("0") <= nir_value <= Decimal("1"):
        raise ValueError("NIR reflectance must be within [0, 1]")
    return float(_ndvi_decimal(red_value, nir_value))


def _parse_coordinate(row: dict[str, str], line_number: int) -> Cell:
    try:
        coordinate = int(row["row"]), int(row["col"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid pixel coordinate on CSV line {line_number}") from exc
    if coordinate[0] < 0 or coordinate[1] < 0:
        raise ValueError(f"pixel coordinate must be non-negative: {coordinate}")
    return coordinate


def _read_rows(path: Path, expected_columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != expected_columns:
            raise ValueError(
                f"invalid CSV columns for {path.name}; expected {expected_columns}"
            )
        rows = list(reader)
    if not rows:
        raise ValueError(f"CSV fixture is empty: {path.name}")
    if any(
        None in row or any(value is None or not value.strip() for value in row.values())
        for row in rows
    ):
        raise ValueError(f"CSV fixture contains a blank or extra value: {path.name}")
    return rows


def _read_band_pixels(path: Path) -> tuple[BandPixel, ...]:
    pixels: list[BandPixel] = []
    coordinates: set[Cell] = set()
    for line_number, row in enumerate(_read_rows(path, BAND_COLUMNS), start=2):
        coordinate = _parse_coordinate(row, line_number)
        if coordinate in coordinates:
            raise ValueError(f"duplicate pixel coordinate: {coordinate}")
        coordinates.add(coordinate)
        bands = {
            name: _decimal(row[name], f"{name} at {coordinate}")
            for name in BAND_COLUMNS[2:]
        }
        if any(not Decimal("0") <= value <= Decimal("1") for value in bands.values()):
            raise ValueError(
                f"reflectance values must be finite and within [0, 1]: {coordinate}"
            )
        for suffix in ("before", "after"):
            if bands[f"red_{suffix}"] + bands[f"nir_{suffix}"] == 0:
                raise ValueError(
                    f"NDVI is undefined when red + NIR is zero: {coordinate} {suffix}"
                )
        pixels.append(
            BandPixel(
                row=coordinate[0],
                col=coordinate[1],
                red_before=bands["red_before"],
                nir_before=bands["nir_before"],
                red_after=bands["red_after"],
                nir_after=bands["nir_after"],
            )
        )
    return tuple(sorted(pixels, key=lambda pixel: pixel.cell))


def _read_reference_mask(path: Path) -> tuple[frozenset[Cell], frozenset[Cell]]:
    all_cells: set[Cell] = set()
    positive_cells: set[Cell] = set()
    for line_number, row in enumerate(_read_rows(path, REFERENCE_COLUMNS), start=2):
        coordinate = _parse_coordinate(row, line_number)
        if coordinate in all_cells:
            raise ValueError(f"duplicate reference coordinate: {coordinate}")
        all_cells.add(coordinate)
        label = row["reference_loss"].strip()
        if label not in {"0", "1"}:
            raise ValueError(f"reference_loss must be exactly 0 or 1 at {coordinate}")
        if label == "1":
            positive_cells.add(coordinate)
    return frozenset(all_cells), frozenset(positive_cells)


def _require_complete_grid(coordinates: Iterable[Cell], grid: GridSpec) -> None:
    actual = frozenset(coordinates)
    expected = grid.cells
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"pixel grid does not match manifest; missing={missing}, extra={extra}"
        )


def _relative_fixture_path(base: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} must stay within the manifest directory")
    base_resolved = base.resolve()
    candidate = (base_resolved / relative).resolve()
    if not candidate.is_relative_to(base_resolved):
        raise ValueError(f"{field} must stay within the manifest directory")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _load_grid(manifest: dict[str, Any]) -> GridSpec:
    try:
        grid = manifest["grid"]
        transform = manifest["geojson_transform"]
    except KeyError as exc:
        raise ValueError(f"manifest is missing required object: {exc.args[0]}") from exc
    if not isinstance(grid, dict) or not isinstance(transform, dict):
        raise ValueError("grid and geojson_transform must be objects")
    _require_exact_keys(
        grid,
        {"rows", "cols", "connectivity", "cell_width_m", "cell_height_m"},
        "grid",
    )
    _require_exact_keys(
        transform,
        {
            "kind",
            "top_left_lon",
            "top_left_lat",
            "pixel_width_deg",
            "pixel_height_deg",
            "row_direction",
        },
        "geojson_transform",
    )

    rows = _positive_int(grid.get("rows"), "grid.rows")
    cols = _positive_int(grid.get("cols"), "grid.cols")
    connectivity = grid.get("connectivity")
    if type(connectivity) is not int or connectivity not in {4, 8}:
        raise ValueError("grid.connectivity must be 4 or 8")
    cell_width_m = _positive_decimal(
        _require_decimal_string(grid.get("cell_width_m"), "grid.cell_width_m"),
        "grid.cell_width_m",
    )
    cell_height_m = _positive_decimal(
        _require_decimal_string(grid.get("cell_height_m"), "grid.cell_height_m"),
        "grid.cell_height_m",
    )

    if transform.get("kind") != "synthetic_wgs84":
        raise ValueError("geojson_transform.kind must be synthetic_wgs84")
    if transform.get("row_direction") != "south":
        raise ValueError("geojson_transform.row_direction must be south")
    top_left_lon = _decimal(
        _require_decimal_string(
            transform.get("top_left_lon"), "geojson_transform.top_left_lon"
        ),
        "geojson_transform.top_left_lon",
    )
    top_left_lat = _decimal(
        _require_decimal_string(
            transform.get("top_left_lat"), "geojson_transform.top_left_lat"
        ),
        "geojson_transform.top_left_lat",
    )
    pixel_width_deg = _positive_decimal(
        _require_decimal_string(
            transform.get("pixel_width_deg"),
            "geojson_transform.pixel_width_deg",
        ),
        "geojson_transform.pixel_width_deg",
    )
    pixel_height_deg = _positive_decimal(
        _require_decimal_string(
            transform.get("pixel_height_deg"),
            "geojson_transform.pixel_height_deg",
        ),
        "geojson_transform.pixel_height_deg",
    )
    east = top_left_lon + pixel_width_deg * cols
    south = top_left_lat - pixel_height_deg * rows
    if not Decimal("-180") <= top_left_lon <= east <= Decimal("180"):
        raise ValueError(
            "synthetic GeoJSON longitude bounds must stay within [-180, 180]"
        )
    if not Decimal("-90") <= south <= top_left_lat <= Decimal("90"):
        raise ValueError("synthetic GeoJSON latitude bounds must stay within [-90, 90]")
    return GridSpec(
        rows=rows,
        cols=cols,
        connectivity=connectivity,
        cell_width_m=cell_width_m,
        cell_height_m=cell_height_m,
        top_left_lon=top_left_lon,
        top_left_lat=top_left_lat,
        pixel_width_deg=pixel_width_deg,
        pixel_height_deg=pixel_height_deg,
    )


def load_forest_case(path: str | Path) -> ForestCase:
    """Load and fully validate a manifest-based synthetic forest case."""
    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("forest case manifest must be a JSON object")
    allowed_keys = {
        "schema_version",
        "case_id",
        "classification",
        "relation_to_trade_case",
        "files",
        "grid",
        "thresholds",
        "geojson_transform",
        "reference",
    }
    extra_keys = sorted(set(manifest) - allowed_keys)
    if extra_keys:
        raise ValueError(
            f"unsupported forest manifest properties: {', '.join(extra_keys)}"
        )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported forest schema_version; expected {SCHEMA_VERSION}"
        )

    for field in ("case_id", "classification", "relation_to_trade_case"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"manifest.{field} must be a non-empty string")
    if manifest["classification"] != "synthetic_reference_mask_evaluation":
        raise ValueError(
            "manifest.classification must be synthetic_reference_mask_evaluation"
        )
    reference = manifest.get("reference")
    if not isinstance(reference, dict):
        raise ValueError("manifest.reference must be an object")
    _require_exact_keys(reference, {"label", "provenance"}, "manifest.reference")
    for field in ("label", "provenance"):
        if not isinstance(reference.get(field), str) or not reference[field].strip():
            raise ValueError(f"manifest.reference.{field} must be a non-empty string")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("manifest.files must be an object")
    extra_files = sorted(set(files) - {"pixels", "reference_mask"})
    if extra_files:
        raise ValueError(
            f"unsupported manifest.files properties: {', '.join(extra_files)}"
        )

    grid = _load_grid(manifest)
    thresholds = manifest.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("manifest.thresholds must be an object")
    _require_exact_keys(
        thresholds,
        {"forest_ndvi_min", "ndvi_decrease_min"},
        "manifest.thresholds",
    )
    forest_threshold = _bounded_threshold(
        _require_decimal_string(
            thresholds.get("forest_ndvi_min"), "thresholds.forest_ndvi_min"
        ),
        "thresholds.forest_ndvi_min",
        minimum=Decimal("-1"),
        maximum=Decimal("1"),
    )
    loss_threshold = _bounded_threshold(
        _require_decimal_string(
            thresholds.get("ndvi_decrease_min"), "thresholds.ndvi_decrease_min"
        ),
        "thresholds.ndvi_decrease_min",
        minimum=Decimal("0"),
        maximum=Decimal("2"),
    )
    pixel_path = _relative_fixture_path(
        manifest_path.parent, files.get("pixels"), "files.pixels"
    )
    reference_path = _relative_fixture_path(
        manifest_path.parent,
        files.get("reference_mask"),
        "files.reference_mask",
    )
    pixels = _read_band_pixels(pixel_path)
    reference_coordinates, reference_mask = _read_reference_mask(reference_path)
    _require_complete_grid((pixel.cell for pixel in pixels), grid)
    _require_complete_grid(reference_coordinates, grid)
    return ForestCase(
        schema_version=manifest["schema_version"],
        case_id=manifest["case_id"],
        classification=manifest["classification"],
        relation_to_trade_case=manifest["relation_to_trade_case"],
        grid=grid,
        forest_threshold=forest_threshold,
        loss_threshold=loss_threshold,
        pixels=pixels,
        reference_mask=reference_mask,
        reference_provenance=reference["provenance"],
    )


def _predict(
    pixels: Iterable[BandPixel],
    *,
    forest_threshold: Decimal,
    loss_threshold: Decimal,
    reference_mask: frozenset[Cell] | None,
) -> tuple[PixelResult, ...]:
    results: list[PixelResult] = []
    for pixel in sorted(pixels, key=lambda item: item.cell):
        before = _ndvi_decimal(pixel.red_before, pixel.nir_before)
        after = _ndvi_decimal(pixel.red_after, pixel.nir_after)
        change = after - before
        predicted_loss = before >= forest_threshold and change <= -loss_threshold
        results.append(
            PixelResult(
                row=pixel.row,
                col=pixel.col,
                ndvi_before=before,
                ndvi_after=after,
                ndvi_change=change,
                predicted_loss=predicted_loss,
                reference_loss=(
                    pixel.cell in reference_mask if reference_mask is not None else None
                ),
            )
        )
    return tuple(results)


def connected_components(
    mask: Iterable[Cell],
    *,
    rows: int,
    cols: int,
    connectivity: int = 4,
) -> tuple[tuple[Cell, ...], ...]:
    """Return stable row-major connected components for a binary grid mask."""
    rows = _positive_int(rows, "rows")
    cols = _positive_int(cols, "cols")
    if connectivity not in {4, 8}:
        raise ValueError("connectivity must be 4 or 8")
    remaining = set(mask)
    if any(not (0 <= row < rows and 0 <= col < cols) for row, col in remaining):
        raise ValueError("mask contains a coordinate outside the grid")
    offsets = [(-1, 0), (0, -1), (0, 1), (1, 0)]
    if connectivity == 8:
        offsets.extend([(-1, -1), (-1, 1), (1, -1), (1, 1)])

    components: list[tuple[Cell, ...]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        stack = [seed]
        cells: list[Cell] = []
        while stack:
            row, col = stack.pop()
            cells.append((row, col))
            for row_delta, col_delta in offsets:
                neighbor = row + row_delta, col + col_delta
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        components.append(tuple(sorted(cells)))
    return tuple(components)


def evaluate_binary_mask(
    predicted_mask: Iterable[Cell],
    reference_mask: Iterable[Cell],
    universe: Iterable[Cell],
) -> dict[str, Any]:
    """Evaluate the positive loss class with explicit zero-denominator policy."""
    predicted = frozenset(predicted_mask)
    reference = frozenset(reference_mask)
    all_cells = frozenset(universe)
    if not all_cells:
        raise ValueError("evaluation universe must not be empty")
    if not predicted <= all_cells or not reference <= all_cells:
        raise ValueError("prediction and reference masks must be subsets of the grid")
    tp = len(predicted & reference)
    fp = len(predicted - reference)
    fn = len(reference - predicted)
    tn = len(all_cells - predicted - reference)

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, METRIC_DIGITS) if denominator else None

    metrics = {
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "iou": ratio(tp, tp + fp + fn),
    }
    return {
        "scope": "synthetic pixel-level reference-mask evaluation",
        "positive_class": "loss",
        "evaluated_pixel_count": len(all_cells),
        "predicted_positive_count": len(predicted),
        "reference_positive_count": len(reference),
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "metrics": metrics,
        "undefined_metrics": [name for name, value in metrics.items() if value is None],
        "metric_policy": {
            "round_digits": METRIC_DIGITS,
            "zero_denominator": "null",
        },
    }


def _rounded(value: Decimal, digits: int = 4) -> float:
    return round(float(value), digits)


def _regions(
    components: Iterable[tuple[Cell, ...]],
    pixel_area_m2: Decimal,
) -> list[dict[str, Any]]:
    return [
        {
            "region_id": index,
            "pixel_count": len(cells),
            "area_m2": round(float(pixel_area_m2 * len(cells)), 2),
            "cells": [{"row": row, "col": col} for row, col in cells],
        }
        for index, cells in enumerate(components, start=1)
    ]


def _pixel_payload(pixel: PixelResult, *, include_reference: bool) -> dict[str, Any]:
    payload = {
        "row": pixel.row,
        "col": pixel.col,
        "ndvi_before": _rounded(pixel.ndvi_before),
        "ndvi_after": _rounded(pixel.ndvi_after),
        "ndvi_change": _rounded(pixel.ndvi_change),
        "loss_flag": pixel.predicted_loss,
    }
    if include_reference:
        payload.update(
            {
                "reference_loss": pixel.reference_loss,
                "confusion_class": pixel.confusion_class,
            }
        )
    return payload


def _summary(
    pixels: tuple[PixelResult, ...],
    regions: list[dict[str, Any]],
    pixel_area_m2: Decimal,
) -> dict[str, Any]:
    loss_count = sum(pixel.predicted_loss for pixel in pixels)
    mean_before = sum((pixel.ndvi_before for pixel in pixels), Decimal("0")) / len(
        pixels
    )
    mean_after = sum((pixel.ndvi_after for pixel in pixels), Decimal("0")) / len(pixels)
    return {
        "loss_pixel_count": loss_count,
        "loss_share": round(loss_count / len(pixels), 4),
        "loss_area_m2": round(float(pixel_area_m2 * loss_count), 2),
        "contiguous_region_count": len(regions),
        "largest_region_pixel_count": max(
            (region["pixel_count"] for region in regions), default=0
        ),
        "mean_ndvi_before": _rounded(mean_before),
        "mean_ndvi_after": _rounded(mean_after),
        "mean_ndvi_change": _rounded(mean_after - mean_before),
    }


def analyze_forest_case(path: str | Path) -> dict[str, Any]:
    """Run manifest-based detection, components, and reference-mask evaluation."""
    case = load_forest_case(path)
    pixels = _predict(
        case.pixels,
        forest_threshold=case.forest_threshold,
        loss_threshold=case.loss_threshold,
        reference_mask=case.reference_mask,
    )
    predicted_mask = frozenset(pixel.cell for pixel in pixels if pixel.predicted_loss)
    components = connected_components(
        predicted_mask,
        rows=case.grid.rows,
        cols=case.grid.cols,
        connectivity=case.grid.connectivity,
    )
    regions = _regions(components, case.grid.pixel_area_m2)
    return {
        "schema_version": case.schema_version,
        "case_id": case.case_id,
        "relation_to_trade_case": case.relation_to_trade_case,
        "classification": case.classification,
        "input": "synthetic red/NIR pixel grid + synthetic reference mask",
        "method": "NDVI=(NIR−Red)/(NIR+Red); loss when baseline NDVI and decrease exceed explicit thresholds",
        "thresholds": {
            "forest_ndvi_min": float(case.forest_threshold),
            "ndvi_decrease_min": float(case.loss_threshold),
            "synthetic_pixel_area_m2": float(case.grid.pixel_area_m2),
        },
        "grid": {
            "rows": case.grid.rows,
            "cols": case.grid.cols,
            "pixel_count": len(pixels),
            "connectivity": case.grid.connectivity,
            "cell_width_m": float(case.grid.cell_width_m),
            "cell_height_m": float(case.grid.cell_height_m),
        },
        "summary": _summary(pixels, regions, case.grid.pixel_area_m2),
        "evaluation": evaluate_binary_mask(
            predicted_mask, case.reference_mask, case.grid.cells
        ),
        "regions": regions,
        "pixels": [_pixel_payload(pixel, include_reference=True) for pixel in pixels],
        "geojson_transform": {
            "kind": "synthetic_wgs84",
            "top_left_lon": float(case.grid.top_left_lon),
            "top_left_lat": float(case.grid.top_left_lat),
            "pixel_width_deg": float(case.grid.pixel_width_deg),
            "pixel_height_deg": float(case.grid.pixel_height_deg),
            "row_direction": "south",
        },
        "reference": {
            "label": "synthetic reference mask",
            "provenance": case.reference_provenance,
        },
        "limitations": [
            "합성 픽셀과 합성 reference mask로 코드 경로와 평가 산식만 확인합니다.",
            "이 지표는 실제 위성 영상이나 운영 모델의 일반화 성능이 아닙니다.",
            "운영용 위성 분류기, 현장 검증, EUDR 적합성 판정을 대체하지 않습니다.",
        ],
    }


def analyze_forest_change(
    path: str | Path,
    *,
    forest_threshold: float = 0.45,
    loss_threshold: float = 0.25,
    pixel_area_m2: float = 100.0,
) -> dict[str, Any]:
    """Compatibility wrapper for the original band-only CSV baseline."""
    forest_limit = _bounded_threshold(
        forest_threshold,
        "forest threshold",
        minimum=Decimal("-1"),
        maximum=Decimal("1"),
    )
    loss_limit = _bounded_threshold(
        loss_threshold,
        "loss threshold",
        minimum=Decimal("0"),
        maximum=Decimal("2"),
    )
    area = _positive_decimal(pixel_area_m2, "synthetic pixel area")
    bands = _read_band_pixels(Path(path))
    rows = max(pixel.row for pixel in bands) + 1
    cols = max(pixel.col for pixel in bands) + 1
    legacy_grid = GridSpec(
        rows=rows,
        cols=cols,
        connectivity=4,
        cell_width_m=area,
        cell_height_m=Decimal("1"),
        top_left_lon=Decimal("0"),
        top_left_lat=Decimal("0"),
        pixel_width_deg=Decimal("1"),
        pixel_height_deg=Decimal("1"),
    )
    _require_complete_grid((pixel.cell for pixel in bands), legacy_grid)
    pixels = _predict(
        bands,
        forest_threshold=forest_limit,
        loss_threshold=loss_limit,
        reference_mask=None,
    )
    predicted_mask = frozenset(pixel.cell for pixel in pixels if pixel.predicted_loss)
    components = connected_components(predicted_mask, rows=rows, cols=cols)
    regions = _regions(components, area)
    return {
        "case_id": "ECO-FOREST-SYN-2026-001",
        "relation_to_trade_case": "independent synthetic technical baseline",
        "classification": "reconstructed_public_baseline",
        "input": "synthetic red/NIR pixel grid",
        "method": "NDVI=(NIR−Red)/(NIR+Red); loss when baseline NDVI and decrease exceed explicit thresholds",
        "thresholds": {
            "forest_ndvi_min": float(forest_limit),
            "ndvi_decrease_min": float(loss_limit),
            "synthetic_pixel_area_m2": float(area),
        },
        "grid": {"rows": rows, "cols": cols, "pixel_count": len(pixels)},
        "summary": _summary(pixels, regions, area),
        "regions": regions,
        "pixels": [_pixel_payload(pixel, include_reference=False) for pixel in pixels],
        "limitations": [
            "합성 픽셀로 임계값과 산식의 재현성만 확인합니다.",
            "운영용 위성 분류기, 현장 검증, EUDR 적합성 판정을 대체하지 않습니다.",
            "대회 당시의 CNN/XAI 정확도를 재현하거나 주장하지 않습니다.",
        ],
    }


def _geo_number(value: Decimal) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def build_regions_geojson(result: dict[str, Any]) -> dict[str, Any]:
    """Return an RFC 7946 FeatureCollection for every synthetic grid cell."""
    transform = result.get("geojson_transform")
    evaluation = result.get("evaluation")
    if not isinstance(transform, dict) or not isinstance(evaluation, dict):
        raise ValueError("GeoJSON export requires a manifest-based evaluated result")
    origin_lon = _decimal(transform["top_left_lon"], "top_left_lon")
    origin_lat = _decimal(transform["top_left_lat"], "top_left_lat")
    width = _positive_decimal(transform["pixel_width_deg"], "pixel_width_deg")
    height = _positive_decimal(transform["pixel_height_deg"], "pixel_height_deg")
    rows = result["grid"]["rows"]
    cols = result["grid"]["cols"]
    area = result["thresholds"]["synthetic_pixel_area_m2"]
    cell_to_region = {
        (cell["row"], cell["col"]): region["region_id"]
        for region in result["regions"]
        for cell in region["cells"]
    }
    features: list[dict[str, Any]] = []
    for pixel in sorted(result["pixels"], key=lambda item: (item["row"], item["col"])):
        row, col = pixel["row"], pixel["col"]
        west = origin_lon + width * col
        east = west + width
        north = origin_lat - height * row
        south = north - height
        ring = [
            [_geo_number(west), _geo_number(north)],
            [_geo_number(west), _geo_number(south)],
            [_geo_number(east), _geo_number(south)],
            [_geo_number(east), _geo_number(north)],
            [_geo_number(west), _geo_number(north)],
        ]
        features.append(
            {
                "type": "Feature",
                "id": f"cell-r{row:03d}-c{col:03d}",
                "properties": {
                    "case_id": result["case_id"],
                    "row": row,
                    "col": col,
                    "predicted_loss": pixel["loss_flag"],
                    "reference_loss": pixel["reference_loss"],
                    "confusion_class": pixel["confusion_class"],
                    "region_id": cell_to_region.get((row, col)),
                    "ndvi_before": pixel["ndvi_before"],
                    "ndvi_after": pixel["ndvi_after"],
                    "ndvi_change": pixel["ndvi_change"],
                    "synthetic_geometry": True,
                    "cell_area_m2": area,
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    east = origin_lon + width * cols
    south = origin_lat - height * rows
    return {
        "type": "FeatureCollection",
        "name": "ecoguard_synthetic_forest_mask_evaluation",
        "bbox": [
            _geo_number(origin_lon),
            _geo_number(south),
            _geo_number(east),
            _geo_number(origin_lat),
        ],
        "metadata": {
            "case_id": result["case_id"],
            "synthetic_geometry": True,
            "scope": evaluation["scope"],
            "connectivity": result["grid"]["connectivity"],
            "confusion_matrix": evaluation["confusion_matrix"],
            "metrics": evaluation["metrics"],
        },
        "features": features,
    }


def _legacy_svg(result: dict[str, Any]) -> str:
    cell = 62
    gap = 6
    rows = result["grid"]["rows"]
    cols = result["grid"]["cols"]
    width = cols * (cell + gap) + 40
    height = rows * (cell + gap) + 105
    blocks: list[str] = []
    for pixel in result["pixels"]:
        x = 20 + pixel["col"] * (cell + gap)
        y = 58 + pixel["row"] * (cell + gap)
        fill = "#b83a30" if pixel["loss_flag"] else "#08775c"
        label = "LOSS" if pixel["loss_flag"] else "OK"
        blocks.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="10" '
            f'fill="{fill}" opacity="0.92"/>'
        )
        blocks.append(
            f'<text x="{x + cell / 2}" y="{y + 29}" text-anchor="middle" '
            f'font-size="12" font-weight="700" fill="white">{label}</text>'
        )
        blocks.append(
            f'<text x="{x + cell / 2}" y="{y + 46}" text-anchor="middle" '
            f'font-size="10" fill="white">{pixel["ndvi_change"]:+.2f}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Synthetic NDVI change grid" font-family="Paperlogy, sans-serif">'
        '<rect width="100%" height="100%" rx="18" fill="#f2f7f4"/>'
        '<text x="20" y="30" font-size="17" font-weight="700" fill="#123c35">'
        "Synthetic NDVI change evidence</text>"
        '<text x="20" y="48" font-size="11" fill="#55706b">'
        "Red = threshold-based loss flag · labels show NDVI change</text>"
        + "".join(blocks)
        + '<text x="20" y="'
        + str(height - 16)
        + '" font-size="10" fill="#55706b">'
        "Educational reconstructed baseline — not an EUDR compliance determination</text>"
        "</svg>"
    )


def render_change_svg(result: dict[str, Any]) -> str:
    """Render a stable legacy mask or a TP/FP/FN/TN evaluation grid."""
    if "evaluation" not in result:
        return _legacy_svg(result)

    cell = 62
    gap = 6
    rows = result["grid"]["rows"]
    cols = result["grid"]["cols"]
    width = cols * (cell + gap) + 40
    height = rows * (cell + gap) + 165
    grid_top = 105
    palette = {
        "tp": ("#08775c", "white"),
        "fp": ("#e8890c", "#123c35"),
        "fn": ("#7c3aed", "white"),
        "tn": ("#dbe7e3", "#123c35"),
    }
    blocks: list[str] = []
    for pixel in sorted(result["pixels"], key=lambda item: (item["row"], item["col"])):
        x = 20 + pixel["col"] * (cell + gap)
        y = grid_top + pixel["row"] * (cell + gap)
        category = pixel["confusion_class"]
        fill, ink = palette[category]
        blocks.append(
            f'<rect data-class="{category}" x="{x}" y="{y}" width="{cell}" '
            f'height="{cell}" rx="10" fill="{fill}" opacity="0.94"/>'
        )
        blocks.append(
            f'<text x="{x + cell / 2}" y="{y + 29}" text-anchor="middle" '
            f'font-size="12" font-weight="700" fill="{ink}">{category.upper()}</text>'
        )
        blocks.append(
            f'<text x="{x + cell / 2}" y="{y + 46}" text-anchor="middle" '
            f'font-size="10" fill="{ink}">{pixel["ndvi_change"]:+.2f}</text>'
        )
    metrics = result["evaluation"]["metrics"]
    metric_text = " · ".join(
        f"{name.upper()}={value:.3f}" if value is not None else f"{name.upper()}=N/A"
        for name, value in metrics.items()
    )
    legend = "".join(
        f'<rect x="{20 + index * 92}" y="79" width="12" height="12" rx="3" '
        f'fill="{fill}"/>'
        f'<text x="{38 + index * 92}" y="90" font-size="11" font-weight="700" '
        f'fill="#123c35">{name.upper()}</text>'
        for index, (name, (fill, _)) in enumerate(palette.items())
    )
    case_id = html.escape(str(result["case_id"]))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="forest-title forest-desc" font-family="Paperlogy, sans-serif">'
        f'<title id="forest-title">Synthetic forest reference-mask evaluation — {case_id}</title>'
        '<desc id="forest-desc">Grid cells compare threshold predictions with a synthetic '
        "reference mask using true positive, false positive, false negative and true negative classes.</desc>"
        '<rect width="100%" height="100%" rx="18" fill="#f2f7f4"/>'
        '<text x="20" y="28" font-size="17" font-weight="700" fill="#123c35">'
        "Synthetic NDVI mask evaluation</text>"
        f'<text x="20" y="49" font-size="11" fill="#55706b">{metric_text}</text>'
        '<text x="20" y="69" font-size="10" fill="#55706b">'
        "Synthetic reference mask — not real-world model accuracy</text>"
        + legend
        + "".join(blocks)
        + f'<text x="20" y="{height - 16}" font-size="10" fill="#55706b">'
        "Educational reconstructed baseline — not an EUDR compliance determination</text>"
        "</svg>"
    )
