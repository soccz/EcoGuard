"""Dependency-free geospatial contract checks for a synthetic forest benchmark.

This module deliberately validates geospatial *plumbing*, not remote-sensing model
accuracy.  The committed fixture is synthetic and the optional public-data manifest
is never accessed by this runtime path.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Sequence

from .jsonio import strict_json_loads

Cell = tuple[int, int]
SCHEMA_VERSION = "forest-geospatial-benchmark/1.0"
ANALYSIS_SCHEMA_VERSION = "forest-geospatial-analysis/1.0"
SUMMARY_SCHEMA_VERSION = "forest-geospatial-summary/1.0"
PIXEL_COLUMNS = (
    "row",
    "col",
    "red_before",
    "nir_before",
    "qa_before",
    "red_after",
    "nir_after",
    "qa_after",
)
REFERENCE_COLUMNS = ("row", "col", "reference_loss")
SUPPORTED_CRS = {
    (
        "EPSG",
        32652,
        "WGS 84 / UTM zone 52N",
        "projected",
        "metre",
    )
}
METRIC_DIGITS = 6
DECIMAL_STRING_PATTERN = re.compile(r"-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


@dataclass(frozen=True)
class AffineTransform:
    """GDAL-order affine transform with exact Decimal coefficients."""

    x_origin: Decimal
    pixel_width: Decimal
    row_rotation: Decimal
    y_origin: Decimal
    col_rotation: Decimal
    pixel_height: Decimal

    @property
    def coefficients(self) -> tuple[Decimal, ...]:
        return (
            self.x_origin,
            self.pixel_width,
            self.row_rotation,
            self.y_origin,
            self.col_rotation,
            self.pixel_height,
        )

    @property
    def determinant(self) -> Decimal:
        return (
            self.pixel_width * self.pixel_height - self.row_rotation * self.col_rotation
        )

    @property
    def pixel_area(self) -> Decimal:
        return abs(self.determinant)

    def coordinate(self, row: int, col: int) -> tuple[Decimal, Decimal]:
        x = self.x_origin + col * self.pixel_width + row * self.row_rotation
        y = self.y_origin + col * self.col_rotation + row * self.pixel_height
        return x, y


@dataclass(frozen=True)
class Tile:
    tile_id: str
    row_start: int
    row_stop: int
    col_start: int
    col_stop: int

    @property
    def pixel_count(self) -> int:
        return (self.row_stop - self.row_start) * (self.col_stop - self.col_start)


@dataclass(frozen=True)
class ScenePixel:
    row: int
    col: int
    red_before: Decimal
    nir_before: Decimal
    qa_before: str
    red_after: Decimal
    nir_after: Decimal
    qa_after: str

    @property
    def cell(self) -> Cell:
        return self.row, self.col


@dataclass(frozen=True)
class GeospatialBenchmark:
    benchmark_id: str
    classification: str
    purpose: str
    claim_boundary: dict[str, list[str]]
    rows: int
    cols: int
    crs: dict[str, Any]
    transform: AffineTransform
    nodata_value: Decimal
    before: dict[str, str]
    after: dict[str, str]
    before_time: datetime
    after_time: datetime
    seasonality_policy: dict[str, Any]
    masking: dict[str, Any]
    forest_threshold: Decimal
    loss_threshold: Decimal
    threshold_provenance: str
    tiles: tuple[Tile, ...]
    holdout_tile_ids: frozenset[str]
    split_provenance: str
    reference: dict[str, Any]
    pixels: tuple[ScenePixel, ...]
    reference_mask: frozenset[Cell]
    input_provenance: dict[str, dict[str, Any]]


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ValueError(f"{field} contract mismatch; missing={missing}, extra={extra}")


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    parsed = [_text(item, f"{field} item") for item in value]
    if len(parsed) != len(set(parsed)):
        raise ValueError(f"{field} must not contain duplicates")
    return parsed


def _decimal(value: Any, field: str, *, require_string: bool = False) -> Decimal:
    if require_string and (
        not isinstance(value, str) or DECIMAL_STRING_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _utc_datetime(value: Any, field: str) -> datetime:
    text = _text(value, field)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ValueError(
            f"{field} must be a whole-second UTC timestamp ending in Z"
        ) from exc
    return parsed


def _relative_file(base: Path, value: Any, field: str) -> tuple[Path, str]:
    relative_text = _text(value, field)
    relative = Path(relative_text)
    if (
        relative.is_absolute()
        or len(relative.parts) != 1
        or relative.name != relative_text
    ):
        raise ValueError(f"{field} must name a file in the manifest directory")
    base_resolved = base.resolve()
    candidate = (base_resolved / relative).resolve()
    if not candidate.is_relative_to(base_resolved):
        raise ValueError(f"{field} must stay within the manifest directory")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate, relative_text


def _file_evidence(path: Path, relative_name: str) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "file": relative_name,
        "bytes": len(content),
        "sha256": sha256(content).hexdigest(),
    }


def _read_csv(path: Path, expected: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != expected:
            raise ValueError(f"invalid columns for {path.name}; expected {expected}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"CSV fixture is empty: {path.name}")
    for row in rows:
        if None in row or any(
            value is None or not value.strip() for value in row.values()
        ):
            raise ValueError(
                f"CSV fixture contains a blank or extra value: {path.name}"
            )
    return rows


def _coordinate(row: dict[str, str], line_number: int) -> Cell:
    try:
        cell = int(row["row"]), int(row["col"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid coordinate on CSV line {line_number}") from exc
    if cell[0] < 0 or cell[1] < 0:
        raise ValueError(f"pixel coordinates must be non-negative: {cell}")
    return cell


def deterministic_tiles(
    rows: int,
    cols: int,
    tile_height: int,
    tile_width: int,
) -> tuple[Tile, ...]:
    """Return clipped row-major tiles with stable coordinate-derived IDs."""
    rows = _positive_int(rows, "rows")
    cols = _positive_int(cols, "cols")
    tile_height = _positive_int(tile_height, "tile_height")
    tile_width = _positive_int(tile_width, "tile_width")
    return tuple(
        Tile(
            tile_id=f"tile-r{row:04d}-c{col:04d}",
            row_start=row,
            row_stop=min(row + tile_height, rows),
            col_start=col,
            col_stop=min(col + tile_width, cols),
        )
        for row in range(0, rows, tile_height)
        for col in range(0, cols, tile_width)
    )


def _load_grid(
    manifest: dict[str, Any],
) -> tuple[int, int, dict[str, Any], AffineTransform, Decimal]:
    grid = _object(manifest.get("grid"), "grid")
    _exact_keys(
        grid,
        {"rows", "cols", "crs", "geotransform", "nodata_value", "pixel_origin"},
        "grid",
    )
    rows = _positive_int(grid["rows"], "grid.rows")
    cols = _positive_int(grid["cols"], "grid.cols")
    if rows > 1_000 or cols > 1_000:
        raise ValueError("grid rows and cols must each be at most 1000")
    if rows * cols > 1_000_000:
        raise ValueError("grid is too large for this small benchmark runner")

    crs = _object(grid["crs"], "grid.crs")
    _exact_keys(crs, {"authority", "code", "name", "kind", "axis_unit"}, "grid.crs")
    signature = (
        crs.get("authority"),
        crs.get("code"),
        crs.get("name"),
        crs.get("kind"),
        crs.get("axis_unit"),
    )
    if signature not in SUPPORTED_CRS:
        raise ValueError("grid.crs is not a supported projected-metre CRS contract")
    if grid["pixel_origin"] != "upper_left_corner":
        raise ValueError("grid.pixel_origin must be upper_left_corner")

    coefficients = grid["geotransform"]
    if not isinstance(coefficients, list) or len(coefficients) != 6:
        raise ValueError("grid.geotransform must contain six GDAL-order coefficients")
    parsed = tuple(
        _decimal(value, f"grid.geotransform[{index}]", require_string=True)
        for index, value in enumerate(coefficients)
    )
    transform = AffineTransform(*parsed)
    if transform.determinant == 0:
        raise ValueError("grid.geotransform must be invertible")
    nodata = _decimal(grid["nodata_value"], "grid.nodata_value", require_string=True)
    if Decimal("0") <= nodata <= Decimal("1"):
        raise ValueError("grid.nodata_value must be outside the reflectance interval")
    return rows, cols, dict(crs), transform, nodata


def _load_scene(value: Any, field: str) -> tuple[dict[str, str], datetime]:
    scene = _object(value, field)
    expected = {
        "scene_id",
        "acquired_at",
        "season_label",
        "sensor_family",
        "product_level",
        "source_kind",
    }
    _exact_keys(scene, expected, field)
    parsed = {name: _text(scene[name], f"{field}.{name}") for name in expected}
    if parsed["source_kind"] != "team_authored_synthetic":
        raise ValueError(f"{field}.source_kind must disclose team_authored_synthetic")
    return parsed, _utc_datetime(parsed["acquired_at"], f"{field}.acquired_at")


def _load_observations(
    manifest: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], datetime, datetime, dict[str, Any]]:
    observations = _object(manifest.get("observations"), "observations")
    _exact_keys(observations, {"before", "after", "seasonality_policy"}, "observations")
    before, before_time = _load_scene(observations["before"], "observations.before")
    after, after_time = _load_scene(observations["after"], "observations.after")
    if before["scene_id"] == after["scene_id"]:
        raise ValueError("before and after scene IDs must differ")
    if after_time <= before_time:
        raise ValueError("after acquisition must be later than before acquisition")

    policy = _object(observations["seasonality_policy"], "seasonality_policy")
    _exact_keys(
        policy,
        {
            "require_same_season_label",
            "maximum_day_of_year_delta",
            "minimum_elapsed_days",
            "maximum_elapsed_days",
            "timezone",
        },
        "seasonality_policy",
    )
    if policy["require_same_season_label"] is not True:
        raise ValueError("seasonality_policy.require_same_season_label must be true")
    if policy["timezone"] != "UTC":
        raise ValueError("seasonality_policy.timezone must be UTC")
    maximum_doy = _positive_int(
        policy["maximum_day_of_year_delta"],
        "seasonality_policy.maximum_day_of_year_delta",
    )
    minimum_elapsed = _positive_int(
        policy["minimum_elapsed_days"], "seasonality_policy.minimum_elapsed_days"
    )
    maximum_elapsed = _positive_int(
        policy["maximum_elapsed_days"], "seasonality_policy.maximum_elapsed_days"
    )
    if maximum_doy > 183 or minimum_elapsed > maximum_elapsed:
        raise ValueError("seasonality policy bounds are inconsistent")
    if before["season_label"] != after["season_label"]:
        raise ValueError("acquisitions must use the same declared season label")
    day_delta = _calendar_day_delta(before_time, after_time)
    if day_delta > maximum_doy:
        raise ValueError("acquisition day-of-year delta exceeds seasonality policy")
    elapsed_seconds = int((after_time - before_time).total_seconds())
    if not minimum_elapsed * 86400 <= elapsed_seconds <= maximum_elapsed * 86400:
        raise ValueError("acquisition elapsed time exceeds seasonality policy")
    return before, after, before_time, after_time, dict(policy)


def _calendar_day_delta(before: datetime, after: datetime) -> int:
    """Return circular month/day distance on a leap-capable reference year."""
    reference_year = 2000
    before_date = before.date().replace(year=reference_year)
    after_date = after.date().replace(year=reference_year)
    direct = abs((after_date - before_date).days)
    return min(direct, 366 - direct)


def _load_masking(manifest: dict[str, Any]) -> dict[str, Any]:
    masking = _object(manifest.get("masking"), "masking")
    _exact_keys(
        masking,
        {
            "qa_clear_class",
            "qa_excluded_classes",
            "nodata_scope",
            "evaluation_scope",
        },
        "masking",
    )
    if masking["qa_clear_class"] != "clear":
        raise ValueError("masking.qa_clear_class must be clear")
    excluded = _string_list(masking["qa_excluded_classes"], "qa_excluded_classes")
    if excluded != ["cloud", "shadow"]:
        raise ValueError("masking.qa_excluded_classes must be [cloud, shadow]")
    if masking["nodata_scope"] != "any_required_band":
        raise ValueError("masking.nodata_scope must be any_required_band")
    if masking["evaluation_scope"] != "valid_holdout_pixels_only":
        raise ValueError("masking.evaluation_scope must be valid_holdout_pixels_only")
    return dict(masking)


def _load_prediction(manifest: dict[str, Any]) -> tuple[Decimal, Decimal, str]:
    rule = _object(manifest.get("prediction_rule"), "prediction_rule")
    _exact_keys(
        rule,
        {"kind", "forest_ndvi_min", "ndvi_decrease_min", "threshold_provenance"},
        "prediction_rule",
    )
    if rule["kind"] != "fixed_ndvi_threshold":
        raise ValueError("prediction_rule.kind must be fixed_ndvi_threshold")
    forest = _decimal(rule["forest_ndvi_min"], "forest_ndvi_min", require_string=True)
    loss = _decimal(rule["ndvi_decrease_min"], "ndvi_decrease_min", require_string=True)
    if not Decimal("-1") <= forest <= Decimal("1"):
        raise ValueError("forest_ndvi_min must be within [-1, 1]")
    if not Decimal("0") <= loss <= Decimal("2"):
        raise ValueError("ndvi_decrease_min must be within [0, 2]")
    return forest, loss, _text(rule["threshold_provenance"], "threshold_provenance")


def _load_tiles(
    manifest: dict[str, Any], rows: int, cols: int
) -> tuple[tuple[Tile, ...], frozenset[str], str]:
    tiling = _object(manifest.get("tiling"), "tiling")
    _exact_keys(tiling, {"tile_height", "tile_width", "order", "edge_policy"}, "tiling")
    if tiling["order"] != "row_major" or tiling["edge_policy"] != "clip":
        raise ValueError("tiling must use row_major order with clip edge policy")
    tiles = deterministic_tiles(
        rows,
        cols,
        _positive_int(tiling["tile_height"], "tiling.tile_height"),
        _positive_int(tiling["tile_width"], "tiling.tile_width"),
    )

    split = _object(manifest.get("spatial_split"), "spatial_split")
    _exact_keys(
        split,
        {
            "strategy",
            "holdout_tile_ids",
            "reported_metrics_scope",
            "selection_provenance",
        },
        "spatial_split",
    )
    if split["strategy"] != "deterministic_tile_holdout":
        raise ValueError("spatial_split.strategy must be deterministic_tile_holdout")
    if split["reported_metrics_scope"] != "valid_holdout_pixels_only":
        raise ValueError("reported metrics must be scoped to valid holdout pixels")
    holdout_list = _string_list(split["holdout_tile_ids"], "holdout_tile_ids")
    known = {tile.tile_id for tile in tiles}
    holdout = frozenset(holdout_list)
    if not holdout < known:
        raise ValueError(
            "holdout_tile_ids must be a non-empty proper subset of known tiles"
        )
    provenance = _text(split["selection_provenance"], "selection_provenance")
    return tiles, holdout, provenance


def _load_reference_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    reference = _object(manifest.get("reference"), "reference")
    _exact_keys(
        reference,
        {
            "kind",
            "creator",
            "created_at",
            "method",
            "license",
            "independent_ground_truth",
        },
        "reference",
    )
    if reference["kind"] != "team_authored_synthetic_binary_mask":
        raise ValueError("reference.kind must disclose a team-authored synthetic mask")
    if reference["independent_ground_truth"] is not False:
        raise ValueError("synthetic reference must not claim independent ground truth")
    for field in ("creator", "method", "license"):
        _text(reference[field], f"reference.{field}")
    _utc_datetime(reference["created_at"], "reference.created_at")
    return dict(reference)


def _load_pixels(
    path: Path, rows: int, cols: int, nodata: Decimal, masking: dict[str, Any]
) -> tuple[ScenePixel, ...]:
    pixels: list[ScenePixel] = []
    seen: set[Cell] = set()
    allowed_qa = {masking["qa_clear_class"], *masking["qa_excluded_classes"]}
    for line_number, row in enumerate(_read_csv(path, PIXEL_COLUMNS), start=2):
        cell = _coordinate(row, line_number)
        if cell in seen:
            raise ValueError(f"duplicate scene pixel coordinate: {cell}")
        seen.add(cell)
        bands = {
            name: _decimal(row[name], f"{name} at {cell}")
            for name in ("red_before", "nir_before", "red_after", "nir_after")
        }
        for name, value in bands.items():
            if value != nodata and not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"{name} at {cell} must be nodata or within [0, 1]")
        for name in ("qa_before", "qa_after"):
            if row[name] not in allowed_qa:
                raise ValueError(f"{name} at {cell} has an unsupported QA class")
        pixels.append(
            ScenePixel(
                row=cell[0],
                col=cell[1],
                red_before=bands["red_before"],
                nir_before=bands["nir_before"],
                qa_before=row["qa_before"],
                red_after=bands["red_after"],
                nir_after=bands["nir_after"],
                qa_after=row["qa_after"],
            )
        )
    _require_complete_grid(seen, rows, cols, "scene pixels")
    return tuple(sorted(pixels, key=lambda pixel: pixel.cell))


def _load_reference_mask(path: Path, rows: int, cols: int) -> frozenset[Cell]:
    seen: set[Cell] = set()
    positive: set[Cell] = set()
    for line_number, row in enumerate(_read_csv(path, REFERENCE_COLUMNS), start=2):
        cell = _coordinate(row, line_number)
        if cell in seen:
            raise ValueError(f"duplicate reference coordinate: {cell}")
        seen.add(cell)
        if row["reference_loss"] not in {"0", "1"}:
            raise ValueError(f"reference_loss at {cell} must be exactly 0 or 1")
        if row["reference_loss"] == "1":
            positive.add(cell)
    _require_complete_grid(seen, rows, cols, "reference mask")
    return frozenset(positive)


def _require_complete_grid(
    cells: Iterable[Cell], rows: int, cols: int, field: str
) -> None:
    actual = frozenset(cells)
    expected = frozenset((row, col) for row in range(rows) for col in range(cols))
    if actual != expected:
        raise ValueError(
            f"{field} does not match grid; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def load_geospatial_benchmark(path: str | Path) -> GeospatialBenchmark:
    """Load and fail-closed validate the synthetic geospatial benchmark contract."""
    manifest_path = Path(path)
    manifest_bytes = manifest_path.read_bytes()

    manifest = strict_json_loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("geospatial benchmark manifest must be a JSON object")
    expected_keys = {
        "schema_version",
        "benchmark_id",
        "classification",
        "purpose",
        "files",
        "grid",
        "observations",
        "masking",
        "prediction_rule",
        "tiling",
        "spatial_split",
        "reference",
        "claim_boundary",
    }
    _exact_keys(manifest, expected_keys, "benchmark manifest")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version; expected {SCHEMA_VERSION}")
    benchmark_id = _text(manifest["benchmark_id"], "benchmark_id")
    classification = _text(manifest["classification"], "classification")
    if classification != "synthetic_geospatial_plumbing_benchmark":
        raise ValueError(
            "classification must be synthetic_geospatial_plumbing_benchmark"
        )
    purpose = _text(manifest["purpose"], "purpose")

    claim_boundary = _object(manifest["claim_boundary"], "claim_boundary")
    _exact_keys(
        claim_boundary, {"demonstrates", "does_not_demonstrate"}, "claim_boundary"
    )
    claims = {
        "demonstrates": _string_list(claim_boundary["demonstrates"], "demonstrates"),
        "does_not_demonstrate": _string_list(
            claim_boundary["does_not_demonstrate"], "does_not_demonstrate"
        ),
    }
    rows, cols, crs, transform, nodata = _load_grid(manifest)
    before, after, before_time, after_time, seasonality_policy = _load_observations(
        manifest
    )
    masking = _load_masking(manifest)
    forest_threshold, loss_threshold, threshold_provenance = _load_prediction(manifest)
    tiles, holdout_tile_ids, split_provenance = _load_tiles(manifest, rows, cols)
    reference = _load_reference_metadata(manifest)

    files = _object(manifest["files"], "files")
    _exact_keys(files, {"scene_pixels", "reference_mask"}, "files")
    pixel_path, pixel_name = _relative_file(
        manifest_path.parent, files["scene_pixels"], "files.scene_pixels"
    )
    reference_path, reference_name = _relative_file(
        manifest_path.parent, files["reference_mask"], "files.reference_mask"
    )
    pixels = _load_pixels(pixel_path, rows, cols, nodata, masking)
    reference_mask = _load_reference_mask(reference_path, rows, cols)
    return GeospatialBenchmark(
        benchmark_id=benchmark_id,
        classification=classification,
        purpose=purpose,
        claim_boundary=claims,
        rows=rows,
        cols=cols,
        crs=crs,
        transform=transform,
        nodata_value=nodata,
        before=before,
        after=after,
        before_time=before_time,
        after_time=after_time,
        seasonality_policy=seasonality_policy,
        masking=masking,
        forest_threshold=forest_threshold,
        loss_threshold=loss_threshold,
        threshold_provenance=threshold_provenance,
        tiles=tiles,
        holdout_tile_ids=holdout_tile_ids,
        split_provenance=split_provenance,
        reference=reference,
        pixels=pixels,
        reference_mask=reference_mask,
        input_provenance={
            "manifest": {
                "file": manifest_path.name,
                "bytes": len(manifest_bytes),
                "sha256": sha256(manifest_bytes).hexdigest(),
            },
            "scene_pixels": _file_evidence(pixel_path, pixel_name),
            "reference_mask": _file_evidence(reference_path, reference_name),
        },
    )


def _ndvi(red: Decimal, nir: Decimal) -> Decimal:
    denominator = nir + red
    if denominator == 0:
        raise ValueError("NDVI is undefined when red + NIR is zero on a valid pixel")
    with localcontext() as context:
        context.prec = 28
        return (nir - red) / denominator


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text


def _rounded(value: Decimal | None, digits: int = METRIC_DIGITS) -> float | None:
    return None if value is None else round(float(value), digits)


def _mask_reasons(pixel: ScenePixel, case: GeospatialBenchmark) -> list[str]:
    reasons: list[str] = []
    if case.nodata_value in {pixel.red_before, pixel.nir_before}:
        reasons.append("nodata_before")
    if pixel.qa_before != case.masking["qa_clear_class"]:
        reasons.append(f"qa_before:{pixel.qa_before}")
    if case.nodata_value in {pixel.red_after, pixel.nir_after}:
        reasons.append("nodata_after")
    if pixel.qa_after != case.masking["qa_clear_class"]:
        reasons.append(f"qa_after:{pixel.qa_after}")
    return reasons


def _tile_index(case: GeospatialBenchmark) -> dict[Cell, Tile]:
    index: dict[Cell, Tile] = {}
    for tile in case.tiles:
        for row in range(tile.row_start, tile.row_stop):
            for col in range(tile.col_start, tile.col_stop):
                cell = (row, col)
                if cell in index:
                    raise ValueError(f"pixel {cell} belongs to more than one tile")
                index[cell] = tile
    expected = {(row, col) for row in range(case.rows) for col in range(case.cols)}
    if set(index) != expected:
        raise ValueError("tiles do not cover the benchmark grid exactly once")
    return index


def _confusion(predicted: bool, reference: bool) -> str:
    if predicted:
        return "tp" if reference else "fp"
    return "fn" if reference else "tn"


def _cell_payload(
    pixel: ScenePixel,
    case: GeospatialBenchmark,
    tile_index: dict[Cell, Tile],
) -> dict[str, Any]:
    reasons = _mask_reasons(pixel, case)
    valid = not reasons
    before = after = change = None
    predicted: bool | None = None
    if valid:
        before = _ndvi(pixel.red_before, pixel.nir_before)
        after = _ndvi(pixel.red_after, pixel.nir_after)
        change = after - before
        predicted = before >= case.forest_threshold and change <= -case.loss_threshold
    tile = tile_index[pixel.cell]
    split = "holdout" if tile.tile_id in case.holdout_tile_ids else "train"
    reference = pixel.cell in case.reference_mask
    included = valid and split == "holdout"
    return {
        "row": pixel.row,
        "col": pixel.col,
        "tile_id": tile.tile_id,
        "split": split,
        "valid": valid,
        "mask_reasons": reasons,
        "ndvi_before": _rounded(before),
        "ndvi_after": _rounded(after),
        "ndvi_change": _rounded(change),
        "predicted_loss": predicted,
        "reference_loss": reference,
        "evaluation_included": included,
        "confusion_class": _confusion(predicted, reference) if included else None,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, METRIC_DIGITS) if denominator else None


def _evaluation(cells: list[dict[str, Any]]) -> dict[str, Any]:
    included = [cell for cell in cells if cell["evaluation_included"]]
    counts = Counter(cell["confusion_class"] for cell in included)
    confusion = {name: counts[name] for name in ("tp", "fp", "fn", "tn")}
    tp, fp, fn = confusion["tp"], confusion["fp"], confusion["fn"]
    metrics = {
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "f1": _ratio(2 * tp, 2 * tp + fp + fn),
        "iou": _ratio(tp, tp + fp + fn),
    }
    return {
        "scope": "valid_holdout_pixels_only",
        "evaluated_pixel_count": len(included),
        "confusion_matrix": confusion,
        "metrics": metrics,
        "undefined_metrics": [name for name, value in metrics.items() if value is None],
        "caveat": (
            "Synthetic code-path metrics; the fixed rule was not trained and this is "
            "not real-world remote-sensing accuracy."
        ),
    }


def pixel_polygon(transform: AffineTransform, row: int, col: int) -> list[list[float]]:
    """Return a closed, counter-clockwise native-CRS pixel exterior ring."""
    if type(row) is not int or type(col) is not int or row < 0 or col < 0:
        raise ValueError("pixel row and col must be non-negative integers")
    points = [
        transform.coordinate(row, col),
        transform.coordinate(row, col + 1),
        transform.coordinate(row + 1, col + 1),
        transform.coordinate(row + 1, col),
    ]
    signed_twice_area = sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, [*points[1:], points[0]])
    )
    if signed_twice_area < 0:
        points = [points[0], *reversed(points[1:])]
    closed = [*points, points[0]]
    return [[float(x), float(y)] for x, y in closed]


def _bbox(transform: AffineTransform, rows: int, cols: int) -> list[float]:
    corners = (
        transform.coordinate(0, 0),
        transform.coordinate(0, cols),
        transform.coordinate(rows, cols),
        transform.coordinate(rows, 0),
    )
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]


def _temporal_summary(case: GeospatialBenchmark) -> dict[str, Any]:
    elapsed_seconds = int((case.after_time - case.before_time).total_seconds())
    day_delta = _calendar_day_delta(case.before_time, case.after_time)
    return {
        "before": dict(case.before),
        "after": dict(case.after),
        "elapsed_seconds": elapsed_seconds,
        "elapsed_days": round(elapsed_seconds / 86400, METRIC_DIGITS),
        "day_of_year_delta": day_delta,
        "same_season_label": case.before["season_label"] == case.after["season_label"],
        "seasonality_policy": dict(case.seasonality_policy),
        "policy_passed": True,
    }


def _tile_summaries(
    case: GeospatialBenchmark, cells: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    valid_counts = Counter(cell["tile_id"] for cell in cells if cell["valid"])
    summaries: list[dict[str, Any]] = []
    for tile in case.tiles:
        summaries.append(
            {
                "tile_id": tile.tile_id,
                "row_start": tile.row_start,
                "row_stop_exclusive": tile.row_stop,
                "col_start": tile.col_start,
                "col_stop_exclusive": tile.col_stop,
                "pixel_count": tile.pixel_count,
                "valid_pixel_count": valid_counts[tile.tile_id],
                "split": (
                    "holdout" if tile.tile_id in case.holdout_tile_ids else "train"
                ),
            }
        )
    return summaries


def analyze_geospatial_benchmark(path: str | Path) -> dict[str, Any]:
    """Analyze the fixed synthetic case and return serializable cells plus summary."""
    case = load_geospatial_benchmark(path)
    tile_index = _tile_index(case)
    cells = [_cell_payload(pixel, case, tile_index) for pixel in case.pixels]
    mask_counts = Counter(reason for cell in cells for reason in cell["mask_reasons"])
    split_counts = Counter(cell["split"] for cell in cells)
    holdout = [cell for cell in cells if cell["split"] == "holdout"]
    transform_text = [_decimal_text(value) for value in case.transform.coefficients]
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "benchmark": {
            "benchmark_id": case.benchmark_id,
            "classification": case.classification,
            "purpose": case.purpose,
            "claim_boundary": case.claim_boundary,
        },
        "input_provenance": case.input_provenance,
        "grid": {
            "rows": case.rows,
            "cols": case.cols,
            "pixel_count": case.rows * case.cols,
            "crs": {
                **case.crs,
                "registry_lookup_performed": False,
                "validation_scope": "fixed offline authority/code/name/unit allowlist",
            },
            "geotransform_gdal_order": transform_text,
            "pixel_area_m2": _decimal_text(case.transform.pixel_area),
            "total_grid_area_m2": _decimal_text(
                case.transform.pixel_area * case.rows * case.cols
            ),
            "bbox_native_crs": _bbox(case.transform, case.rows, case.cols),
        },
        "temporal_pair": _temporal_summary(case),
        "masking": {
            "policy": case.masking,
            "valid_pixel_count": sum(cell["valid"] for cell in cells),
            "masked_pixel_count": sum(not cell["valid"] for cell in cells),
            "mask_reason_counts": dict(sorted(mask_counts.items())),
        },
        "tiling": {
            "order": "row_major",
            "edge_policy": "clip",
            "tile_count": len(case.tiles),
            "tiles": _tile_summaries(case, cells),
        },
        "spatial_split": {
            "strategy": "deterministic_tile_holdout",
            "selection_provenance": case.split_provenance,
            "train_pixel_count": split_counts["train"],
            "holdout_pixel_count": split_counts["holdout"],
            "masked_holdout_pixel_count": sum(not cell["valid"] for cell in holdout),
            "train_tile_ids": [
                tile.tile_id
                for tile in case.tiles
                if tile.tile_id not in case.holdout_tile_ids
            ],
            "holdout_tile_ids": [
                tile.tile_id
                for tile in case.tiles
                if tile.tile_id in case.holdout_tile_ids
            ],
        },
        "reference": {
            **case.reference,
            "positive_pixel_count": len(case.reference_mask),
        },
        "prediction_rule": {
            "kind": "fixed_ndvi_threshold",
            "forest_ndvi_min": _decimal_text(case.forest_threshold),
            "ndvi_decrease_min": _decimal_text(case.loss_threshold),
            "threshold_provenance": case.threshold_provenance,
        },
        "spatial_evaluation": _evaluation(cells),
    }
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "summary": summary,
        "cells": cells,
    }


def build_geospatial_geojson(analysis: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic cell polygons in the declared native projected CRS."""
    if analysis.get("schema_version") != ANALYSIS_SCHEMA_VERSION:
        raise ValueError("unsupported geospatial analysis schema")
    summary = _object(analysis.get("summary"), "analysis.summary")
    grid = _object(summary.get("grid"), "analysis.summary.grid")
    coefficients = grid.get("geotransform_gdal_order")
    if not isinstance(coefficients, list) or len(coefficients) != 6:
        raise ValueError("analysis summary has an invalid geotransform")
    transform = AffineTransform(
        *tuple(_decimal(value, "analysis geotransform") for value in coefficients)
    )
    pixel_area = _decimal(grid.get("pixel_area_m2"), "pixel_area_m2")
    features = []
    for cell in analysis.get("cells", []):
        row, col = cell["row"], cell["col"]
        properties = dict(cell)
        properties["pixel_area_m2"] = float(pixel_area)
        features.append(
            {
                "type": "Feature",
                "id": f"cell-r{row:03d}-c{col:03d}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [pixel_polygon(transform, row, col)],
                },
                "properties": properties,
            }
        )
    crs = dict(grid["crs"])
    return {
        "type": "FeatureCollection",
        "name": "ecoguard_synthetic_geospatial_plumbing_benchmark",
        "bbox": grid["bbox_native_crs"],
        "coordinate_reference_system": {
            "authority": crs["authority"],
            "code": crs["code"],
            "name": crs["name"],
            "axis_unit": crs["axis_unit"],
            "coordinate_space": "native_projected",
            "rfc7946_wgs84": False,
            "note": (
                "Native projected coordinates are retained to test affine geometry; "
                "reproject before RFC 7946 interchange."
            ),
        },
        "benchmark": summary["benchmark"],
        "features": features,
    }


def canonical_json(payload: Any) -> str:
    """Serialize benchmark outputs in a stable, strict JSON representation."""
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run EcoGuard's synthetic geospatial plumbing benchmark."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--summary", type=Path, help="write benchmark summary JSON")
    parser.add_argument("--geojson", type=Path, help="write cell-level GeoJSON")
    args = parser.parse_args(argv)
    analysis = analyze_geospatial_benchmark(args.manifest)
    if args.summary:
        _write_json(args.summary, analysis["summary"])
    if args.geojson:
        _write_json(args.geojson, build_geospatial_geojson(analysis))
    if not args.summary and not args.geojson:
        print(canonical_json(analysis["summary"]), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
