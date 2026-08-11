import unittest
import tempfile
from pathlib import Path

from ecoguard.forest import analyze_forest_change, ndvi, render_change_svg


ROOT = Path(__file__).resolve().parents[1]


class ForestBaselineTests(unittest.TestCase):
    def test_ndvi_formula(self):
        self.assertAlmostEqual(ndvi(0.2, 0.6), 0.5)

    def test_synthetic_loss_patch_is_deterministic(self):
        result = analyze_forest_change(
            ROOT / "data/synthetic/forest_pixels.csv"
        )
        self.assertEqual(result["summary"]["loss_pixel_count"], 12)
        self.assertEqual(result["summary"]["loss_share"], 0.3333)
        self.assertEqual(result["summary"]["loss_area_m2"], 1200.0)
        self.assertEqual(result["summary"]["contiguous_region_count"], 1)
        self.assertEqual(result["regions"][0]["pixel_count"], 12)
        self.assertEqual(
            sum(region["area_m2"] for region in result["regions"]),
            result["summary"]["loss_area_m2"],
        )
        loss_cells = {
            (pixel["row"], pixel["col"])
            for pixel in result["pixels"]
            if pixel["loss_flag"]
        }
        self.assertIn((2, 2), loss_cells)
        self.assertNotIn((0, 0), loss_cells)

    def test_visualization_declares_its_scope(self):
        result = analyze_forest_change(
            ROOT / "data/synthetic/forest_pixels.csv"
        )
        svg = render_change_svg(result)
        self.assertIn("Synthetic NDVI change evidence", svg)
        self.assertIn("not an EUDR compliance determination", svg)

    def test_invalid_grid_and_area_are_rejected(self):
        with self.assertRaises(ValueError):
            analyze_forest_change(
                ROOT / "data/synthetic/forest_pixels.csv",
                pixel_area_m2=-100,
            )

        duplicate = (
            "row,col,red_before,nir_before,red_after,nir_after\n"
            "0,0,0.2,0.6,0.3,0.3\n"
            "0,0,0.2,0.6,0.3,0.3\n"
        )
        invalid_number = (
            "row,col,red_before,nir_before,red_after,nir_after\n"
            "0,0,nan,0.6,0.3,0.3\n"
        )
        for content in (duplicate, invalid_number):
            with self.subTest(content=content.splitlines()[1]):
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".csv",
                    encoding="utf-8",
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    with self.assertRaises(ValueError):
                        analyze_forest_change(handle.name)

    def test_zero_denominator_is_not_silently_treated_as_bare_land(self):
        with self.assertRaises(ValueError):
            ndvi(0.0, 0.0)


if __name__ == "__main__":
    unittest.main()
