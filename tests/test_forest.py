import json
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from ecoguard.forest import (
    analyze_forest_case,
    analyze_forest_change,
    build_regions_geojson,
    connected_components,
    evaluate_binary_mask,
    load_forest_case,
    ndvi,
    render_change_svg,
)


ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "data/synthetic/forest_case.json"
PIXEL_PATH = ROOT / "data/synthetic/forest_pixels.csv"
REFERENCE_PATH = ROOT / "data/synthetic/forest_reference_mask.csv"

EXPECTED_PREDICTION = {
    (1, 2),
    (1, 3),
    (2, 1),
    (2, 2),
    (2, 3),
    (2, 4),
    (3, 1),
    (3, 2),
    (3, 3),
    (3, 4),
    (4, 2),
    (4, 3),
}
EXPECTED_REFERENCE = (EXPECTED_PREDICTION - {(1, 3)}) | {(4, 4)}


def _manifest(rows=6, cols=6):
    manifest = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    manifest["grid"]["rows"] = rows
    manifest["grid"]["cols"] = cols
    return manifest


def _write_case(directory, pixels, reference, manifest=None):
    directory = Path(directory)
    (directory / "forest_pixels.csv").write_text(pixels, encoding="utf-8")
    (directory / "forest_reference_mask.csv").write_text(reference, encoding="utf-8")
    (directory / "forest_case.json").write_text(
        json.dumps(manifest or _manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return directory / "forest_case.json"


class ForestV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = analyze_forest_case(CASE_PATH)

    def test_ndvi_uses_valid_reflectance_only(self):
        self.assertAlmostEqual(ndvi(0.2, 0.6), 0.5)
        for red, nir in (
            (0.0, 0.0),
            (-0.1, 0.6),
            (0.2, 1.1),
            (math.nan, 0.5),
            (0.5, math.inf),
        ):
            with self.subTest(red=red, nir=nir):
                with self.assertRaises(ValueError):
                    ndvi(red, nir)

    def test_manifest_case_has_exact_prediction_reference_and_metrics(self):
        pixels = self.result["pixels"]
        self.assertEqual(
            [(pixel["row"], pixel["col"]) for pixel in pixels],
            [(row, col) for row in range(6) for col in range(6)],
        )
        predicted = {
            (pixel["row"], pixel["col"]) for pixel in pixels if pixel["loss_flag"]
        }
        reference = {
            (pixel["row"], pixel["col"]) for pixel in pixels if pixel["reference_loss"]
        }
        self.assertEqual(predicted, EXPECTED_PREDICTION)
        self.assertEqual(reference, EXPECTED_REFERENCE)
        self.assertEqual(
            self.result["evaluation"]["confusion_matrix"],
            {"tp": 11, "fp": 1, "fn": 1, "tn": 23},
        )
        self.assertEqual(
            self.result["evaluation"]["metrics"],
            {
                "precision": 0.916667,
                "recall": 0.916667,
                "f1": 0.916667,
                "iou": 0.846154,
            },
        )
        self.assertEqual(self.result["summary"]["loss_pixel_count"], 12)
        self.assertEqual(self.result["summary"]["loss_area_m2"], 1200.0)
        self.assertEqual(self.result["summary"]["contiguous_region_count"], 1)
        region_cells = {
            (cell["row"], cell["col"]) for cell in self.result["regions"][0]["cells"]
        }
        self.assertEqual(region_cells, EXPECTED_PREDICTION)
        self.assertIn(
            "not a real-world annotation", self.result["reference"]["provenance"]
        )

    def test_manifest_classification_and_top_level_contract_are_enforced(self):
        pixels = PIXEL_PATH.read_text(encoding="utf-8")
        reference = REFERENCE_PATH.read_text(encoding="utf-8")
        mutations = (
            ("classification", "production_satellite_result", "classification"),
            ("unexpected", "value", "unsupported forest manifest"),
        )
        for key, value, message in mutations:
            with self.subTest(key=key):
                manifest = _manifest()
                manifest[key] = value
                with tempfile.TemporaryDirectory() as directory:
                    case_path = _write_case(directory, pixels, reference, manifest)
                    with self.assertRaisesRegex(ValueError, message):
                        load_forest_case(case_path)

    def test_threshold_comparison_uses_unrounded_values(self):
        pixels = (
            "row,col,red_before,nir_before,red_after,nir_after\n"
            "0,0,0.2,0.6,0.3,0.5\n"
            "0,1,0.2001,0.6,0.3,0.5\n"
        )
        reference = "row,col,reference_loss\n0,0,1\n0,1,0\n"
        manifest = _manifest(rows=1, cols=2)
        manifest["thresholds"] = {
            "forest_ndvi_min": "0.5",
            "ndvi_decrease_min": "0.25",
        }
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_forest_case(
                _write_case(directory, pixels, reference, manifest)
            )
        self.assertTrue(result["pixels"][0]["loss_flag"])
        self.assertFalse(result["pixels"][1]["loss_flag"])
        self.assertEqual(result["evaluation"]["metrics"]["f1"], 1.0)

    def test_input_row_order_does_not_change_any_output(self):
        def reversed_csv(path):
            lines = path.read_text(encoding="utf-8").splitlines()
            return "\n".join([lines[0], *reversed(lines[1:])]) + "\n"

        with tempfile.TemporaryDirectory() as directory:
            shuffled = analyze_forest_case(
                _write_case(
                    directory,
                    reversed_csv(PIXEL_PATH),
                    reversed_csv(REFERENCE_PATH),
                )
            )
        self.assertEqual(shuffled, self.result)
        self.assertEqual(
            build_regions_geojson(shuffled), build_regions_geojson(self.result)
        )
        self.assertEqual(render_change_svg(shuffled), render_change_svg(self.result))

    def test_equivalent_decimal_notation_does_not_change_outputs(self):
        pixels = PIXEL_PATH.read_text(encoding="utf-8").replace(
            "0,0,0.18,0.72,0.19,0.70",
            "0,0,0.1800,0.72000,0.1900,0.7000",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            equivalent = analyze_forest_case(
                _write_case(
                    directory,
                    pixels,
                    REFERENCE_PATH.read_text(encoding="utf-8"),
                )
            )
        self.assertEqual(equivalent, self.result)
        self.assertEqual(
            build_regions_geojson(equivalent), build_regions_geojson(self.result)
        )
        self.assertEqual(render_change_svg(equivalent), render_change_svg(self.result))

    def test_one_band_mutation_changes_mask_metrics_regions_and_visuals(self):
        pixels = PIXEL_PATH.read_text(encoding="utf-8").replace(
            "0,0,0.18,0.72,0.19,0.70",
            "0,0,0.18,0.72,0.40,0.40",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            mutated = analyze_forest_case(
                _write_case(
                    directory,
                    pixels,
                    REFERENCE_PATH.read_text(encoding="utf-8"),
                )
            )
        self.assertTrue(mutated["pixels"][0]["loss_flag"])
        self.assertEqual(
            mutated["evaluation"]["confusion_matrix"],
            {"tp": 11, "fp": 2, "fn": 1, "tn": 22},
        )
        self.assertEqual(
            mutated["evaluation"]["metrics"],
            {
                "precision": 0.846154,
                "recall": 0.916667,
                "f1": 0.88,
                "iou": 0.785714,
            },
        )
        self.assertEqual(mutated["summary"]["contiguous_region_count"], 2)
        self.assertNotEqual(
            build_regions_geojson(mutated), build_regions_geojson(self.result)
        )
        self.assertNotEqual(render_change_svg(mutated), render_change_svg(self.result))

    def test_connected_components_are_stable_and_connectivity_is_explicit(self):
        diagonal = {(0, 0), (1, 1), (2, 2)}
        self.assertEqual(
            connected_components(diagonal, rows=3, cols=3, connectivity=4),
            (((0, 0),), ((1, 1),), ((2, 2),)),
        )
        self.assertEqual(
            connected_components(diagonal, rows=3, cols=3, connectivity=8),
            (((0, 0), (1, 1), (2, 2)),),
        )
        self.assertEqual(connected_components(set(), rows=1, cols=1), ())
        with self.assertRaises(ValueError):
            connected_components({(1, 0)}, rows=1, cols=1)

    def test_metric_zero_denominators_are_null_not_arbitrary_scores(self):
        universe = {(0, 0), (0, 1)}
        empty = evaluate_binary_mask(set(), set(), universe)
        self.assertEqual(
            empty["metrics"],
            {"precision": None, "recall": None, "f1": None, "iou": None},
        )
        self.assertEqual(
            empty["undefined_metrics"], ["precision", "recall", "f1", "iou"]
        )
        missed = evaluate_binary_mask(set(), {(0, 0)}, universe)
        self.assertIsNone(missed["metrics"]["precision"])
        self.assertEqual(missed["metrics"]["recall"], 0.0)
        self.assertEqual(missed["metrics"]["f1"], 0.0)
        false_alarm = evaluate_binary_mask({(0, 0)}, set(), universe)
        self.assertEqual(false_alarm["metrics"]["precision"], 0.0)
        self.assertIsNone(false_alarm["metrics"]["recall"])
        with self.assertRaises(ValueError):
            evaluate_binary_mask({(9, 9)}, set(), universe)
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            evaluate_binary_mask(set(), set(), set())

    def test_geojson_is_complete_stable_and_rfc7946_shaped(self):
        geojson = build_regions_geojson(self.result)
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertNotIn("crs", geojson)
        self.assertEqual(geojson["bbox"], [0.0, 0.00046, 0.00054, 0.001])
        self.assertEqual(len(geojson["features"]), 36)
        self.assertEqual(
            [feature["id"] for feature in geojson["features"]],
            [f"cell-r{row:03d}-c{col:03d}" for row in range(6) for col in range(6)],
        )
        self.assertEqual(
            Counter(
                feature["properties"]["confusion_class"]
                for feature in geojson["features"]
            ),
            Counter({"tn": 23, "tp": 11, "fp": 1, "fn": 1}),
        )
        for feature in geojson["features"]:
            ring = feature["geometry"]["coordinates"][0]
            self.assertEqual(feature["geometry"]["type"], "Polygon")
            self.assertEqual(ring[0], ring[-1])
            signed_area = (
                sum(
                    first[0] * second[1] - second[0] * first[1]
                    for first, second in zip(ring, ring[1:])
                )
                / 2
            )
            self.assertGreater(signed_area, 0)
        serialized = json.dumps(geojson, sort_keys=True, allow_nan=False)
        self.assertEqual(
            serialized,
            json.dumps(
                build_regions_geojson(self.result), sort_keys=True, allow_nan=False
            ),
        )

    def test_svg_is_valid_xml_with_all_confusion_classes(self):
        svg = render_change_svg(self.result)
        root = ET.fromstring(svg)
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        cells = root.findall(".//svg:rect[@data-class]", namespace)
        self.assertEqual(len(cells), 36)
        self.assertEqual(
            Counter(cell.attrib["data-class"] for cell in cells),
            Counter({"tn": 23, "tp": 11, "fp": 1, "fn": 1}),
        )
        self.assertIsNotNone(root.find("svg:title", namespace))
        self.assertIsNotNone(root.find("svg:desc", namespace))
        self.assertIn("F1=0.917", svg)
        self.assertIn("not real-world model accuracy", svg)
        self.assertEqual(svg, render_change_svg(self.result))

    def test_manifest_rejects_incomplete_or_misaligned_grids(self):
        pixels = PIXEL_PATH.read_text(encoding="utf-8")
        reference = REFERENCE_PATH.read_text(encoding="utf-8")
        pixel_lines = pixels.splitlines()
        reference_lines = reference.splitlines()
        invalid_cases = [
            ("\n".join(pixel_lines[:-1]) + "\n", reference, "missing"),
            (pixels, "\n".join(reference_lines[:-1]) + "\n", "missing"),
            (pixels, reference.replace("0,0,0", "0,0,2", 1), "exactly 0 or 1"),
            (pixels.replace("row,col,", "row,column,", 1), reference, "columns"),
        ]
        for invalid_pixels, invalid_reference, message in invalid_cases:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                case_path = _write_case(directory, invalid_pixels, invalid_reference)
                with self.assertRaisesRegex(ValueError, message):
                    analyze_forest_case(case_path)

    def test_band_csv_rejects_duplicates_nonfinite_ranges_and_zero_denominator(self):
        pixels = PIXEL_PATH.read_text(encoding="utf-8")
        reference = REFERENCE_PATH.read_text(encoding="utf-8")
        lines = pixels.splitlines()
        invalid_cases = [
            ("\n".join([lines[0], lines[1], lines[1], *lines[2:]]) + "\n", "duplicate"),
            (pixels.replace("0,0,0.18", "0,0,nan", 1), "finite"),
            (pixels.replace("0,0,0.18", "0,0,1.1", 1), "within"),
            (pixels.replace("0,0,0.18,0.72", "0,0,0,0", 1), "undefined"),
            (pixels.replace("0,0,0.18", "0,0,", 1), "blank"),
        ]
        for invalid_pixels, message in invalid_cases:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                case_path = _write_case(directory, invalid_pixels, reference)
                with self.assertRaisesRegex(ValueError, message):
                    analyze_forest_case(case_path)

    def test_manifest_rejects_bad_schema_paths_and_parameters(self):
        pixels = PIXEL_PATH.read_text(encoding="utf-8")
        reference = REFERENCE_PATH.read_text(encoding="utf-8")
        mutations = [
            (
                lambda manifest: manifest.update(schema_version="1.0.0"),
                "schema_version",
            ),
            (
                lambda manifest: manifest["files"].update(pixels="../pixels.csv"),
                "stay within",
            ),
            (lambda manifest: manifest["grid"].update(rows=0), "positive integer"),
            (lambda manifest: manifest["grid"].update(connectivity=6), "4 or 8"),
            (
                lambda manifest: manifest["thresholds"].update(forest_ndvi_min="nan"),
                "finite",
            ),
            (
                lambda manifest: manifest["geojson_transform"].update(
                    top_left_lat="91"
                ),
                "latitude",
            ),
        ]
        for mutate, message in mutations:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                manifest = _manifest()
                mutate(manifest)
                case_path = _write_case(directory, pixels, reference, manifest)
                with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
                    load_forest_case(case_path)

    def test_public_and_packaged_forest_resources_match(self):
        for filename in (
            "forest_case.json",
            "forest_pixels.csv",
            "forest_reference_mask.csv",
        ):
            with self.subTest(filename=filename):
                public = ROOT / "data/synthetic" / filename
                packaged = ROOT / "src/ecoguard/resources" / filename
                self.assertEqual(public.read_bytes(), packaged.read_bytes())

    def test_legacy_wrapper_and_svg_remain_compatible(self):
        result = analyze_forest_change(PIXEL_PATH)
        self.assertNotIn("evaluation", result)
        self.assertEqual(result["summary"]["loss_pixel_count"], 12)
        self.assertEqual(result["summary"]["loss_share"], 0.3333)
        self.assertEqual(result["summary"]["loss_area_m2"], 1200.0)
        self.assertEqual(result["summary"]["contiguous_region_count"], 1)
        self.assertEqual(
            {
                (pixel["row"], pixel["col"])
                for pixel in result["pixels"]
                if pixel["loss_flag"]
            },
            EXPECTED_PREDICTION,
        )
        svg = render_change_svg(result)
        self.assertIn("Synthetic NDVI change evidence", svg)
        self.assertIn("not an EUDR compliance determination", svg)
        self.assertEqual(result, analyze_forest_change(PIXEL_PATH))
        self.assertEqual(svg, render_change_svg(analyze_forest_change(PIXEL_PATH)))
        for invalid in (-1, math.nan, math.inf):
            with self.subTest(pixel_area=invalid):
                with self.assertRaises(ValueError):
                    analyze_forest_change(PIXEL_PATH, pixel_area_m2=invalid)


if __name__ == "__main__":
    unittest.main()
