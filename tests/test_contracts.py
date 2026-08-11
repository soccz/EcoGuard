import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicContractTests(unittest.TestCase):
    def test_public_json_schemas_are_valid_json_with_stable_ids(self):
        schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
        self.assertEqual(
            {path.name for path in schemas},
            {
                "artifact_manifest.schema.json",
                "forest_case.schema.json",
                "normalization_policy.schema.json",
                "trade_case_documents.schema.json",
            },
        )
        for path in schemas:
            with self.subTest(schema=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    payload["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )
                self.assertTrue(payload["$id"].endswith("/" + path.name))
                self.assertTrue(
                    payload["$id"].startswith(
                        "https://raw.githubusercontent.com/soccz/EcoGuard/main/schemas/"
                    )
                )
                self.assertEqual(payload["type"], "object")

    def test_manifest_contract_matches_committed_golden_shape(self):
        manifest = json.loads(
            (ROOT / "artifacts/examples/artifact_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["schema_version"], "artifact-manifest/1.0")
        self.assertEqual(len(manifest["inputs"]), 8)
        self.assertEqual(len(manifest["outputs"]), 10)
        for section in ("inputs", "outputs"):
            for details in manifest[section].values():
                self.assertRegex(details["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(details["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
