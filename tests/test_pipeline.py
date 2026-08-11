import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

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
            self.assertEqual(packet["reproduction"]["schema_version"], "2.0.0")
            self.assertEqual(packet["proof_summary"]["source_document_count"], 7)
            self.assertEqual(packet["proof_summary"]["cbam_trace_step_count"], 11)

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


if __name__ == "__main__":
    unittest.main()
