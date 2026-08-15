# Architecture

EcoGuard v0.5는 결과값보다 **evidence lineage와 계산 trace**를 먼저 설계합니다.
모든 운영 시스템 연동은 바깥 adapter로 두고, dependency-free wheel은 합성
입력에서 시작하는 결정론적 core만 포함합니다. 실제 공개 Sentinel-2
derivative를 쓰는 PyTorch 코드는 `research/forest_xai`에 분리해 wheel과 core
검증 수치에 포함하지 않습니다.

```text
synthetic OCR document bundle
  document / page / line / confidence / raw text
                        │
                        ▼
              ingestion.extract_document_bundle
  candidate / character span / line SHA / document SHA
                        │
                        ▼
                  preprocessing.normalize_records
  field / unit / transformation / selection rank / provenance
                        │
             ┌──────────┴───────────┐
             │                      │
             ▼                      ▼
  validation ledger          rule-mapped case issue
  conflict / missing               │
             │                      ▼
             │            legal BM25F citation retrieval
             │            score trace / abstain / eval
             │
             ▼
  CBAM technical inventory
  item × component DAG / reconciliation / sensitivity

  independent synthetic forest case
  red/NIR + reference mask
             │
             ▼
  NDVI mask / confusion metrics / regions / GeoJSON / SVG

             all stage outputs
                    │
                    ▼
  human-review JSON + HTML + artifact SHA-256 manifest

parallel verification benchmarks
  OCR TSV/JSON/text -> field P/R/F1 + error buckets
  geospatial manifest -> CRS/affine/mask/time/tile/holdout evidence
  legal blind-style holdout -> selective retrieval metrics
  official CBAM coverage map -> partial/missing statutory pathways
                    │
                    ▼
  benchmark JSON/GeoJSON + input/output SHA-256 manifest
```

선택형 산림 연구는 core 밖에서 서로 다른 세 축으로 동작합니다.

```text
public CC BY 4.0 Sentinel-2 derivative (single date)
  24 train chips / 12 evaluation chips / 4 bands / 64×64
                         │
                         ▼
       TinyForestCoverSegmenter → forest-cover probability
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       scene-separated metrics   reference-targeted Grad-CAM

programmatically generated before/after four-band pair
                         │
                         ▼
       TinyChangeSegmenter → synthetic change mask
              │                     │
              ▼                     ▼
       segmentation Grad-CAM     local classifier-score JVP

post-award presentation-concept reconstruction
  public train chips → tiny generator + critic
                         │
             z0 → z1 interpolation → forest-score curve + exact JVP

  public evaluation RGB + forest probability + synthetic coarse height
                         │
             x/y-grid bilinear height interpolation → 2.5D drape artifact
```

첫 번째 축은 실제 pixel이지만 **단일시점 forest cover**입니다. 두 번째
축은 before/after이지만 **합성 smoke test**입니다. 세 번째 축은 대회 당시
코드의 복구본이 아니라 발표 아이디어를 공개 입력으로 새로 구현한 **수상 후
재구성**입니다. 세 축을 합쳐 실제 bi-temporal change, HiGAN, 발표 수치
`83.4% → 96.2%`, photorealism 또는 위성에서 고도·3D를 복원했다고 주장하지
않습니다.

## Core stage contracts

| Stage | Input contract | Output contract | Main invariant |
|---|---|---|---|
| ingestion | document bundle v1 | extracted records v2 | input order does not change records; every candidate has a source span and hash |
| preprocessing | extracted records + normalization policy | normalized evidence v3 | no candidate is silently discarded; selection is reproducible |
| legal | 8 article records + 34 eval cases | retrieval decision and citation trace | explicit instrument cannot leak to the other regulation |
| CBAM | normalized typed fields | cbam-scenario/3.0 | component, direct/indirect, process/precursor and shipment totals reconcile |
| forest | forest case v2 + band/reference CSV | mask evaluation + GeoJSON/SVG | grid and reference universe match exactly; output is row-major |
| pipeline | all versioned fixtures | 11 public artifacts | two executions and wheel-installed execution are byte-identical |
| benchmark | 10 synthetic/reference fixtures | 6 benchmark artifacts | offline execution and committed bytes are identical |

