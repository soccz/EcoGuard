import copy
import json
import re
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
            paths = reproduce(output_dir, root=ROOT)
            cls.packet = json.loads(
                paths["evidence_report_json"].read_text(encoding="utf-8")
            )
            cls.svg = paths["forest_change_svg"].read_text(encoding="utf-8")

    def test_actual_emissions_are_rendered_from_calculation_result(self):
        packet = copy.deepcopy(self.packet)
        packet["cbam_exposure"]["actual_data_scenario"][
            "embedded_emissions_tco2e"
        ] = "2222.72"
        rendered = render_html(packet, "<svg></svg>")
        self.assertIn("2222.72 tCO₂e", rendered)
        self.assertNotIn("1,111.36 tCO₂e", rendered)

    def test_decision_reason_reflects_issue_state(self):
        normalized = copy.deepcopy(self.packet["normalized_evidence"])
        normalized["issues"] = []
        normalized["summary"]["high_issue_count"] = 0
        normalized["summary"]["review_issue_count"] = 0
        packet = build_evidence_packet(
            self.packet["extraction"],
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

    def test_report_exposes_each_proof_layer_and_metric_boundary(self):
        rendered = render_html(self.packet, self.svg)
        for marker in (
            "Document ingestion and lineage",
            "Normalization, selection and review ledger",
            "Legal citation retrieval baseline",
            "CBAM component trace and price sensitivity",
            "Synthetic forest reference-mask evaluation",
            "Reproduction inputs",
            "970.50",
            "140.86",
            "11 / 1",
            "not real-world model accuracy",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, rendered)
        self.assertIn("false support 0.0%", rendered)
        self.assertIn("일반 법률 정확도가 아닙니다", rendered)
        self.assertIn("법정 의무액이 아닙니다", rendered)

    def test_report_contains_no_live_demo_or_automatic_approval_claim(self):
        rendered = render_html(self.packet, self.svg)
        for forbidden in (".github.io", "Live Demo", "AUTO APPROVED", "amount due"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_status_pills_meet_normal_text_contrast(self):
        rendered = render_html(self.packet, self.svg)

        def luminance(hex_color):
            channels = [
                int(hex_color[index : index + 2], 16) / 255 for index in (0, 2, 4)
            ]
            linear = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        for variable in ("warn", "high", "info"):
            with self.subTest(variable=variable):
                match = re.search(rf"--{variable}:#([0-9a-f]{{6}})", rendered)
                self.assertIsNotNone(match)
                contrast = 1.05 / (luminance(match.group(1)) + 0.05)
                self.assertGreaterEqual(contrast, 4.5)


if __name__ == "__main__":
    unittest.main()
