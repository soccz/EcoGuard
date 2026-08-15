import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from ecoguard.cli import main

ROOT = Path(__file__).resolve().parents[1]


class CliStageTests(unittest.TestCase):
    def test_extract_normalize_and_cbam_stage_files_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            extracted = directory / "extracted.json"
            normalized = directory / "normalized.json"
            cbam = directory / "cbam.json"
            self.assertEqual(
                main(
                    [
                        "extract",
                        str(ROOT / "data/synthetic/trade_case_documents.json"),
                        "--output",
                        str(extracted),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "normalize",
                        str(extracted),
                        "--policy",
                        str(ROOT / "data/reference/normalization_policy.json"),
                        "--output",
                        str(normalized),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(["cbam-calculate", str(normalized), "--output", str(cbam)]),
                0,
            )
            result = json.loads(cbam.read_text(encoding="utf-8"))
            self.assertEqual(
                result["technical_inventory"]["embedded_emissions_tco2e"],
                "1111.36",
            )
            self.assertFalse(result["statutory_calculator"])

    def test_legal_search_exposes_abstention_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "legal.json"
            self.assertEqual(
                main(
                    [
                        "legal-search",
                        "농장 좌표를 지도에 표시하는 방법",
                        "--root",
                        str(ROOT),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["decision"]["status"], "abstained")
            self.assertEqual(result["results"], [])
            self.assertTrue(result["query_trace"]["reason_code"])

    def test_forest_geojson_stage_has_all_reference_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "forest.geojson"
            self.assertEqual(
                main(
                    [
                        "forest-analyze",
                        str(ROOT / "data/synthetic/forest_case.json"),
                        "--geojson",
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["type"], "FeatureCollection")
            self.assertEqual(len(result["features"]), 36)

    def test_invalid_legal_limit_is_rejected_by_cli(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                main(["legal-search", "CBAM 검증 조항", "--limit", "0"])

    def test_benchmark_cli_writes_six_auditable_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                main(
                    [
                        "benchmark",
                        "--root",
                        str(ROOT),
                        "--output",
                        directory,
                    ]
                ),
                0,
            )
            names = {path.name for path in Path(directory).iterdir()}
            self.assertEqual(
                names,
                {
                    "benchmark_manifest.json",
                    "cbam_rule_coverage_report.json",
                    "forest_geospatial.geojson",
                    "forest_geospatial_summary.json",
                    "legal_blind_evaluation.json",
                    "ocr_field_benchmark.json",
                },
            )

        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                main(["benchmark", "--output", directory])


if __name__ == "__main__":
    unittest.main()
