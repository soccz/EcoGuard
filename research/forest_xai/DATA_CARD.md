# Public Sentinel-2 forest fixture data card

This optional research fixture exists to prove that the forest model code can
cross a **real public satellite-data boundary**. It is deliberately separate
from EcoGuard's dependency-free synthetic release benchmark.

## Source and license

- Original dataset: Bragagnolo, da Silva, and Grzybowski,
  [*Amazon and Atlantic Forest image datasets for semantic segmentation*](https://doi.org/10.5281/zenodo.4498086),
  Zenodo, 2021.
- License: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
- Machine-readable Parquet conversion used by the preparation script:
  [NickBurns/amazon-sentinel2-forest-segmentation](https://huggingface.co/datasets/NickBurns/amazon-sentinel2-forest-segmentation).
- Sensor/product: Sentinel-2 Level-2A; bands B4, B3, B2, and B8.
- Label: binary forest cover mask supplied with the source dataset.

The source mirror commit, shard URLs, complete SHA-256 values, selected row
indices, original filenames, and scene IDs are fixed in `manifest.json` and
`scripts/prepare_public_fixture.py`.

The original Zenodo description says its bands were converted to byte values,
while the Parquet mirror's committed tensors contain larger integer values. The
preparation script therefore does not claim radiometric calibration: it pins the
mirror bytes and applies one explicit model-input transform,
`clip(value / 10000, 0, 1)`. Rebuilding from a different conversion requires a
new manifest and evaluation; these arrays must not be interpreted as scientific
surface reflectance without returning to the original GeoTIFF metadata.

## Committed derivative

The repository contains 24 train and 12 evaluation chips. Each source chip is
reduced from 512×512 to 64×64 with non-overlapping 8×8 means. The mask uses a
50% forest-coverage rule over the same blocks. Train and evaluation scene IDs
are disjoint; the loader rejects any file whose hash, shape, dtype, range, or
manifest contract differs.

This small derivative is committed so a CPU-only reviewer can train, evaluate,
and explain a model without downloading 1.1GB of source Parquet data. Rebuild it
from the pinned sources with:

```bash
python -m pip install pyarrow==23.0.1 numpy==1.26.4
python research/forest_xai/scripts/prepare_public_fixture.py \
  --cache /tmp/ecoguard-forest-source \
  --output research/forest_xai/data/public_fixture
```

## What it proves

- loading and validating real multi-band Sentinel-2 arrays;
- a scene-separated train/evaluation boundary;
- CNN forest-cover segmentation, checkpointing, metrics, and Grad-CAM;
- reproducible attribution to source files and licensed data.

## What it does not prove

- bi-temporal forest-loss or deforestation detection;
- why forest cover changed, whether the change is legal, or EUDR compliance;
- external independent validation or production performance;
- the presentation-era 83.4%/96.2% figures.

The synthetic paired-image track tests change-model and latent-JVP mechanics.
The public Sentinel-2 track tests real forest-cover data handling. Their metrics
must never be merged.
