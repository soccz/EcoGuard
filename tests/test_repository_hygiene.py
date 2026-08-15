import re
import unittest
from pathlib import Path
from urllib.parse import unquote

from ecoguard import __version__


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^]]*\]\(([^)]+)\)")


class RepositoryHygieneTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        missing = []
        markdown_files = [ROOT / "README.md"]
        markdown_files.extend(sorted((ROOT / "docs").glob("*.md")))
        markdown_files.extend(sorted((ROOT / "data").glob("**/README.md")))
        markdown_files.extend(
            ROOT / name for name in ("CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md")
        )
        for document in markdown_files:
            text = document.read_text(encoding="utf-8")
            for match in MARKDOWN_LINK.finditer(text):
                target = match.group(1).strip().split(maxsplit=1)[0]
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                relative = unquote(target.split("#", 1)[0])
                if relative and not (document.parent / relative).resolve().exists():
                    missing.append(f"{document.relative_to(ROOT)} -> {relative}")
        self.assertEqual(missing, [])

    def test_readme_pins_current_release_and_separates_claim_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"--branch v{__version__}", readme)
        self.assertIn("partial 8, not implemented 7, implemented 0", readme)
        self.assertIn("외부 blind", readme)
        self.assertIn("OCR engine 자체 성능", readme)
        self.assertIn("인증 없는 로컬 예제", readme)

    def test_public_tree_excludes_private_presentation_and_live_endpoints(self):
        tracked_like_files = [path for path in ROOT.rglob("*") if path.is_file()]
        names = {path.name.casefold() for path in tracked_like_files}
        self.assertFalse(
            any(name.endswith((".heic", ".heif", ".ppt", ".pptx")) for name in names)
        )
        forbidden = ("gkfla" + "2020-bit", "ecoguard" + "-live/")
        findings = []
        for path in tracked_like_files:
            if any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for value in forbidden:
                if value.casefold() in text.casefold():
                    findings.append(f"{path.relative_to(ROOT)}: {value}")
        self.assertEqual(findings, [])

    def test_security_and_automation_files_exist(self):
        required = (
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CITATION.cff",
            ".github/CODEOWNERS",
            ".github/dependabot.yml",
            ".github/workflows/codeql.yml",
            ".github/workflows/forest-xai.yml",
            ".github/workflows/verify.yml",
        )
        self.assertEqual(
            [relative for relative in required if not (ROOT / relative).is_file()],
            [],
        )

    def test_tag_release_waits_for_retrained_forest_research(self):
        release_workflow = (ROOT / ".github/workflows/verify.yml").read_text(
            encoding="utf-8"
        )
        research_workflow = (ROOT / ".github/workflows/forest-xai.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("workflow_call:", research_workflow)
        self.assertIn("uses: ./.github/workflows/forest-xai.yml", release_workflow)
        release_job = release_workflow.split("\n  release:\n", maxsplit=1)[1]
        self.assertRegex(release_job, r"needs:\n\s+- verify\n\s+- research")
        self.assertIn("verify_public_demo --retrain", research_workflow)
        self.assertIn("verify_reconstruction --retrain", research_workflow)


if __name__ == "__main__":
    unittest.main()
