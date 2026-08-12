import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ATTESTATION = ROOT / "data/reference/competition_archive_attestation.json"


class CompetitionProvenanceTests(unittest.TestCase):
    def test_private_archive_attestation_is_minimal_and_unambiguous(self):
        payload = json.loads(ATTESTATION.read_text(encoding="utf-8"))
        self.assertEqual(payload["attestation_version"], "1.0")
        self.assertEqual(payload["custodian_attestation"]["github_identity"], "soccz")
        self.assertEqual(len(payload["records"]), 3)
        ids = [record["archive_id"] for record in payload["records"]]
        self.assertEqual(len(ids), len(set(ids)))
        for record in payload["records"]:
            with self.subTest(record=record["archive_id"]):
                self.assertGreater(record["bytes"], 0)
                self.assertRegex(record["sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(
                    record["filesystem_modified_at"],
                    r"^2026-[0-9]{2}-[0-9]{2}T[0-9:]+\+09:00$",
                )
                self.assertNotIn("/", record["archive_id"])
        serialized = ATTESTATION.read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(
                r"/home/|IMG_" + "6351|" + r"\.heic" + "|ecoguard" + "-live",
                serialized,
            )
        )

    def test_document_states_hash_and_timestamp_limits(self):
        document = (ROOT / "docs/COMPETITION_PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn("공인 timestamp", document)
        self.assertIn("대회 당시 그대로 운영된 코드", document)
        self.assertIn("단독 개발 책임", document)


if __name__ == "__main__":
    unittest.main()
