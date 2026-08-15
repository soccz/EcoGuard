# Changelog

All notable public reconstruction changes are recorded here. Competition-era private implementation is mapped separately in [COMPETITION_PROVENANCE.md](docs/COMPETITION_PROVENANCE.md).

## [Unreleased]

## [0.6.0] - 2026-08-15

### Added

- Optional `research/forest_xai` track, isolated from the dependency-free wheel
- attributed public Sentinel-2 single-date forest-cover fixture, compact CNN,
  checkpoint, evaluation, model/data cards, and Grad-CAM artifacts
- synthetic paired-image change CNN and exact local classifier-score JVP smoke test
- post-award reconstruction of two presentation-era forest concepts: a small
  public-fixture GAN with deterministic latent interpolation and forest-score
  JVP, plus a 2.5D drape over a synthetic bilinearly interpolated height field
- committed reconstruction checkpoint, metadata sidecar, interpolation/drape
  artifacts, reconstruction card, and a separate hash-bound verifier
- separate CPU research workflow and fast/full reproducibility verifiers
- PyTorch 2.13 CPU checkpoint loading with `weights_only=True`, file/tensor hashes,
  exact metadata sidecars, and tamper regression tests

### Changed

- core `make verify` now also lints and byte-compiles `research/forest_xai`
  (research tests, dependencies, metrics and artifacts stay outside core counts)
- research Makefile targets now separate test, public-model verification, and
  post-award reconstruction verification from the core release gate
- competition provenance now records the attempted GAN latent and z/field
  visualization concepts without treating the post-award code as contemporary
  evidence

### Boundaries

- no claim of real bi-temporal forest-loss detection, HiGAN reproduction,
  presentation-era score reproduction, photorealistic generation, or
  satellite-derived elevation/3D reconstruction

## [0.5.0] - 2026-08-12

### Added

- OCR engine-output adapters and a field-level synthetic benchmark
- geospatial forest benchmark contracts and spatial holdout evaluation
- maintainer-authored blind-style legal holdout and machine-readable CBAM rule coverage
- local dependency-free HTTP integration boundary
- property-based parser and mask invariants, branch-coverage gate and security documentation
- shared UTF-8 strict-JSON boundary, exact evidence/corpus contracts and claim-inflation regression tests

## [0.4.1] - 2026-08-12

- Made the Git tag archive the canonical release source.
- Proved local and GitHub Release wheels byte-identical.
- Published the four-page case-study PDF with release checks.

## [0.4.0] - 2026-08-12

- Added Python 3.11–3.13 CI and tag-gated GitHub Releases.
- Enforced clean tracked source, two identical wheel builds and installed-wheel golden replay.
- Clarified @soccz's core-engine development responsibility and the three-person team's joint award.

## [0.3.0] - 2026-08-11

- Hardened numeric parsing, candidate completeness, source hashes and legal source binding.
- Added component-level CBAM DAG and reference-mask forest evaluation.

[0.6.0]: https://github.com/soccz/EcoGuard/releases/tag/v0.6.0
[0.5.0]: https://github.com/soccz/EcoGuard/releases/tag/v0.5.0
[0.4.1]: https://github.com/soccz/EcoGuard/releases/tag/v0.4.1
[0.4.0]: https://github.com/soccz/EcoGuard/releases/tag/v0.4.0
[0.3.0]: https://github.com/soccz/EcoGuard/releases/tag/v0.3.0
