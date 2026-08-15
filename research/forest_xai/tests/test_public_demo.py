from __future__ import annotations

from pathlib import Path
import json
import shutil
import tempfile
import unittest

import numpy as np
import torch
from torch import nn

from research.forest_xai.public_training import load_public_checkpoint
from research.forest_xai.public_data import load_public_forest_fixture
from research.forest_xai.scripts.verify_public_demo import (
    EXPECTED_BOUNDARY,
    RETRAINED_CONFUSION_ATOL,
    RETRAINED_METRIC_ATOL,
    RETRAINED_PARAMETER_ATOL,
    RETRAINED_PROBABILITY_ATOL,
    _compare_metric_replay,
    _compare_model_state_replay,
    _compare_numeric_replay,
    verify_committed_public_demo,
)

TRACK_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ARTIFACTS = TRACK_ROOT / "artifacts" / "public_demo"


class PublicForestDemoVerificationTests(unittest.TestCase):
    def test_retrained_state_replay_has_strict_finite_tolerance(self) -> None:
        expected = nn.Linear(2, 1, bias=False)
        actual = nn.Linear(2, 1, bias=False)
        with torch.no_grad():
            expected.weight.zero_()
        actual.load_state_dict(expected.state_dict())
        with torch.no_grad():
            actual.weight[0, 0] += RETRAINED_PARAMETER_ATOL * 0.99
        replay = _compare_model_state_replay(expected, actual)
        self.assertLessEqual(replay["max_absolute_error"], RETRAINED_PARAMETER_ATOL)

        with torch.no_grad():
            actual.weight[0, 0] += RETRAINED_PARAMETER_ATOL * 0.02
        with self.assertRaisesRegex(ValueError, "tensor state differs"):
            _compare_model_state_replay(expected, actual)

        with torch.no_grad():
            actual.weight[0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "non-finite retrained tensor"):
            _compare_model_state_replay(expected, actual)

    def test_retrained_metric_and_probability_replay_bounds_are_strict(self) -> None:
        expected = {
            "f1": 0.9,
            "iou": 0.82,
            "mean_probability": 0.5,
            "pixel_accuracy": 0.91,
            "precision": 0.92,
            "recall": 0.88,
            "threshold": 0.55,
            "tp": 90,
            "fp": 8,
            "fn": 12,
            "tn": 110,
        }
        actual = dict(expected)
        actual["f1"] += RETRAINED_METRIC_ATOL * 0.99
        actual["tp"] -= RETRAINED_CONFUSION_ATOL
        actual["fn"] += RETRAINED_CONFUSION_ATOL
        replay = _compare_metric_replay("test", actual, expected)
        self.assertEqual(replay["threshold"], "exact")

        actual["f1"] = expected["f1"] + RETRAINED_METRIC_ATOL * 1.01
        with self.assertRaisesRegex(ValueError, "floating metrics differs"):
            _compare_metric_replay("test", actual, expected)

        actual = dict(expected)
        actual["tp"] -= RETRAINED_CONFUSION_ATOL + 1
        actual["fn"] += RETRAINED_CONFUSION_ATOL + 1
        with self.assertRaisesRegex(ValueError, "tp differs"):
            _compare_metric_replay("test", actual, expected)

        actual = dict(expected)
        actual["threshold"] = 0.5
        with self.assertRaisesRegex(ValueError, "threshold differs"):
            _compare_metric_replay("test", actual, expected)

        within = np.array([0.0, RETRAINED_PROBABILITY_ATOL * 0.99])
        _compare_numeric_replay(
            "probability", within, np.zeros(2), tolerance=RETRAINED_PROBABILITY_ATOL
        )
        with self.assertRaisesRegex(ValueError, "probability differs"):
            _compare_numeric_replay(
                "probability",
                np.array([RETRAINED_PROBABILITY_ATOL * 1.01]),
                np.zeros(1),
                tolerance=RETRAINED_PROBABILITY_ATOL,
            )
        with self.assertRaisesRegex(ValueError, "non-finite retrained probability"):
            _compare_numeric_replay(
                "probability",
                np.array([float("nan")]),
                np.zeros(1),
                tolerance=RETRAINED_PROBABILITY_ATOL,
            )

    def test_committed_fixture_model_evaluation_and_explanations_verify(self) -> None:
        result = verify_committed_public_demo(TRACK_ROOT)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["training_shape"], [24, 4, 64, 64])
        self.assertEqual(result["evaluation_shape"], [12, 4, 64, 64])
        self.assertEqual(result["scene_overlap"], 0)
        self.assertEqual(result["explanation_files_verified"], 4)
        self.assertEqual(result["claim_boundary"], EXPECTED_BOUNDARY)
        self.assertEqual(result["source_doi"], "https://doi.org/10.5281/zenodo.4498086")
        self.assertEqual(result["source_license"], "CC BY 4.0")
        self.assertEqual(result["evaluation_metrics"]["f1"], 0.947917)
        self.assertFalse(result["claim_boundary"]["bi_temporal_change_detection"])
        self.assertFalse(result["claim_boundary"]["external_independent_benchmark"])

    def test_public_checkpoint_tampering_is_rejected(self) -> None:
        source = PUBLIC_ARTIFACTS / "sentinel2_forest_cover.pt"
        source_sidecar = PUBLIC_ARTIFACTS / "sentinel2_forest_cover.pt.metadata.json"
        with tempfile.TemporaryDirectory(prefix="forest-xai-tamper-test-") as temporary:
            root = Path(temporary)
            checkpoint = root / source.name
            sidecar = root / source_sidecar.name
            shutil.copyfile(source, checkpoint)
            shutil.copyfile(source_sidecar, sidecar)
            with checkpoint.open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "checkpoint SHA-256 mismatch"):
                load_public_checkpoint(checkpoint, torch.device("cpu"))

    def test_manifest_and_sidecar_contracts_reject_ambiguous_json(self) -> None:
        fixture_source = TRACK_ROOT / "data" / "public_fixture"
        with tempfile.TemporaryDirectory(prefix="forest-xai-json-test-") as temporary:
            root = Path(temporary)
            fixture = root / "fixture"
            shutil.copytree(fixture_source, fixture)
            manifest_path = fixture / "manifest.json"
            original = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text(
                original.replace(
                    '"schema_version": "forest-xai-public-fixture/1.0",',
                    '"schema_version": "wrong",\n  '
                    '"schema_version": "forest-xai-public-fixture/1.0",',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_public_forest_fixture(fixture, "train")

            checkpoint = root / "sentinel2_forest_cover.pt"
            sidecar = root / "sentinel2_forest_cover.pt.metadata.json"
            shutil.copyfile(PUBLIC_ARTIFACTS / checkpoint.name, checkpoint)
            source_sidecar = PUBLIC_ARTIFACTS / sidecar.name
            payload = json.loads(source_sidecar.read_text(encoding="utf-8"))
            payload["checkpoint_file"] = "another-file.pt"
            sidecar.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "sidecar contract"):
                load_public_checkpoint(checkpoint, torch.device("cpu"))


if __name__ == "__main__":
    unittest.main()
