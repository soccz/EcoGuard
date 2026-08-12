import json
import re
import tomllib
import unittest
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from ecoguard import __version__
from ecoguard.pipeline import INPUT_SPECS, PIPELINE_VERSION


ROOT = Path(__file__).resolve().parents[1]


class PublicContractTests(unittest.TestCase):
    def test_package_and_pipeline_versions_are_synchronized(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["version"], __version__)
        self.assertEqual(PIPELINE_VERSION, __version__)
        self.assertEqual(project["project"].get("dependencies", []), [])
        self.assertEqual(project["project"]["requires-python"], ">=3.11")

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
                        "https://raw.githubusercontent.com/soccz/EcoGuard/v0.4.0/schemas/"
                    )
                )
                self.assertEqual(payload["type"], "object")

    def test_public_fixtures_validate_against_draft_2020_12_schemas(self):
        fixtures = {
            "artifact_manifest.schema.json": (
                ROOT / "artifacts/examples/artifact_manifest.json"
            ),
            "forest_case.schema.json": ROOT / "data/synthetic/forest_case.json",
            "normalization_policy.schema.json": (
                ROOT / "data/reference/normalization_policy.json"
            ),
            "trade_case_documents.schema.json": (
                ROOT / "data/synthetic/trade_case_documents.json"
            ),
        }
        for schema_name, fixture_path in fixtures.items():
            with self.subTest(schema=schema_name, fixture=fixture_path.name):
                schema = json.loads(
                    (ROOT / "schemas" / schema_name).read_text(encoding="utf-8")
                )
                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                errors = sorted(
                    Draft202012Validator(schema).iter_errors(fixture),
                    key=lambda error: list(error.absolute_path),
                )
                self.assertEqual(errors, [], [error.message for error in errors])

    def test_forest_schema_rejects_invalid_runtime_contract_examples(self):
        schema = json.loads(
            (ROOT / "schemas/forest_case.schema.json").read_text(encoding="utf-8")
        )
        baseline = json.loads(
            (ROOT / "data/synthetic/forest_case.json").read_text(encoding="utf-8")
        )
        mutations = []
        for path, value in (
            (("grid", "cell_width_m"), "banana"),
            (("thresholds", "forest_ndvi_min"), "2"),
            (("geojson_transform",), {}),
            (("reference",), {}),
        ):
            mutated = json.loads(json.dumps(baseline))
            target = mutated
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            mutations.append(mutated)

        validator = Draft202012Validator(schema)
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                self.assertTrue(list(validator.iter_errors(mutated)))

    def test_normalization_schema_and_runtime_use_the_same_selection_strategy(self):
        schema = json.loads(
            (ROOT / "schemas/normalization_policy.schema.json").read_text(
                encoding="utf-8"
            )
        )
        policy = json.loads(
            (ROOT / "data/reference/normalization_policy.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            schema["properties"]["selection_strategy"]["const"],
            policy["selection_strategy"],
        )

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

    def test_manifest_hashes_match_every_committed_input_and_output_byte(self):
        artifact_dir = ROOT / "artifacts/examples"
        manifest = json.loads(
            (artifact_dir / "artifact_manifest.json").read_text(encoding="utf-8")
        )
        input_paths = {
            name: ROOT / relative_path
            for name, relative_path, _resource_name in INPUT_SPECS
        }
        output_paths = {
            "extracted_records": artifact_dir / "extracted_records.json",
            "normalized_evidence": artifact_dir / "normalized_evidence.json",
            "legal_retrieval_evaluation": (
                artifact_dir / "legal_retrieval_evaluation.json"
            ),
            "legal_issue_citations": artifact_dir / "legal_issue_citations.json",
            "cbam_exposure": artifact_dir / "cbam_exposure.json",
            "forest_change": artifact_dir / "forest_change.json",
            "forest_change_geojson": artifact_dir / "forest_change.geojson",
            "forest_change_svg": artifact_dir / "forest_change.svg",
            "evidence_report_json": artifact_dir / "ecoguard_evidence_report.json",
            "evidence_report_html": artifact_dir / "ecoguard_evidence_report.html",
        }
        self.assertEqual(set(manifest["inputs"]), set(input_paths))
        self.assertEqual(set(manifest["outputs"]), set(output_paths))
        for section, paths in (("inputs", input_paths), ("outputs", output_paths)):
            for name, path in paths.items():
                with self.subTest(section=section, name=name):
                    content = path.read_bytes()
                    self.assertEqual(manifest[section][name]["bytes"], len(content))
                    self.assertEqual(
                        manifest[section][name]["sha256"],
                        sha256(content).hexdigest(),
                    )

    def test_all_public_json_rejects_nonstandard_nan_constants(self):
        json_paths = [
            *sorted((ROOT / "schemas").glob("*.json")),
            *sorted((ROOT / "data").rglob("*.json")),
            *sorted((ROOT / "artifacts/examples").glob("*.json")),
        ]
        self.assertTrue(json_paths)

        def reject_constant(value):
            raise ValueError(f"non-standard JSON constant: {value}")

        for path in json_paths:
            with self.subTest(path=path.relative_to(ROOT)):
                json.loads(
                    path.read_text(encoding="utf-8"),
                    parse_constant=reject_constant,
                )

    def test_validation_matrix_only_names_discoverable_tests(self):
        validation = (ROOT / "docs/VALIDATION.md").read_text(encoding="utf-8")
        references = set(
            re.findall(
                r"`(test_[a-z0-9_]+\.[A-Za-z0-9_]+\.test_[a-z0-9_]+)`",
                validation,
            )
        )

        def test_ids(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from test_ids(item)
                else:
                    yield item.id()

        discovered = set(
            test_ids(unittest.defaultTestLoader.discover(str(ROOT / "tests")))
        )
        self.assertGreaterEqual(len(references), 20)
        self.assertEqual(references - discovered, set())


if __name__ == "__main__":
    unittest.main()
