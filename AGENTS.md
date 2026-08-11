# Repository Guidance

- EcoGuard is a Python 3.11+ reproducibility package for an educational trade-finance PoC.
- Keep runtime code dependency-free unless a new dependency is justified, pinned, and covered by tests.
- Public inputs must remain synthetic. Do not add participant data, private endpoints, real company records, or the non-public demo URL.
- Preserve field-level provenance through preprocessing and label regulatory or pricing assumptions in every output.
- Treat legal retrieval as decision support: cite official EUR-Lex references and never present output as legal advice.
- Run `python -m unittest discover -s tests -v` and `python -m ecoguard reproduce --output artifacts/generated` before publishing.
- Keep competition-era full decks, static demo variants, and hard-coded scores out of the public tree and history.
