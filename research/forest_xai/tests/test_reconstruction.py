from __future__ import annotations

from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from research.forest_xai.checkpoint import file_sha256
from research.forest_xai.cli import build_parser
from research.forest_xai.reconstruction import (
    RECONSTRUCTION_CLAIM_BOUNDARY,
    LatentGanConfig,
    LatentInterpolationConfig,
    ReliefDrapeConfig,
    interpolate_latent_path,
    load_latent_gan,
    render_relief_drape,
    train_latent_gan,
)
from research.forest_xai.scripts.verify_reconstruction import (
    RETRAINED_JVP_ATOL,
    RETRAINED_PROBABILITY_ATOL,
    _compare_array_replay,
    _compare_model_state_replay,
    _compare_numeric_sequence,
    _compare_png_replay,
    verify_committed_reconstruction,
)

import torch


TRACK_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = TRACK_ROOT / "data" / "public_fixture"
RECONSTRUCTION = TRACK_ROOT / "artifacts" / "public_demo" / "reconstruction"
CLASSIFIER = TRACK_ROOT / "artifacts" / "public_demo" / "sentinel2_forest_cover.pt"


class PostAwardReconstructionTests(unittest.TestCase):
    def test_committed_reconstruction_verifier_replays_all_artifacts(self) -> None:
        result = verify_committed_reconstruction(TRACK_ROOT)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["latent_frames"], 8)
        self.assertEqual(result["terrain_files_verified"], 5)
        self.assertEqual(result["mesh"]["vertex_count"], 1089)
        self.assertEqual(result["mesh"]["face_count"], 1024)
        self.assertLessEqual(
            result["latent_contact_sheet_replay"]["max_channel_error"], 2
        )
        self.assertEqual(
            result["latent_probability_replay"]["tolerance"],
            RETRAINED_PROBABILITY_ATOL,
        )
        self.assertEqual(result["latent_jvp_replay"]["tolerance"], RETRAINED_JVP_ATOL)
        self.assertEqual(result["terrain_array_replay"]["faces"]["comparison"], "exact")
        for name in ("height", "probability", "vertices"):
            self.assertLessEqual(
                result["terrain_array_replay"][name]["max_absolute_error"], 1e-6
            )

    def test_latent_gan_training_is_deterministic_and_small(self) -> None:
        config = LatentGanConfig(epochs=4)
        with tempfile.TemporaryDirectory(prefix="forest-xai-recon-") as temporary:
            root = Path(temporary)
            first = train_latent_gan(FIXTURE_ROOT, root / "first", config)
            second = train_latent_gan(FIXTURE_ROOT, root / "second", config)
            self.assertEqual(first["state_dict_sha256"], second["state_dict_sha256"])
            self.assertLess(first["parameter_count"], 100_000)
            generator, _, sidecar = load_latent_gan(
                root / "first" / "latent_gan.pt", torch.device("cpu")
            )
            self.assertEqual(
                sidecar["metadata"]["claim_boundary"],
                RECONSTRUCTION_CLAIM_BOUNDARY,
            )
            with torch.no_grad():
                sample = generator(torch.zeros(1, generator.latent_dim))
            self.assertEqual(tuple(sample.shape), (1, 4, 64, 64))
            self.assertGreaterEqual(float(sample.min()), 0.0)
            self.assertLessEqual(float(sample.max()), 1.0)

    def test_committed_latent_interpolation_reproduces_and_bounds_claims(
        self,
    ) -> None:
        committed = json.loads(
            (RECONSTRUCTION / "latent_interpolation.json").read_text(encoding="utf-8")
        )
        for flag, value in RECONSTRUCTION_CLAIM_BOUNDARY.items():
            self.assertEqual(committed["claim_boundary"][flag], value)
        with tempfile.TemporaryDirectory(prefix="forest-xai-recon-") as temporary:
            result = interpolate_latent_path(
                RECONSTRUCTION / "latent_gan.pt",
                CLASSIFIER,
                Path(temporary),
                LatentInterpolationConfig(
                    seed=committed["seed"], frames=committed["frames"]
                ),
            )
            variable_semantics = {"files", "forest_probabilities", "jvp"}
            self.assertEqual(
                {
                    key: value
                    for key, value in result.items()
                    if key not in variable_semantics
                },
                {
                    key: value
                    for key, value in committed.items()
                    if key not in variable_semantics
                },
            )
            probability_replay = _compare_numeric_sequence(
                "forest probability curve",
                result["forest_probabilities"],
                committed["forest_probabilities"],
                tolerance=RETRAINED_PROBABILITY_ATOL,
            )
            self.assertLessEqual(
                probability_replay["max_absolute_error"],
                RETRAINED_PROBABILITY_ATOL,
            )
            jvp_replay = _compare_numeric_sequence(
                "JVP semantics",
                [
                    result["jvp"]["latent_path_length"],
                    result["jvp"]["unit_path_direction_derivative"],
                ],
                [
                    committed["jvp"]["latent_path_length"],
                    committed["jvp"]["unit_path_direction_derivative"],
                ],
                tolerance=RETRAINED_JVP_ATOL,
            )
            self.assertLessEqual(jvp_replay["max_absolute_error"], RETRAINED_JVP_ATOL)
            self.assertEqual(
                {
                    key: value
                    for key, value in result["jvp"].items()
                    if key
                    not in {"latent_path_length", "unit_path_direction_derivative"}
                },
                {
                    key: value
                    for key, value in committed["jvp"].items()
                    if key
                    not in {"latent_path_length", "unit_path_direction_derivative"}
                },
            )
            replay = _compare_png_replay(
                RECONSTRUCTION / committed["files"]["contact_sheet"]["path"],
                Path(temporary) / result["files"]["contact_sheet"]["path"],
            )
            self.assertLessEqual(replay["max_channel_error"], 2)
        self.assertEqual(
            committed["files"]["contact_sheet"]["sha256"],
            file_sha256(RECONSTRUCTION / "latent_interpolation.png"),
        )

    def test_fast_replay_allows_negligible_probability_and_jvp_rounding(self) -> None:
        committed = json.loads(
            (RECONSTRUCTION / "latent_interpolation.json").read_text(encoding="utf-8")
        )

        def interpolate_with_rounding(*args, **kwargs):
            result = interpolate_latent_path(*args, **kwargs)
            result["forest_probabilities"][0] = (
                committed["forest_probabilities"][0] + 1e-8
            )
            result["jvp"]["latent_path_length"] = (
                committed["jvp"]["latent_path_length"] + 1e-8
            )
            result["jvp"]["unit_path_direction_derivative"] = (
                committed["jvp"]["unit_path_direction_derivative"] - 1e-8
            )
            return result

        with patch(
            "research.forest_xai.reconstruction.interpolate_latent_path",
            side_effect=interpolate_with_rounding,
        ):
            result = verify_committed_reconstruction(TRACK_ROOT)
        self.assertEqual(
            result["latent_probability_replay"]["max_absolute_error"], 1e-8
        )
        self.assertEqual(result["latent_jvp_replay"]["max_absolute_error"], 1e-8)

    def test_fast_replay_keeps_immutable_latent_fields_exact(self) -> None:
        def interpolate_with_changed_seed(*args, **kwargs):
            result = interpolate_latent_path(*args, **kwargs)
            result["seed"] += 1
            return result

        with patch(
            "research.forest_xai.reconstruction.interpolate_latent_path",
            side_effect=interpolate_with_changed_seed,
        ):
            with self.assertRaisesRegex(ValueError, "invariant latent semantics"):
                verify_committed_reconstruction(TRACK_ROOT)

    def test_contact_sheet_replay_rejects_visible_pixel_drift(self) -> None:
        source = RECONSTRUCTION / "latent_interpolation.png"
        with tempfile.TemporaryDirectory(prefix="forest-xai-image-drift-") as temporary:
            changed = Path(temporary) / "changed.png"
            with Image.open(source) as image:
                values = image.convert("RGB")
            pixel = values.getpixel((0, 0))
            values.putpixel((0, 0), ((pixel[0] + 8) % 256, pixel[1], pixel[2]))
            values.save(changed)
            with self.assertRaisesRegex(ValueError, "more than 2/255"):
                _compare_png_replay(source, changed)

    def test_machine_array_replay_rejects_material_float_drift(self) -> None:
        source = RECONSTRUCTION / "terrain_height.npy"
        with tempfile.TemporaryDirectory(prefix="forest-xai-array-drift-") as temporary:
            changed = Path(temporary) / "changed.npy"
            values = np.load(source, allow_pickle=False).copy()
            values.flat[0] += 1e-4
            with changed.open("wb") as handle:
                np.save(handle, values, allow_pickle=False)
            with self.assertRaisesRegex(ValueError, "more than 1e-6"):
                _compare_array_replay(source, changed)

    def test_machine_array_replay_rejects_non_finite_values_on_either_side(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="forest-xai-array-finite-"
        ) as temporary:
            root = Path(temporary)
            reference = root / "reference.npy"
            candidate = root / "candidate.npy"
            finite = np.array([0.25], dtype=np.float32)
            for value in (float("nan"), float("inf")):
                non_finite = np.array([value], dtype=np.float32)
                with self.subTest(value=value, side="reference"):
                    np.save(reference, non_finite, allow_pickle=False)
                    np.save(candidate, finite, allow_pickle=False)
                    with self.assertRaisesRegex(ValueError, "non-finite reference"):
                        _compare_array_replay(reference, candidate)
                with self.subTest(value=value, side="candidate"):
                    np.save(reference, finite, allow_pickle=False)
                    np.save(candidate, non_finite, allow_pickle=False)
                    with self.assertRaisesRegex(ValueError, "non-finite candidate"):
                        _compare_array_replay(reference, candidate)

    def test_retrained_state_replay_rejects_material_parameter_drift(self) -> None:
        expected = torch.nn.Linear(2, 2, bias=False)
        actual = torch.nn.Linear(2, 2, bias=False)
        actual.load_state_dict(expected.state_dict())
        with torch.no_grad():
            actual.weight[0, 0] += 1e-4
        replay = _compare_model_state_replay(
            {"generator": expected}, {"generator": actual}
        )
        self.assertAlmostEqual(replay["max_absolute_error"], 1e-4, places=7)
        with torch.no_grad():
            actual.weight[0, 0] += 1e-3
        with self.assertRaisesRegex(ValueError, "more than 0.0005"):
            _compare_model_state_replay({"generator": expected}, {"generator": actual})

    def test_numeric_replay_enforces_threshold_and_finite_values(self) -> None:
        tolerance = 1e-4
        replay = _compare_numeric_sequence(
            "probe", [0.99 * tolerance], [0.0], tolerance=tolerance
        )
        self.assertAlmostEqual(
            replay["max_absolute_error"], 0.99 * tolerance, places=12
        )
        with self.assertRaisesRegex(ValueError, "more than 0.0001"):
            _compare_numeric_sequence(
                "probe", [1.01 * tolerance], [0.0], tolerance=tolerance
            )
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value, side="actual"):
                with self.assertRaisesRegex(ValueError, "non-finite actual"):
                    _compare_numeric_sequence(
                        "probe", [value], [0.0], tolerance=tolerance
                    )
            with self.subTest(value=value, side="expected"):
                with self.assertRaisesRegex(ValueError, "non-finite expected"):
                    _compare_numeric_sequence(
                        "probe", [0.0], [value], tolerance=tolerance
                    )
        for invalid_tolerance in (
            0.0,
            -tolerance,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(tolerance=invalid_tolerance):
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    _compare_numeric_sequence(
                        "probe", [0.0], [0.0], tolerance=invalid_tolerance
                    )

    def test_committed_relief_drape_reproduces_and_declares_synthetic_height(
        self,
    ) -> None:
        committed = json.loads(
            (RECONSTRUCTION / "terrain_drape.json").read_text(encoding="utf-8")
        )
        self.assertTrue(committed["claim_boundary"]["synthetic_height_field"])
        self.assertTrue(committed["claim_boundary"]["not_satellite_derived_elevation"])
        self.assertTrue(committed["claim_boundary"]["post_award_reconstruction"])
        with tempfile.TemporaryDirectory(prefix="forest-xai-recon-") as temporary:
            result = render_relief_drape(
                FIXTURE_ROOT,
                CLASSIFIER,
                Path(temporary),
                ReliefDrapeConfig(
                    seed=committed["seed"],
                    sample_index=committed["sample_index"],
                    height_grid_size=committed["height_grid_size"],
                    vertical_scale=committed["vertical_scale"],
                ),
            )
            self.assertEqual(result["sample_id"], committed["sample_id"])
            self.assertEqual(
                result["mean_forest_probability"],
                committed["mean_forest_probability"],
            )
            self.assertEqual(
                result["files"]["drape"]["sha256"],
                committed["files"]["drape"]["sha256"],
            )
        self.assertEqual(
            committed["files"]["drape"]["sha256"],
            file_sha256(RECONSTRUCTION / "terrain_drape.png"),
        )

    def test_checkpoint_and_duplicate_sidecar_tampering_are_rejected(self) -> None:
        source_checkpoint = RECONSTRUCTION / "latent_gan.pt"
        source_sidecar = RECONSTRUCTION / "latent_gan.pt.metadata.json"
        with tempfile.TemporaryDirectory(prefix="forest-xai-tamper-") as temporary:
            root = Path(temporary)
            checkpoint = root / "latent_gan.pt"
            sidecar = root / "latent_gan.pt.metadata.json"
            shutil.copyfile(source_checkpoint, checkpoint)
            shutil.copyfile(source_sidecar, sidecar)
            checkpoint.write_bytes(checkpoint.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                load_latent_gan(checkpoint, torch.device("cpu"))

            shutil.copyfile(source_checkpoint, checkpoint)
            original = source_sidecar.read_text(encoding="utf-8")
            sidecar.write_text(
                '{\n  "scope": "injected-claim",' + original[1:],
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_latent_gan(checkpoint, torch.device("cpu"))

    def test_reconstruction_cli_exposes_explicit_contract_controls(self) -> None:
        args = build_parser().parse_args(
            [
                "recon-drape",
                "--fixture-root",
                str(FIXTURE_ROOT),
                "--classifier-checkpoint",
                str(CLASSIFIER),
                "--output-dir",
                "output",
                "--height-grid-size",
                "10",
                "--vertical-scale",
                "1.5",
            ]
        )
        self.assertEqual(args.command, "recon-drape")
        self.assertEqual(args.height_grid_size, 10)
        self.assertEqual(args.vertical_scale, 1.5)

    def test_contact_sheet_expands_without_clipping_nine_frames(self) -> None:
        with tempfile.TemporaryDirectory(prefix="forest-xai-nine-frames-") as temporary:
            result = interpolate_latent_path(
                RECONSTRUCTION / "latent_gan.pt",
                CLASSIFIER,
                Path(temporary),
                LatentInterpolationConfig(frames=9),
            )
            self.assertEqual(result["frames"], 9)
            with Image.open(Path(temporary) / "latent_interpolation.png") as image:
                self.assertEqual(image.size, (1048, 784))


if __name__ == "__main__":
    unittest.main()
