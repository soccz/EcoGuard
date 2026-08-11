import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagedResourceTests(unittest.TestCase):
    def test_packaged_resources_match_public_fixtures(self):
        pairs = {
            "ocr_records.json": ROOT / "data/synthetic/ocr_records.json",
            "forest_pixels.csv": ROOT / "data/synthetic/forest_pixels.csv",
            "legal_corpus.json": ROOT / "data/reference/legal_corpus.json",
            "legal_eval.json": ROOT / "data/reference/legal_eval.json",
            "source_manifest.json": ROOT / "data/reference/source_manifest.json",
        }
        for resource_name, public_path in pairs.items():
            with self.subTest(resource=resource_name):
                packaged = ROOT / "src/ecoguard/resources" / resource_name
                self.assertEqual(packaged.read_bytes(), public_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
