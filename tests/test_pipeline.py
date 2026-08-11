import json
import shutil
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from ecoguard.pipeline import reproduce


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DEMO_MARKERS = (".github.io", "Live Demo")


class PipelineTests(unittest.TestCase):
    def test_pipeline_writes_complete_deterministic_packet(self):
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = reproduce(first_dir, root=ROOT)
            second = reproduce(second_dir, root=ROOT)
            self.assertEqual(set(first), set(second))
            self.assertEqual(
                set(first),
                {
                    "extracted_records",
                    "normalized_evidence",
                    "legal_retrieval_evaluation",
                    "legal_issue_citations",
                    "cbam_exposure",
                    "forest_change",
                    "forest_change_geojson",
                    "forest_change_svg",
                    "evidence_report_json",
                    "evidence_report_html",
                    "artifact_manifest",
                },
            )
            for name in first:
                self.assertTrue(first[name].is_file(), name)
                self.assertEqual(first[name].read_bytes(), second[name].read_bytes())
                expected = ROOT / "artifacts/examples" / first[name].name
                self.assertEqual(first[name].read_bytes(), expected.read_bytes())

            packet = json.loads(
                first["evidence_report_json"].read_text(encoding="utf-8")
            )
            self.assertEqual(packet["decision"]["status"], "human_review_required")
            self.assertEqual(
                packet["classification"], "synthetic educational proof-of-concept"
            )
            self.assertEqual(
                packet["forest_change_baseline"]["relation_to_trade_case"],
                "independent synthetic technical baseline",
            )
            self.assertEqual(
                packet["legal_issue_citations"]["supported_issue_count"],
                2,
            )
            self.assertEqual(packet["legal_issue_citations"]["unmapped_issue_count"], 1)
            self.assertEqual(packet["reproduction"]["schema_version"], "3.0.0")
            self.assertEqual(packet["proof_summary"]["source_document_count"], 7)
            self.assertEqual(packet["proof_summary"]["cbam_trace_step_count"], 11)
            self.assertEqual(packet["proof_summary"]["issue_count"], 3)
            self.assertEqual(packet["proof_summary"]["high_issue_count"], 1)
            self.assertEqual(packet["proof_summary"]["review_issue_count"], 2)

            geojson = json.loads(
                first["forest_change_geojson"].read_text(encoding="utf-8")
            )
            self.assertEqual(len(geojson["features"]), 36)
            manifest = json.loads(
                first["artifact_manifest"].read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["outputs"]), 10)
            for name, details in manifest["outputs"].items():
                self.assertEqual(
                    sha256(first[name].read_bytes()).hexdigest(),
                    details["sha256"],
                )

    def test_generated_html_does_not_publish_live_demo_address(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = reproduce(output_dir, root=ROOT)["evidence_report_html"]
            content = report.read_text(encoding="utf-8")
            for marker in PUBLIC_DEMO_MARKERS:
                self.assertNotIn(marker, content)
            self.assertIn("HUMAN REVIEW REQUIRED", content)

    def test_one_source_line_mutation_changes_lineage_and_cbam_result(self):
        with (
            tempfile.TemporaryDirectory() as root_dir,
            tempfile.TemporaryDirectory() as output_dir,
        ):
            mutated_root = Path(root_dir)
            shutil.copytree(ROOT / "data", mutated_root / "data")
            trade_path = mutated_root / "data/synthetic/trade_case_documents.json"
            original = trade_path.read_text(encoding="utf-8")
            mutated = original.replace("EUR 87.50 / tCO2e", "EUR 88.00 / tCO2e", 1)
            self.assertNotEqual(mutated, original)
            trade_path.write_text(mutated, encoding="utf-8")

            paths = reproduce(output_dir, root=mutated_root)
            normalized = json.loads(
                paths["normalized_evidence"].read_text(encoding="utf-8")
            )
            cbam = json.loads(paths["cbam_exposure"].read_text(encoding="utf-8"))
            manifest = json.loads(
                paths["artifact_manifest"].read_text(encoding="utf-8")
            )
            baseline_normalized = json.loads(
                (ROOT / "artifacts/examples/normalized_evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            baseline_manifest = json.loads(
                (ROOT / "artifacts/examples/artifact_manifest.json").read_text(
                    encoding="utf-8"
                )
            )

            field = normalized["fields"]["certificate_price_eur_per_tco2e"]
            baseline_field = baseline_normalized["fields"][
                "certificate_price_eur_per_tco2e"
            ]
            self.assertEqual(field["value"], "88")
            self.assertNotEqual(
                field["selected_from"]["line_sha256"],
                baseline_field["selected_from"]["line_sha256"],
            )
            self.assertEqual(cbam["actual_data_scenario"]["exposure_eur"], "97799.68")
            self.assertNotEqual(
                manifest["inputs"]["trade_case_documents"]["sha256"],
                baseline_manifest["inputs"]["trade_case_documents"]["sha256"],
            )
            for input_name in set(manifest["inputs"]) - {"trade_case_documents"}:
                self.assertEqual(
                    manifest["inputs"][input_name],
                    baseline_manifest["inputs"][input_name],
                )

    def test_reproduction_performs_no_network_io(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch(
                "socket.socket",
                side_effect=AssertionError("runtime network access is forbidden"),
            ):
                paths = reproduce(output_dir, root=ROOT)
        self.assertEqual(len(paths), 11)

    def test_reproduction_rejects_legal_manifest_corpus_mismatch(self):
        with (
            tempfile.TemporaryDirectory() as root_dir,
            tempfile.TemporaryDirectory() as output_dir,
        ):
            mutated_root = Path(root_dir)
            shutil.copytree(ROOT / "data", mutated_root / "data")
            manifest_path = mutated_root / "data/reference/source_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sources"][0]["celex"] = "32023R9999"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "legal source manifest"):
                reproduce(output_dir, root=mutated_root)


if __name__ == "__main__":
    unittest.main()
