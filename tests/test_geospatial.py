import copy
import io
import json
import shutil
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from ecoguard.geospatial import (
    ANALYSIS_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    AffineTransform,
    analyze_geospatial_benchmark,
    build_geospatial_geojson,
    canonical_json,
    deterministic_tiles,
    load_geospatial_benchmark,
    main,
    pixel_polygon,
)

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "data/benchmarks/forest"
MANIFEST_PATH = BENCHMARK_DIR / "synthetic_geospatial_case.json"
PIXEL_PATH = BENCHMARK_DIR / "synthetic_scene_pixels.csv"
REFERENCE_PATH = BENCHMARK_DIR / "synthetic_reference_mask.csv"
SCHEMA_PATH = BENCHMARK_DIR / "benchmark.schema.json"
OPT_IN_PATH = BENCHMARK_DIR / "public_data_opt_in_manifest.json"
EXPECTED_SUMMARY = BENCHMARK_DIR / "expected_summary.json"
EXPECTED_GEOJSON = BENCHMARK_DIR / "expected_cells.geojson"


def _copy_case(directory):
    destination = Path(directory)
    for source in (MANIFEST_PATH, PIXEL_PATH, REFERENCE_PATH):
        shutil.copy2(source, destination / source.name)
    return destination / MANIFEST_PATH.name


def _rewrite_manifest(path, mutate):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    mutate(payload)
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _signed_area(ring):
    return (
        sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(ring, ring[1:])
        )
        / 2
    )


class GeospatialBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = analyze_geospatial_benchmark(MANIFEST_PATH)
        cls.summary = cls.analysis["summary"]
        cls.geojson = build_geospatial_geojson(cls.analysis)

    def test_machine_readable_contract_and_runtime_accept_fixture(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        fixture = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(fixture),
            key=lambda error: list(error.absolute_path),
        )
        self.assertEqual(errors, [], [error.message for error in errors])
        loaded = load_geospatial_benchmark(MANIFEST_PATH)
        self.assertEqual(loaded.rows, 4)
        self.assertEqual(loaded.cols, 6)
        self.assertEqual(loaded.crs["code"], 32652)
        self.assertEqual(str(loaded.transform.pixel_area), "100")

    def test_summary_proves_geospatial_mask_temporal_and_holdout_plumbing(self):
        self.assertEqual(self.analysis["schema_version"], ANALYSIS_SCHEMA_VERSION)
        self.assertEqual(self.summary["schema_version"], SUMMARY_SCHEMA_VERSION)
        self.assertEqual(self.summary["grid"]["pixel_area_m2"], "100")
        self.assertEqual(self.summary["grid"]["total_grid_area_m2"], "2400")
        self.assertEqual(
            self.summary["grid"]["bbox_native_crs"],
            [500000.0, 4099960.0, 500060.0, 4100000.0],
        )
        self.assertEqual(self.summary["masking"]["valid_pixel_count"], 20)
        self.assertEqual(self.summary["masking"]["masked_pixel_count"], 4)
        self.assertEqual(
            self.summary["masking"]["mask_reason_counts"],
            {
                "nodata_after": 1,
                "qa_after:cloud": 1,
                "qa_after:shadow": 1,
                "qa_before:cloud": 1,
            },
        )
        self.assertEqual(self.summary["temporal_pair"]["day_of_year_delta"], 2)
        self.assertEqual(self.summary["temporal_pair"]["elapsed_seconds"], 31795320)
        self.assertTrue(self.summary["temporal_pair"]["policy_passed"])
        self.assertEqual(self.summary["tiling"]["tile_count"], 4)
        self.assertEqual(self.summary["spatial_split"]["train_pixel_count"], 12)
        self.assertEqual(self.summary["spatial_split"]["holdout_pixel_count"], 12)
        self.assertEqual(self.summary["spatial_split"]["masked_holdout_pixel_count"], 3)
        self.assertFalse(self.summary["reference"]["independent_ground_truth"])
        self.assertGreaterEqual(
            len(self.summary["benchmark"]["claim_boundary"]["does_not_demonstrate"]),
            4,
        )

    def test_only_valid_holdout_pixels_contribute_to_reported_metrics(self):
        evaluation = self.summary["spatial_evaluation"]
        self.assertEqual(evaluation["scope"], "valid_holdout_pixels_only")
        self.assertEqual(evaluation["evaluated_pixel_count"], 9)
        self.assertEqual(
            evaluation["confusion_matrix"],
            {"tp": 4, "fp": 1, "fn": 1, "tn": 3},
        )
        self.assertEqual(
            evaluation["metrics"],
            {"precision": 0.8, "recall": 0.8, "f1": 0.8, "iou": 0.666667},
        )
        included = [
            cell for cell in self.analysis["cells"] if cell["evaluation_included"]
        ]
        self.assertEqual(len(included), 9)
        self.assertTrue(all(cell["valid"] for cell in included))
        self.assertTrue(all(cell["split"] == "holdout" for cell in included))
        self.assertEqual(
            Counter(cell["confusion_class"] for cell in included),
            Counter({"tp": 4, "tn": 3, "fp": 1, "fn": 1}),
        )

    def test_nodata_cloud_and_shadow_are_masked_before_ndvi(self):
        cells = {(cell["row"], cell["col"]): cell for cell in self.analysis["cells"]}
        expected = {
            (0, 4): ["qa_before:cloud"],
            (1, 5): ["nodata_after"],
            (2, 4): ["qa_after:shadow"],
            (3, 1): ["qa_after:cloud"],
        }
        for cell, reasons in expected.items():
            with self.subTest(cell=cell):
                self.assertFalse(cells[cell]["valid"])
                self.assertEqual(cells[cell]["mask_reasons"], reasons)
                self.assertIsNone(cells[cell]["ndvi_before"])
                self.assertIsNone(cells[cell]["ndvi_after"])
                self.assertIsNone(cells[cell]["predicted_loss"])
                self.assertFalse(cells[cell]["evaluation_included"])

    def test_geojson_has_stable_native_crs_polygons_and_exact_planar_area(self):
        self.assertEqual(self.geojson["type"], "FeatureCollection")
        self.assertEqual(len(self.geojson["features"]), 24)
        self.assertEqual(
            [feature["id"] for feature in self.geojson["features"]],
            [f"cell-r{row:03d}-c{col:03d}" for row in range(4) for col in range(6)],
        )
        coordinate_metadata = self.geojson["coordinate_reference_system"]
        self.assertEqual(coordinate_metadata["code"], 32652)
        self.assertEqual(coordinate_metadata["coordinate_space"], "native_projected")
        self.assertFalse(coordinate_metadata["rfc7946_wgs84"])
        for feature in self.geojson["features"]:
            ring = feature["geometry"]["coordinates"][0]
            self.assertEqual(ring[0], ring[-1])
            self.assertAlmostEqual(_signed_area(ring), 100.0)
            self.assertEqual(feature["properties"]["pixel_area_m2"], 100.0)
        self.assertEqual(
            sum(
                _signed_area(feature["geometry"]["coordinates"][0])
                for feature in self.geojson["features"]
            ),
            2400.0,
        )

    def test_tiling_is_row_major_complete_disjoint_and_clips_edges(self):
        tiles = deterministic_tiles(5, 7, 2, 3)
        self.assertEqual(
            [tile.tile_id for tile in tiles],
            [
                "tile-r0000-c0000",
                "tile-r0000-c0003",
                "tile-r0000-c0006",
                "tile-r0002-c0000",
                "tile-r0002-c0003",
                "tile-r0002-c0006",
                "tile-r0004-c0000",
                "tile-r0004-c0003",
                "tile-r0004-c0006",
            ],
        )
        self.assertEqual(tiles[-1].pixel_count, 1)
        memberships = Counter(
            cell
            for tile in tiles
            for cell in (
                (row, col)
                for row in range(tile.row_start, tile.row_stop)
                for col in range(tile.col_start, tile.col_stop)
            )
        )
        self.assertEqual(
            set(memberships), {(row, col) for row in range(5) for col in range(7)}
        )
        self.assertEqual(set(memberships.values()), {1})
        for invalid in ((0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 0, 1)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                deterministic_tiles(*invalid)

    def test_csv_row_order_changes_input_hash_but_not_semantic_or_geojson_order(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _copy_case(directory)
            lines = (
                (Path(directory) / PIXEL_PATH.name)
                .read_text(encoding="utf-8")
                .splitlines()
            )
            (Path(directory) / PIXEL_PATH.name).write_text(
                "\n".join([lines[0], *reversed(lines[1:])]) + "\n",
                encoding="utf-8",
            )
            reordered = analyze_geospatial_benchmark(manifest)
        self.assertEqual(reordered["cells"], self.analysis["cells"])
        self.assertEqual(
            build_geospatial_geojson(reordered),
            self.geojson,
        )
        baseline_summary = copy.deepcopy(self.summary)
        reordered_summary = copy.deepcopy(reordered["summary"])
        baseline_hash = baseline_summary.pop("input_provenance")["scene_pixels"][
            "sha256"
        ]
        reordered_hash = reordered_summary.pop("input_provenance")["scene_pixels"][
            "sha256"
        ]
        self.assertNotEqual(baseline_hash, reordered_hash)
        self.assertEqual(baseline_summary, reordered_summary)

    def test_contract_rejects_crs_affine_temporal_split_reference_and_path_mutations(
        self,
    ):
        mutations = (
            (lambda value: value["grid"]["crs"].update(code=4326), "supported"),
            (
                lambda value: value["grid"].update(
                    geotransform=["0", "10", "20", "0", "5", "10"]
                ),
                "invertible",
            ),
            (
                lambda value: value["observations"]["after"].update(season_label="wet"),
                "same declared season",
            ),
            (
                lambda value: value["spatial_split"].update(
                    holdout_tile_ids=["tile-r9999-c9999"]
                ),
                "proper subset",
            ),
            (
                lambda value: value["reference"].update(independent_ground_truth=True),
                "must not claim",
            ),
            (
                lambda value: value["files"].update(
                    scene_pixels="../synthetic_scene_pixels.csv"
                ),
                "manifest directory",
            ),
            (lambda value: value.update(unexpected="value"), "contract mismatch"),
        )
        for mutate, message in mutations:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                manifest = _copy_case(directory)
                _rewrite_manifest(manifest, mutate)
                with self.assertRaisesRegex(ValueError, message):
                    load_geospatial_benchmark(manifest)

    def test_additional_manifest_boundaries_fail_closed(self):
        mutations = (
            (lambda value: value.update(purpose=""), "non-empty string"),
            (lambda value: value.update(schema_version="other"), "schema_version"),
            (
                lambda value: value["grid"].update(rows=1001, cols=1),
                "at most 1000",
            ),
            (
                lambda value: value["grid"].update(rows=1, cols=1001),
                "at most 1000",
            ),
            (
                lambda value: value["grid"].update(pixel_origin="pixel_center"),
                "upper_left_corner",
            ),
            (
                lambda value: value["grid"].update(geotransform=["0"] * 5),
                "six GDAL-order",
            ),
            (
                lambda value: value["grid"].update(
                    geotransform=["0", 10, "0", "0", "0", "-10"]
                ),
                "decimal string",
            ),
            (
                lambda value: value["grid"].update(
                    geotransform=["0", "1e1", "0", "0", "0", "-10"]
                ),
                "decimal string",
            ),
            (
                lambda value: value["prediction_rule"].update(forest_ndvi_min="+0.45"),
                "decimal string",
            ),
            (lambda value: value["grid"].update(nodata_value="0.5"), "outside"),
            (
                lambda value: value["observations"]["before"].update(
                    source_kind="remote_scene"
                ),
                "team_authored_synthetic",
            ),
            (
                lambda value: value["observations"]["after"].update(
                    scene_id=value["observations"]["before"]["scene_id"]
                ),
                "scene IDs must differ",
            ),
            (
                lambda value: value["observations"]["after"].update(
                    acquired_at="2023-02-17T02:12:00Z"
                ),
                "must be later",
            ),
            (
                lambda value: value["observations"]["before"].update(
                    acquired_at="2024-02-15 02:10:00"
                ),
                "UTC timestamp",
            ),
            (
                lambda value: value["observations"]["seasonality_policy"].update(
                    require_same_season_label=False
                ),
                "must be true",
            ),
            (
                lambda value: value["observations"]["seasonality_policy"].update(
                    timezone="Asia/Seoul"
                ),
                "must be UTC",
            ),
            (
                lambda value: value["observations"]["seasonality_policy"].update(
                    maximum_day_of_year_delta=184
                ),
                "bounds are inconsistent",
            ),
            (
                lambda value: value["observations"]["after"].update(
                    acquired_at="2025-03-01T02:12:00Z"
                ),
                "day-of-year delta",
            ),
            (
                lambda value: value["observations"]["after"].update(
                    acquired_at="2026-02-17T02:12:00Z"
                ),
                "elapsed time",
            ),
            (
                lambda value: value["masking"].update(qa_clear_class="valid"),
                "must be clear",
            ),
            (
                lambda value: value["masking"].update(
                    qa_excluded_classes=["shadow", "cloud"]
                ),
                r"must be \[cloud, shadow\]",
            ),
            (
                lambda value: value["masking"].update(nodata_scope="all_bands"),
                "any_required_band",
            ),
            (
                lambda value: value["masking"].update(evaluation_scope="all_pixels"),
                "valid_holdout_pixels_only",
            ),
            (
                lambda value: value["prediction_rule"].update(kind="classifier"),
                "fixed_ndvi_threshold",
            ),
            (
                lambda value: value["prediction_rule"].update(forest_ndvi_min="2"),
                r"within \[-1, 1\]",
            ),
            (
                lambda value: value["prediction_rule"].update(ndvi_decrease_min="3"),
                r"within \[0, 2\]",
            ),
            (
                lambda value: value["tiling"].update(order="column_major"),
                "row_major",
            ),
            (
                lambda value: value["spatial_split"].update(strategy="random"),
                "deterministic_tile_holdout",
            ),
            (
                lambda value: value["spatial_split"].update(
                    reported_metrics_scope="all_pixels"
                ),
                "valid holdout pixels",
            ),
            (
                lambda value: value["reference"].update(kind="field_survey"),
                "team-authored synthetic",
            ),
            (
                lambda value: value["claim_boundary"].update(
                    demonstrates=["duplicate", "duplicate"]
                ),
                "must not contain duplicates",
            ),
        )
        for mutate, message in mutations:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                manifest = _copy_case(directory)
                _rewrite_manifest(manifest, mutate)
                with self.assertRaisesRegex(ValueError, message):
                    load_geospatial_benchmark(manifest)

        with tempfile.TemporaryDirectory() as directory:
            manifest = _copy_case(directory)
            _rewrite_manifest(
                manifest,
                lambda value: value["files"].update(scene_pixels="not_present.csv"),
            )
            with self.assertRaises(FileNotFoundError):
                load_geospatial_benchmark(manifest)

    def test_seasonality_distance_wraps_across_calendar_year(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _copy_case(directory)

            def mutate(value):
                value["observations"]["before"]["acquired_at"] = "2024-12-31T02:10:00Z"
                value["observations"]["after"]["acquired_at"] = "2025-01-01T02:12:00Z"
                policy = value["observations"]["seasonality_policy"]
                policy["minimum_elapsed_days"] = 1
                policy["maximum_elapsed_days"] = 2

            _rewrite_manifest(manifest, mutate)
            case = load_geospatial_benchmark(manifest)
            self.assertEqual(case.before_time.month, 12)
            self.assertEqual(case.after_time.month, 1)

    def test_scene_and_reference_csv_validation_fail_closed(self):
        cases = (
            (
                "pixels",
                lambda text: text.replace(
                    "0,0,0.20,0.60,clear", "0,0,1.20,0.60,clear", 1
                ),
                "within",
            ),
            (
                "pixels",
                lambda text: text.replace(
                    "0,0,0.20,0.60,clear", "0,0,0.20,0.60,snow", 1
                ),
                "unsupported QA",
            ),
            (
                "pixels",
                lambda text: "\n".join(
                    [text.splitlines()[0], text.splitlines()[1], *text.splitlines()[1:]]
                )
                + "\n",
                "duplicate",
            ),
            (
                "reference",
                lambda text: "\n".join(text.splitlines()[:-1]) + "\n",
                "does not match grid",
            ),
            (
                "reference",
                lambda text: "\n".join(
                    [text.splitlines()[0], text.splitlines()[1], *text.splitlines()[1:]]
                )
                + "\n",
                "duplicate reference",
            ),
            (
                "reference",
                lambda text: text.replace("0,0,0", "0,0,2", 1),
                "exactly 0 or 1",
            ),
            (
                "pixels",
                lambda text: text.replace("row,col,", "row,column,", 1),
                "invalid columns",
            ),
            (
                "pixels",
                lambda text: text.splitlines()[0] + "\n",
                "fixture is empty",
            ),
            (
                "pixels",
                lambda text: text.replace("0,0,0.20", "0,0,", 1),
                "blank",
            ),
            (
                "pixels",
                lambda text: text.replace("0,0,0.20", "x,0,0.20", 1),
                "invalid coordinate",
            ),
            (
                "pixels",
                lambda text: text.replace("0,0,0.20", "-1,0,0.20", 1),
                "non-negative",
            ),
        )
        for target, mutate, message in cases:
            with (
                self.subTest(target=target, message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                manifest = _copy_case(directory)
                filename = (
                    PIXEL_PATH.name if target == "pixels" else REFERENCE_PATH.name
                )
                path = Path(directory) / filename
                path.write_text(
                    mutate(path.read_text(encoding="utf-8")), encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, message):
                    analyze_geospatial_benchmark(manifest)

    def test_zero_ndvi_denominator_is_rejected_only_after_mask_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _copy_case(directory)
            path = Path(directory) / PIXEL_PATH.name
            content = path.read_text(encoding="utf-8").replace(
                "0,0,0.20,0.60,clear", "0,0,0,0,clear", 1
            )
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NDVI is undefined"):
                analyze_geospatial_benchmark(manifest)

        with tempfile.TemporaryDirectory() as directory:
            manifest = _copy_case(directory)
            path = Path(directory) / PIXEL_PATH.name
            content = path.read_text(encoding="utf-8").replace(
                "0,0,0.20,0.60,clear", "0,0,-9999,-9999,clear", 1
            )
            path.write_text(content, encoding="utf-8")
            masked = analyze_geospatial_benchmark(manifest)
        first = masked["cells"][0]
        self.assertEqual(first["mask_reasons"], ["nodata_before"])
        self.assertIsNone(first["ndvi_before"])

    def test_reference_mutation_changes_hash_and_holdout_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _copy_case(directory)
            path = Path(directory) / REFERENCE_PATH.name
            content = path.read_text(encoding="utf-8").replace("1,4,1", "1,4,0", 1)
            path.write_text(content, encoding="utf-8")
            mutated = analyze_geospatial_benchmark(manifest)["summary"]
        self.assertNotEqual(
            mutated["input_provenance"]["reference_mask"]["sha256"],
            self.summary["input_provenance"]["reference_mask"]["sha256"],
        )
        self.assertEqual(
            mutated["spatial_evaluation"]["confusion_matrix"],
            {"tp": 4, "fp": 1, "fn": 0, "tn": 4},
        )
        self.assertEqual(mutated["spatial_evaluation"]["metrics"]["f1"], 0.888889)

    def test_public_satellite_sources_are_metadata_only_and_explicitly_opt_in(self):
        manifest = json.loads(OPT_IN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["classification"], "network_opt_in_metadata_only")
        self.assertFalse(manifest["automatic_download"])
        self.assertFalse(manifest["runtime_used_by_default"])
        self.assertFalse(manifest["downloaded_assets_committed"])
        self.assertTrue(manifest["adapter_contract"]["explicit_user_opt_in_required"])
        self.assertFalse(
            manifest["adapter_contract"]["network_client_in_runtime_package"]
        )
        self.assertEqual(
            {
                (provider["mission"], provider["collection"])
                for provider in manifest["providers"]
            },
            {("Sentinel-2", "sentinel-2-l2a"), ("Landsat 8/9", "landsat-c2l2-sr")},
        )
        forbidden_suffixes = {".tif", ".tiff", ".jp2", ".nc", ".parquet"}
        self.assertFalse(
            [
                path
                for path in BENCHMARK_DIR.rglob("*")
                if path.is_file() and path.suffix.lower() in forbidden_suffixes
            ]
        )

    def test_runtime_is_offline_and_cli_matches_committed_golden_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.json"
            geojson_path = Path(directory) / "cells.geojson"
            with patch(
                "socket.socket",
                side_effect=AssertionError("geospatial benchmark must remain offline"),
            ):
                self.assertEqual(
                    main(
                        [
                            str(MANIFEST_PATH),
                            "--summary",
                            str(summary_path),
                            "--geojson",
                            str(geojson_path),
                        ]
                    ),
                    0,
                )
            self.assertEqual(summary_path.read_bytes(), EXPECTED_SUMMARY.read_bytes())
            self.assertEqual(geojson_path.read_bytes(), EXPECTED_GEOJSON.read_bytes())
            self.assertEqual(
                sha256(summary_path.read_bytes()).hexdigest(),
                sha256(canonical_json(self.summary).encode("utf-8")).hexdigest(),
            )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main([str(MANIFEST_PATH)]), 0)
        self.assertEqual(json.loads(stdout.getvalue()), self.summary)

    def test_geometry_and_geojson_public_boundaries_reject_invalid_inputs(self):
        positive_transform = AffineTransform(
            Decimal("0"),
            Decimal("10"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("10"),
        )
        self.assertEqual(_signed_area(pixel_polygon(positive_transform, 0, 0)), 100)
        for row, col in ((-1, 0), (0, -1), (True, 0)):
            with self.subTest(row=row, col=col), self.assertRaises(ValueError):
                pixel_polygon(positive_transform, row, col)

        with self.assertRaisesRegex(ValueError, "analysis schema"):
            build_geospatial_geojson({"schema_version": "other"})
        invalid = copy.deepcopy(self.analysis)
        invalid["summary"]["grid"]["geotransform_gdal_order"] = ["0"]
        with self.assertRaisesRegex(ValueError, "invalid geotransform"):
            build_geospatial_geojson(invalid)


if __name__ == "__main__":
    unittest.main()
