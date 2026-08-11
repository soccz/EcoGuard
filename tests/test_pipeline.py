import json
import tempfile
import unittest
from pathlib import Path

from ecoguard.pipeline import reproduce


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DEMO_MARKERS = (".github.io", "Live Demo")


class PipelineTests(unittest.TestCase):
    def test_pipeline_writes_complete_deterministic_packet(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = reproduce(first_dir, root=ROOT)
            second = reproduce(second_dir, root=ROOT)
            self.assertEqual(set(first), set(second))
            for name in first:
                self.assertTrue(first[name].is_file(), name)
                self.assertEqual(first[name].read_bytes(), second[name].read_bytes())
                expected = ROOT / "artifacts/examples" / first[name].name
                self.assertEqual(first[name].read_bytes(), expected.read_bytes())

            packet = json.loads(
                first["evidence_report_json"].read_text(encoding="utf-8")
            )
            self.assertEqual(packet["decision"]["status"], "human_review_required")
            self.assertEqual(packet["classification"], "synthetic educational proof-of-concept")
            self.assertEqual(
                packet["forest_change_baseline"]["relation_to_trade_case"],
                "independent synthetic technical baseline",
            )
            self.assertEqual(
                packet["legal_issue_citations"]["supported_issue_count"],
                3,
            )
            self.assertEqual(packet["reproduction"]["schema_version"], "1.0.0")

    def test_generated_html_does_not_publish_live_demo_address(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = reproduce(output_dir, root=ROOT)["evidence_report_html"]
            content = report.read_text(encoding="utf-8")
            for marker in PUBLIC_DEMO_MARKERS:
                self.assertNotIn(marker, content)
            self.assertIn("HUMAN REVIEW REQUIRED", content)


if __name__ == "__main__":
    unittest.main()
