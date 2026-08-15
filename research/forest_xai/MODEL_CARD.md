# Sentinel-2 forest-cover capability model card

## Summary

| Field | Value |
|---|---|
| Model | `TinyForestCoverSegmenter` |
| Research-track version | `0.1.0` |
| Task | Single-date binary forest-cover segmentation |
| Input | Four Sentinel-2 L2A bands, `[N, 4, 64, 64]` |
| Band order | B4 (red), B3 (green), B2 (blue), B8 (near infrared) |
| Output | One forest logit per pixel; committed threshold `0.55` |
| Parameters | 2,929 |
| Training target | CPU, deterministic seed `20260812` |
| Status | Optional research capability demonstration, not a production model |

This card applies only to the committed public-data model in
`artifacts/public_demo/`. It does not apply to the separate synthetic
before/after change and JVP smoke test.

## Intended use

The model demonstrates that the optional research code can:

- validate and load attributed real public Sentinel-2 arrays;
- train a compact convolutional forest-cover segmenter;
- reproduce checkpoint-bound evaluation metrics; and
- generate a model-specific Grad-CAM trace.

It is suitable for code review, local reproducibility checks, and further
research prototyping. It must not be used to determine forest loss,
deforestation, causation, legality, EUDR compliance, financing eligibility, or
any operational decision.

## Architecture and preprocessing

The model has two padded `3×3` convolutions with SiLU activations and one `1×1`
segmentation head. It preserves the `64×64` spatial grid. The pinned Parquet
mirror integers were clipped after division by 10,000, then reduced from
`512×512` to `64×64` with non-overlapping `8×8` means. This is a deterministic
model-input transform, not a claim of calibrated surface reflectance; the data
card records the source-card/mirror representation caveat. Training-split
channel means and standard deviations stored in the checkpoint sidecar are
applied at inference.

The output is a single-date **forest-cover** probability. There is no second
date, temporal differencing, change class, or deforestation label anywhere in
this model path.

## Data

The source is *Amazon and Atlantic Forest image datasets for semantic
segmentation* by Bragagnolo, da Silva, and Grzybowski, distributed under CC BY
4.0 at [Zenodo DOI 10.5281/zenodo.4498086](https://doi.org/10.5281/zenodo.4498086).
The reproducible preparation path uses the attributed Parquet mirror documented
in [DATA_CARD.md](DATA_CARD.md).

The committed derivative is intentionally small and maintainer-selected:

| Split | Chips | Source scenes | Shape |
|---|---:|---:|---|
| Train | 24 | 2 | `[24, 4, 64, 64]` |
| Evaluation | 12 | 2 | `[12, 4, 64, 64]` |

Train and evaluation scene IDs are disjoint, but this is **not an independent
external benchmark**. Maintainers selected the rows and inspected the pipeline.
The fixture exists to demonstrate a real public-data boundary on CPU, not to
estimate generalization across geography, season, sensor conditions, or time.

## Training

- 80 full-batch epochs on CPU
- Adam, learning rate `0.02`
- positive-class-weighted binary cross entropy
- convolution width `16`
- deterministic PyTorch algorithms and one CPU thread
- threshold `0.55`, selected on the training split from fixed candidates

The checkpoint records configuration, scene IDs, normalization values, fixture
hashes, PyTorch version, deterministic settings, tensor-state SHA-256, and the
checkpoint-file SHA-256.

## Evaluation result

Re-evaluating the committed checkpoint on the 12-chip maintainer-selected
evaluation fixture produces:

| Metric | Value |
|---|---:|
| F1 | **0.947917** |
| Precision | 0.979623 |
| Recall | 0.918200 |
| IoU | 0.900991 |
| Pixel accuracy | 0.947550 |
| TP / FP / FN / TN | 23,460 / 488 / 2,090 / 23,114 |

These numbers describe only this small, non-independent **forest-cover
capability fixture**. They are not change-detection or deforestation performance,
not field validation, and not comparable to presentation-era figures.

## Explanation artifact

The committed explanation uses evaluation sample `S2-EV-003`. Grad-CAM targets
the mean forest logit over pixels marked by the source reference mask. This
choice makes the visualization auditable but also means the reference label
defines the region being explained. Grad-CAM is a local model-sensitivity view;
it is not a causal explanation, ecological attribution, or proof that the model
uses a scientifically valid feature.

The RGB preview, reference mask, probability map, and Grad-CAM image are all
bound by SHA-256 values in `artifacts/public_demo/explanation/explanation.json`.

## Limitations and risks

- Four selected scenes and 36 chips cannot establish geographic or seasonal
  generalization.
- Downsampling removes fine boundaries and small forest structures.
- The fixture has no explicit cloud, shadow, atmospheric-quality, or temporal
  robustness evaluation.
- Row selection is maintainer-authored; the evaluation is not blinded or
  independent.
- Threshold selection used the training split; probability calibration was not
  evaluated.
- Pixel metrics can be dominated by spatial autocorrelation and common classes.
- The model can learn acquisition or preprocessing artifacts rather than forest
  semantics.
- No uncertainty estimate, human review protocol, monitoring, or operational
  safety case is provided.
- SHA-256 detects byte mismatch; it is not a digital signature, trusted
  timestamp, authorship proof, or guarantee that the source labels are correct.

## Reproduction and integrity

Fast verification reloads every fixture array, rejects hash/shape/range errors,
checks scene separation, loads the checkpoint with `weights_only=True` only
after its file SHA-256 matches the committed sidecar, reproduces evaluation
JSON, regenerates the explanation, and compares all image hashes. This
hardening covers the committed, hash-pinned checkpoint only, not arbitrary
external checkpoints:

```bash
python research/forest_xai/scripts/verify_public_demo.py
```

The optional full CPU retraining is deliberately outside the normal unit-test
loop:

```bash
python research/forest_xai/scripts/verify_public_demo.py --retrain
```

The retraining audit keeps immutable metadata, threshold, and positive/negative
pixel populations exact. It bounds raw parameters and probability maps at
`5e-4`, loss and floating metrics at `5e-5`, and each confusion count at one
pixel. CPU kernels may round the final parameter bits differently, so the
retrained tensor-state SHA-256 and serialized container bytes need not equal the
committed values. Every generated checkpoint and tensor state is still checked
against the SHA-256 values in its own sidecar.

Committed checkpoint SHA-256:
`270fe3c7f857cfee541240ae8af09968e76b194c367539904c64f619953f168c`.
Committed tensor-state SHA-256:
`cd89eb6b8589d5ae1d0d3a775de911cb026af685fd023b5dc2949e4f4257293e`.
