# Repository Guidance

- EcoGuard is a Python 3.11+ reproducibility package for an educational trade-finance PoC.
- Keep runtime code dependency-free unless a new dependency is justified, pinned, and covered by tests.
- Core package inputs must remain synthetic. The optional `research/forest_xai` track may use attributed, redistribution-compatible public research data, but must stay outside the wheel and keep its data/model cards and claim boundary current.
- Preserve field-level provenance through preprocessing and label regulatory or pricing assumptions in every output.
- Treat legal retrieval as decision support: cite official EUR-Lex references and never present output as legal advice.
- Run `python -m unittest discover -s tests -v` and `python -m ecoguard reproduce --output artifacts/generated` before publishing.
- Build release wheels from a clean source snapshot; never trust an in-place `build/` directory or an old generated artifact.
- Freeze public test and artifact counts only after `scripts/verify_release.sh` passes on the final tree.
- Keep core release verification and optional research verification separate: never add research tests, dependencies, metrics, or artifacts to the core's 174-test/wheel claims. Run the research checks through their documented environment and `python -m research.forest_xai.scripts.verify_public_demo`.
- Keep competition-era full decks, static demo variants, and hard-coded scores out of the public tree and history.
- Do not describe the optional public model as bi-temporal change detection. It is single-date forest-cover segmentation; the before/after CNN and JVP path is synthetic. HiGAN, the presentation-era `83.4% → 96.2%`, and satellite-to-3D reconstruction remain unverified or unimplemented until independently reproducible evidence exists.