## 선택형 산림 연구 contract

| Stage | Input contract | Output contract | Main invariant |
|---|---|---|---|
| public fixture loader | attributed manifest + train/evaluation NPY | validated tensors + scene/sample metadata | hash·shape·dtype·range·scene separation이 틀리면 즉시 실패 |
| public training | 24 train chips + deterministic CPU config | checkpoint + metadata sidecar + train JSON | tensor state·normalization·fixture·threshold·config가 sidecar에 binding |
| public evaluation | 12 evaluation chips + committed checkpoint | forest-cover metrics JSON | scene overlap 0, threshold 0.55, committed metric 전체 일치 |
| public explanation | evaluation sample `S2-EV-003` | RGB·reference·probability·Grad-CAM PNG + JSON | 4개 이미지를 재생성한 SHA-256이 committed manifest와 일치 |
| synthetic change | generated before/after pair + change mask | checkpoint·metric·Grad-CAM·NPZ·JVP trace | synthetic warning, `not_a_gan`, `not_a_reproduction` 경계 유지 |
| reconstruction GAN | public train split + deterministic CPU config | generator/critic checkpoint+sidecar, 8-frame contact sheet+JSON | file/tensor hash; post-award/not-HiGAN/not-photorealistic 경계; unit-path forest-score JVP |
| reconstruction drape | public RGB·probability + deterministic synthetic height | 2.5D JSON/PNG + height/probability/vertices/faces NPY | bilinear interpolation·1089-vertex/1024-face mesh·output hash 재현; synthetic-height/not-satellite-derived-elevation 경계 |

## Adapter and service boundaries

`ocr_adapter.py` converts Tesseract TSV, provider-neutral JSON or pdftotext text into the same document bundle consumed by ingestion. It does not execute an OCR engine. `api.py` exposes CBAM and legal functions through a local WSGI boundary but delegates to the same validators; it does not weaken provenance checks.

The core geospatial benchmark is separate from the compact 6×6 forest
visualization baseline. It validates a fixed projected CRS allow-list, affine
geometry, acquisition/seasonality policy, cloud/nodata masking and tile holdout
accounting. It does not download or reproject satellite scenes. The optional
research fixture commits a small attributed NPY derivative, not a raw-scene
adapter, raster I/O layer, reprojection or co-registration pipeline.

## Evidence identity

Ingestion assigns a deterministic evidence ID such as:

```text
ev-commercial-invoice-p01-l004
```

The candidate also contains:

```json
{
  "document": "commercial_invoice",
  "page": 1,
  "line": 4,
  "source_span": {
    "alias_start": 0,
    "alias_end": 8,
    "value_start": 11,
    "value_end": 21
  },
  "line_sha256": "...",
  "document_sha256": "..."
}
```

Normalization copies this identity into `selected_from`. CBAM leaf operands reference the same evidence ID and source hash. A reviewer can therefore walk backward from exposure → formula step → normalized field → OCR line without relying on an opaque database key.

## Candidate selection

Selection is data-driven by `normalization_policy.json`:

```text
parseable > document authority > extraction confidence > stable order
```

Confidence is only a tie-breaker after document authority. A high-confidence value from a memo cannot automatically override a lower-confidence value from an authoritative sheet. Material conflicts and within-tolerance differences are different output types.

## CBAM calculation DAG

Every technical-inventory multiplication is a node:

```text
m5.process_direct
  = shipment mass evidence × process-direct intensity evidence

m5.component_sum
  = Σ(m5.* component nodes)

shipment.component_sum
  = m5.component_sum + m12.component_sum
```

Leaf nodes require an `evidence_ref`. Analyst-defined sensitivity leaves require an `assumption_ref`. Derived operands require a `derived_from` step ID. Tests evaluate the arithmetic and topological order rather than only comparing the final number.

## Legal retrieval boundary

The retriever is not an LLM. It separates regulation aliases, article, title, keywords, concepts and team-authored summary, applies field-weighted BM25F, and returns:

