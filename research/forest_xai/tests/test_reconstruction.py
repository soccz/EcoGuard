from __future__ import annotations

from pathlib import Path
import json
import shutil
import tempfile
import unittest

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
            self.assertEqual(
                result["forest_probabilities"],
                committed["forest_probabilities"],
            )
            self.assertEqual(result["jvp"], committed["jvp"])
            self.assertEqual(
                result["files"]["contact_sheet"]["sha256"],
                committed["files"]["contact_sheet"]["sha256"],
            )
        self.assertEqual(
            committed["files"]["contact_sheet"]["sha256"],
            file_sha256(RECONSTRUCTION / "latent_interpolation.png"),
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
