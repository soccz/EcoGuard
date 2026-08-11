import copy
import json
import tempfile
import unittest
from pathlib import Path

from ecoguard.pipeline import reproduce
from ecoguard.report import build_evidence_packet, render_html


ROOT = Path(__file__).resolve().parents[1]


class EvidenceReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as output_dir:
            report = reproduce(output_dir, root=ROOT)["evidence_report_json"]
            cls.packet = json.loads(report.read_text(encoding="utf-8"))

    def test_actual_emissions_are_rendered_from_calculation_result(self):
        packet = copy.deepcopy(self.packet)
        packet["cbam_exposure"]["actual_data_scenario"][
            "embedded_emissions_tco2e"
        ] = "2222.72"
        rendered = render_html(packet, "<svg></svg>")
        self.assertIn("2222.72 tCO2e", rendered)
        self.assertNotIn("1,111.36 tCO2e", rendered)

    def test_decision_reason_reflects_issue_state(self):
        normalized = copy.deepcopy(self.packet["normalized_evidence"])
        normalized["issues"] = []
        packet = build_evidence_packet(
            normalized,
            self.packet["legal_retrieval_evaluation"],
            self.packet["legal_issue_citations"],
            self.packet["cbam_exposure"],
            self.packet["forest_change_baseline"],
        )
        self.assertEqual(
            packet["decision"]["reason"],
            "교육용 PoC는 자동 승인하지 않으며 사람이 최종 검토합니다.",
        )
        self.assertIn("모든 사례 입력", packet["boundaries"][0])


if __name__ == "__main__":
    unittest.main()