- normalized query and detected instrument/intent/concepts
- supported/review/abstained decision and reason code
- ranked citation with Article/paragraph metadata and EUR-Lex URL
- word, character, phrase, article and field score trace
- corpus and entry SHA-256

Evaluation reports positive coverage and negative abstention separately so a system cannot inflate apparent accuracy by refusing every query.

## Forest evaluation boundary

`forest_case.json` fixes grid dimensions, thresholds, connectivity, cell size and a synthetic WGS84 transform. Band and reference-mask files must cover the exact same 36-cell universe. Prediction is computed at full `Decimal` precision; rounding occurs only when serializing.

GeoJSON uses one RFC 7946 Polygon Feature per cell. This avoids claiming a geometrically valid dissolved boundary when no GIS union library is present. `region_id` still groups connected predicted cells.

### Public forest-cover boundary

The optional public model accepts one four-band date and emits one forest logit
per pixel. No second date, temporal difference or forest-loss label enters this
path. The evaluation split uses 12 chips from two scenes that do not appear in
the 24-chip, two-scene training split. That separation detects direct scene
leakage but does not turn a maintainer-selected four-scene fixture into an
external benchmark.

Grad-CAM targets the mean forest logit inside the source reference region. It is
bound to the checkpoint and regenerated by the verifier, but it remains a local
sensitivity visualization. It does not explain causation, legality or ecological
validity, and it does not by itself improve or validate a metric.

### Synthetic change and latent boundary

The change model receives programmatically generated before/after pairs. The
JVP differentiates the synthetic classifier score along one local latent
direction and decodes a small step. This proves that the gradient and artifact
paths are executable. It is not a GAN, a HiGAN reproduction, a causal
counterfactual or a semantic latent factor.

### Post-award reconstruction boundary

The reconstruction trains a tiny generator and critic on the committed public
training fixture, walks one deterministic latent path, and differentiates the
committed forest-cover model's mean score along that path. It is new post-award
code, not recovered competition code or a named HiGAN implementation. It has no
photorealism or generative-quality evaluation.

The relief path has a height input, but that input is a deterministic synthetic
coarse field expanded by bilinear interpolation. It drapes real fixture RGB and
model probability for a 2.5D visualization; it does not infer height or geometry
from Sentinel-2. A future licensed DEM drape would still need to be described as
2.5D visualization, not 3D reconstructed from these images.

## Deterministic build

Golden output excludes timestamps, random IDs, absolute paths and host-specific Python versions. JSON uses sorted keys and rejects NaN. Documents and pixels are sorted by stable identifiers.

`scripts/verify_release.sh` proves the package boundary:

1. refuse tracked changes and non-ignored untracked files
2. test, compile, lint and format-check the source tree
3. export clean HEAD twice with `git archive` so tracked bytes, modes and timestamps are canonical
4. build the wheel twice with the commit timestamp as `SOURCE_DATE_EPOCH`
5. require the two wheel SHA-256 digests to match
6. install into a fresh venv and rerun the complete test suite
7. run from outside the repository using packaged fixtures
8. diff every generated byte against `artifacts/examples`

The same verifier also runs the repository-owned benchmark suite and diffs all six files in `artifacts/benchmarks`. Hypothesis checks generated parser/mask invariants, and branch coverage must remain at least 85%.

`artifact_manifest.json` independently records every input and non-manifest output hash.

The optional research track has a separate dependency set and executable
contract:

```bash
python -m unittest discover -s research/forest_xai/tests -v
python -m research.forest_xai.scripts.verify_public_demo
python -m research.forest_xai.scripts.verify_reconstruction
```

Its research test methods, checkpoints, model metrics and explanation/reconstruction artifacts are not
added to the core's 174 test methods, wheel or golden-artifact counts. Appending
`--retrain` to the public verifier additionally repeats the 80-epoch CPU
training and compares tensor state, metadata and metrics. Appending `--retrain`
to the reconstruction verifier additionally repeats the tiny-GAN CPU training
and compares its invariant metadata exactly, parameters and derived numeric
semantics within the documented CPU-kernel tolerances, and bounded decoded
preview replay.
