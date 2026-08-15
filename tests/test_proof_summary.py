import copy
import tempfile
import unittest
from pathlib import Path

from scripts.proof_summary import (
    ProofError,
    _check_file,
    _load_json,
    _validate_research_claims,
    collect_proof,
    format_summary,
)

ROOT = Path(__file__).resolve().parents[1]


class ProofSummaryTests(unittest.TestCase):
    def test_committed_proof_is_valid_and_names_claim_boundaries(self):
        proof = collect_proof(ROOT)
        summary = format_summary(proof)

        self.assertIn("[PASS] OCR/provenance", summary)
        self.assertIn("11-step DAG", summary)
        self.assertIn("EUR-Lex-bound", summary)
        self.assertIn("single-date forest-cover", summary)
        self.assertIn("post-award GAN/2.5D", summary)
        self.assertIn("not HiGAN", summary)
        self.assertEqual(proof["lineage"]["span"], "[13,26)")
        self.assertEqual(proof["cbam"]["total"], "1111.36")

    def test_core_artifact_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            normalized = ROOT / "artifacts/examples/normalized_evidence.json"
            tampered = Path(temporary) / normalized.name
            tampered.write_bytes(normalized.read_bytes() + b" ")
            manifest = _load_json(ROOT / "artifacts/examples/artifact_manifest.json")

            with self.assertRaisesRegex(ProofError, "byte-size mismatch"):
                _check_file(tampered, manifest["outputs"]["normalized_evidence"])

    def test_research_claim_boundary_tampering_fails_closed(self):
        base = ROOT / "research/forest_xai/artifacts/public_demo"
        evaluation = _load_json(base / "evaluation.json")
        latent = _load_json(base / "reconstruction/latent_interpolation.json")
        terrain = copy.deepcopy(_load_json(base / "reconstruction/terrain_drape.json"))
        terrain["claim_boundary"]["not_satellite_derived_elevation"] = False

        with self.assertRaisesRegex(ProofError, "terrain boundary missing"):
            _validate_research_claims(evaluation, latent, terrain)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as temporary:
            duplicate = Path(temporary) / "duplicate.json"
            duplicate.write_text('{"proof": 1, "proof": 2}', encoding="utf-8")
            with self.assertRaisesRegex(ProofError, "duplicate JSON object key"):
                _load_json(duplicate)

            nonfinite = Path(temporary) / "nonfinite.json"
            nonfinite.write_text('{"proof": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ProofError, "non-finite JSON number"):
                _load_json(nonfinite)


if __name__ == "__main__":
    unittest.main()
