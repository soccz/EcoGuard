# Contributing

Contributions must preserve EcoGuard's central rule: a public technical claim needs a synthetic input, a deterministic implementation, a failure boundary and an executable test.

## Development loop

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
PYTHONPATH=src python -m unittest discover -s tests -v
```

Before a pull request, commit the intended files and run the release verifier from a clean worktree:

```bash
./scripts/verify_release.sh
```

It enforces branch coverage, lint, format, schema validation, two byte-identical wheel builds, installed-wheel tests, execution outside the repository and byte-identical golden artifacts.

## Data and claims

- Commit only synthetic cases unless a new public-data adapter is optional, license-documented and checksum-pinned.
- Never commit participant applications, private endpoints, credentials, personal contact details or the original Live Demo address.
- Keep OCR confidence, raw line, source span and hashes intact across adapters.
- Legal changes must cite official EUR-Lex identifiers and retain abstention tests.
- CBAM changes must separate technical inventory and sensitivity from statutory obligation.
- Forest metrics must state the reference universe, split, cloud/nodata policy and whether inputs are synthetic.
- Regenerate golden artifacts only after reviewing the semantic diff. Do not update expected files merely to make a test pass.

## Pull request evidence

Describe the claim being changed, its input, the direct test, the expected artifact difference and any limitation that remains. New optional dependencies must be pinned, justified and excluded from the dependency-free runtime unless essential.
