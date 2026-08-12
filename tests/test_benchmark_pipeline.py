import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecoguard.benchmark import INPUT_PATHS, run_benchmarks


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkPipelineTests(unittest.TestCase):
    def test_suite_writes_all_outputs_deterministically(self):
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = run_benchmarks(first_dir, root=ROOT)
            second = run_benchmarks(second_dir, root=ROOT)
            self.assertEqual(
                set(first),
                {
                    "ocr_field_benchmark",
                    "forest_geospatial_summary",
                    "forest_geospatial_geojson",
                    "legal_blind_evaluation",
                    "cbam_rule_coverage_report",
                    "benchmark_manifest",
                },
            )
            for name in first:
                with self.subTest(output=name):
                    self.assertEqual(
                        first[name].read_bytes(), second[name].read_bytes()
                    )
                    golden = ROOT / "artifacts/benchmarks" / first[name].name
                    self.assertEqual(first[name].read_bytes(), golden.read_bytes())

    def test_manifest_hashes_every_input_and_non_manifest_output(self):
        manifest = json.loads(
            (ROOT / "artifacts/benchmarks/benchmark_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(manifest["inputs"]), set(INPUT_PATHS))
        self.assertEqual(len(manifest["outputs"]), 5)
        self.assertFalse(manifest["policy"]["external_network_io"])

    def test_suite_performs_no_network_io(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("benchmark attempted network I/O")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(socket, "create_connection", side_effect=forbidden),
            patch.object(socket.socket, "connect", side_effect=forbidden),
        ):
            run_benchmarks(directory, root=ROOT)


if __name__ == "__main__":
    unittest.main()
