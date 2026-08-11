import unittest
from importlib.resources import files
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagedResourceTests(unittest.TestCase):
    RESOURCE_NAMES = {
        "forest_case.json",
        "forest_pixels.csv",
        "forest_reference_mask.csv",
        "legal_corpus.json",
        "legal_eval.json",
        "normalization_policy.json",
        "source_manifest.json",
        "trade_case_documents.json",
    }

    def test_package_contains_only_declared_public_resources(self):
        packaged = {
            entry.name
            for entry in files("ecoguard.resources").iterdir()
            if entry.is_file() and not entry.name.startswith("__")
        }
        self.assertEqual(packaged, self.RESOURCE_NAMES)

    def test_packaged_resources_match_public_fixtures(self):
        pairs = {
            "trade_case_documents.json": ROOT
            / "data/synthetic/trade_case_documents.json",
            "normalization_policy.json": ROOT
            / "data/reference/normalization_policy.json",
            "forest_case.json": ROOT / "data/synthetic/forest_case.json",
            "forest_pixels.csv": ROOT / "data/synthetic/forest_pixels.csv",
            "forest_reference_mask.csv": ROOT
            / "data/synthetic/forest_reference_mask.csv",
            "legal_corpus.json": ROOT / "data/reference/legal_corpus.json",
            "legal_eval.json": ROOT / "data/reference/legal_eval.json",
            "source_manifest.json": ROOT / "data/reference/source_manifest.json",
        }
        self.assertEqual(set(pairs), self.RESOURCE_NAMES)
        for resource_name, public_path in pairs.items():
            with self.subTest(resource=resource_name):
                packaged = ROOT / "src/ecoguard/resources" / resource_name
                self.assertEqual(packaged.read_bytes(), public_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
