"""Deterministic NDVI change baseline over a tiny synthetic pixel grid."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


def ndvi(red: float, nir: float) -> float:
    denominator = nir + red
    if denominator == 0:
        raise ValueError("NDVI is undefined when red + NIR is zero")
    return (nir - red) / denominator


def _connected_regions(
    pixels: list[dict[str, Any]],
    *,
    pixel_area_m2: float,
) -> list[dict[str, Any]]:
    remaining = {
        (pixel["row"], pixel["col"])
        for pixel in pixels
        if pixel["loss_flag"]
    }
    regions: list[dict[str, Any]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        stack = [seed]
        cells: list[tuple[int, int]] = []
        while stack:
            row, col = stack.pop()
            cells.append((row, col))
            for neighbor in (
                (row - 1, col),
                (row + 1, col),
                (row, col - 1),
                (row, col + 1),
            ):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        cells.sort()
        regions.append(
            {
                "region_id": len(regions) + 1,
                "pixel_count": len(cells),
                "area_m2": round(len(cells) * pixel_area_m2, 2),
                "cells": [{"row": row, "col": col} for row, col in cells],
            }
        )
    return regions


def analyze_forest_change(
    path: str | Path,
    *,
    forest_threshold: float = 0.45,
    loss_threshold: float = 0.25,
    pixel_area_m2: float = 100.0,
) -> dict[str, Any]:
    """Flag pixels that were vegetated and show a material NDVI decrease."""
    if not math.isfinite(pixel_area_m2) or pixel_area_m2 <= 0:
        raise ValueError("synthetic pixel area must be a positive finite number")
    if not math.isfinite(forest_threshold) or not -1 <= forest_threshold <= 1:
        raise ValueError("forest NDVI threshold must be finite and within [-1, 1]")
    if not math.isfinite(loss_threshold) or not 0 <= loss_threshold <= 2:
        raise ValueError("NDVI decrease threshold must be finite and within [0, 2]")

    pixels: list[dict[str, Any]] = []
    coordinates: set[tuple[int, int]] = set()
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            coordinate = (int(row["row"]), int(row["col"]))
            if coordinate[0] < 0 or coordinate[1] < 0:
                raise ValueError(f"pixel coordinate must be non-negative: {coordinate}")
            if coordinate in coordinates:
                raise ValueError(f"duplicate pixel coordinate: {coordinate}")
            coordinates.add(coordinate)
            bands = {
                name: float(row[name])
                for name in ("red_before", "nir_before", "red_after", "nir_after")
            }
            if any(
                not math.isfinite(value) or not 0 <= value <= 1
                for value in bands.values()
            ):
                raise ValueError(
                    f"reflectance values must be finite and within [0, 1]: {coordinate}"
                )
            before = ndvi(bands["red_before"], bands["nir_before"])
            after = ndvi(bands["red_after"], bands["nir_after"])
            change = after - before
            loss = before >= forest_threshold and change <= -loss_threshold
            pixels.append(
                {
                    "row": coordinate[0],
                    "col": coordinate[1],
                    "ndvi_before": round(before, 4),
                    "ndvi_after": round(after, 4),
                    "ndvi_change": round(change, 4),
                    "loss_flag": loss,
                }
            )

    if not pixels:
        raise ValueError("forest pixel fixture is empty")
    loss_count = sum(1 for pixel in pixels if pixel["loss_flag"])
    regions = _connected_regions(pixels, pixel_area_m2=pixel_area_m2)
    average_before = sum(pixel["ndvi_before"] for pixel in pixels) / len(pixels)
    average_after = sum(pixel["ndvi_after"] for pixel in pixels) / len(pixels)
    rows = max(pixel["row"] for pixel in pixels) + 1
    cols = max(pixel["col"] for pixel in pixels) + 1
    expected_coordinates = {
        (row, col) for row in range(rows) for col in range(cols)
    }
    if coordinates != expected_coordinates:
        missing = sorted(expected_coordinates - coordinates)
        raise ValueError(f"pixel grid is not complete; missing coordinates: {missing}")
    return {
        "case_id": "ECO-FOREST-SYN-2026-001",
        "relation_to_trade_case": "independent synthetic technical baseline",
        "classification": "reconstructed_public_baseline",
        "input": "synthetic red/NIR pixel grid",
        "method": "NDVI=(NIR−Red)/(NIR+Red); loss when baseline NDVI and decrease exceed explicit thresholds",
        "thresholds": {
            "forest_ndvi_min": forest_threshold,
            "ndvi_decrease_min": loss_threshold,
            "synthetic_pixel_area_m2": pixel_area_m2,
        },
        "grid": {"rows": rows, "cols": cols, "pixel_count": len(pixels)},
        "summary": {
            "loss_pixel_count": loss_count,
            "loss_share": round(loss_count / len(pixels), 4),
            "loss_area_m2": round(loss_count * pixel_area_m2, 2),
            "contiguous_region_count": len(regions),
            "largest_region_pixel_count": max(
                (region["pixel_count"] for region in regions),
                default=0,
            ),
            "mean_ndvi_before": round(average_before, 4),
            "mean_ndvi_after": round(average_after, 4),
            "mean_ndvi_change": round(average_after - average_before, 4),
        },
        "regions": regions,
        "pixels": pixels,
        "limitations": [
            "합성 픽셀로 임계값과 산식의 재현성만 확인합니다.",
            "운영용 위성 분류기, 현장 검증, EUDR 적합성 판정을 대체하지 않습니다.",
            "대회 당시의 CNN/XAI 정확도를 재현하거나 주장하지 않습니다.",
        ],
    }


def render_change_svg(result: dict[str, Any]) -> str:
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
        fill = "#f05a47" if pixel["loss_flag"] else "#2da57b"
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
        f'aria-label="Synthetic NDVI change grid">'
        '<rect width="100%" height="100%" rx="18" fill="#f2f7f4"/>'
        '<text x="20" y="30" font-size="17" font-weight="700" fill="#123c35">'
        'Synthetic NDVI change evidence</text>'
        '<text x="20" y="48" font-size="11" fill="#55706b">'
        'Red = threshold-based loss flag · labels show NDVI change</text>'
        + "".join(blocks)
        + '<text x="20" y="'
        + str(height - 16)
        + '" font-size="10" fill="#55706b">'
        'Educational reconstructed baseline — not an EUDR compliance determination</text>'
        '</svg>'
    )
