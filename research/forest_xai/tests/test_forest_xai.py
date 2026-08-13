from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import torch

from research.forest_xai.checkpoint import load_checkpoint, sidecar_path
from research.forest_xai.determinism import configure_determinism, resolve_device
from research.forest_xai.explain import (
    explain,
    gradcam,
    gradcam_from_feature_map,
    latent_direction_probe,
)
from research.forest_xai.fixture import (
    FIXTURE_SCOPE,
    fixture_sha256,
    make_synthetic_batch,
)
from research.forest_xai.models import (
    LatentEncoder,
    LatentGenerator,
    LatentScoreClassifier,
    TinyChangeSegmenter,
    TinyForestCoverSegmenter,
)
from research.forest_xai.training import TrainConfig, evaluate, train


class ForestXaiResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        configure_determinism(17)

    def test_synthetic_fixture_is_stable_and_unambiguously_scoped(self) -> None:
        first = make_synthetic_batch(samples=8, image_size=16, seed=17, split="train")
        second = make_synthetic_batch(samples=8, image_size=16, seed=17, split="train")
        self.assertEqual(first.metadata["scope"], FIXTURE_SCOPE)
        self.assertFalse(first.metadata["real_satellite_data"])
        self.assertFalse(first.metadata["real_world_accuracy_claim"])
        self.assertEqual(fixture_sha256(first), fixture_sha256(second))
        self.assertTrue(torch.equal(first.before, second.before))
        self.assertEqual(first.before.shape, (8, 4, 16, 16))
        self.assertEqual(first.mask.shape, (8, 1, 16, 16))

    def test_model_shapes_and_input_guards(self) -> None:
        batch = make_synthetic_batch(samples=2, image_size=16, seed=17, split="train")
        segmenter = TinyChangeSegmenter()
        encoder = LatentEncoder()
        generator = LatentGenerator()
        classifier = LatentScoreClassifier()
        logits = segmenter(batch.before, batch.after)
        latent = encoder(batch.before, batch.after)
        generated = generator(latent)
        self.assertEqual(logits.shape, batch.mask.shape)
        self.assertEqual(latent.shape, (2, 8))
        self.assertEqual(generated.shape, (2, 8, 16, 16))
        self.assertEqual(classifier(latent).shape, (2,))
        with self.assertRaises(ValueError):
            segmenter(batch.before[:, :3], batch.after[:, :3])

    def test_public_axis_model_and_generic_gradcam(self) -> None:
        model = TinyForestCoverSegmenter()
        image = torch.rand(1, 4, 16, 16)
        target = torch.zeros(1, 1, 16, 16)
        target[:, :, 4:10, 3:9] = 1
        features = model.feature_maps(image)
        heatmap, score = gradcam_from_feature_map(model, features, target_mask=target)
        self.assertEqual(model(image).shape, target.shape)
        self.assertEqual(heatmap.shape, target.shape)
        self.assertTrue(torch.isfinite(heatmap).all())
        self.assertGreaterEqual(float(heatmap.min()), 0.0)
        self.assertLessEqual(float(heatmap.max()), 1.0)
        self.assertTrue(np.isfinite(score))

    def test_gradcam_and_jvp_direction_probe_are_finite(self) -> None:
        batch = make_synthetic_batch(
            samples=2, image_size=16, seed=17, split="evaluation"
        )
        selection = slice(1, 2)
        segmenter = TinyChangeSegmenter()
        encoder = LatentEncoder()
        generator = LatentGenerator()
        classifier = LatentScoreClassifier()
        heatmap, score = gradcam(
            segmenter,
            batch.before[selection],
            batch.after[selection],
            target_mask=batch.mask[selection],
        )
        probe, generated, counterfactual = latent_direction_probe(
            encoder,
            generator,
            classifier,
            batch.before[selection],
            batch.after[selection],
            direction_name="increase",
            step=0.05,
        )
        self.assertEqual(heatmap.shape, (1, 1, 16, 16))
        self.assertTrue(torch.isfinite(heatmap).all())
        self.assertTrue(np.isfinite(score))
        self.assertGreater(probe["local_jvp"], 0)
        self.assertTrue(probe["observed_direction_matches_request"])
        self.assertTrue(probe["not_a_reproduction"])
        self.assertTrue(probe["not_a_gan"])
        self.assertEqual(generated.shape, counterfactual.shape)
        self.assertFalse(torch.equal(generated, counterfactual))

    def test_train_evaluate_explain_and_checkpoint_integrity(self) -> None:
        config = TrainConfig(
            seed=17,
            epochs=2,
            train_samples=8,
            evaluation_samples=4,
            image_size=16,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train_result = train(root / "train", config)
            repeated_result = train(root / "repeated", config)
            checkpoint = root / "train" / train_result["checkpoint"]
            evaluation = evaluate(checkpoint, root / "evaluation.json")
            explanation = explain(
                checkpoint,
                root / "explanation",
                sample_index=1,
                direction_name="decrease",
                step=0.05,
            )
            self.assertEqual(train_result["scope"], FIXTURE_SCOPE)
            self.assertEqual(
                train_result["state_dict_sha256"], repeated_result["state_dict_sha256"]
            )
            self.assertEqual(
                train_result["checkpoint_sha256"], repeated_result["checkpoint_sha256"]
            )
            self.assertEqual(train_result["evaluation"], repeated_result["evaluation"])
            self.assertEqual(evaluation["scope"], FIXTURE_SCOPE)
            self.assertEqual(explanation["scope"], FIXTURE_SCOPE)
            self.assertEqual(
                train_result["checkpoint_sha256"], evaluation["checkpoint_sha256"]
            )
            self.assertTrue((root / "explanation" / "gradcam_heatmap.png").is_file())
            self.assertTrue(
                (root / "explanation" / "explanation_tensors.npz").is_file()
            )
            with Image.open(root / "explanation" / "gradcam_heatmap.png") as image:
                self.assertEqual(image.size, (256, 256))
            self.assertTrue(explanation["latent_probe"]["not_a_reproduction"])

            sidecar = json.loads(sidecar_path(checkpoint).read_text())
            self.assertFalse(sidecar["metadata"]["real_satellite_data"])
            self.assertFalse(sidecar["metadata"]["real_world_performance_claim"])
            checkpoint.write_bytes(checkpoint.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_checkpoint(checkpoint, device=torch.device("cpu"))

    def test_resolve_device_does_not_silently_fallback(self) -> None:
        self.assertEqual(str(resolve_device("cpu")), "cpu")
        with self.assertRaises(ValueError):
            resolve_device("tpu")


if __name__ == "__main__":
    unittest.main()
