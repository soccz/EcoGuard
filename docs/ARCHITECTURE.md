# Architecture

EcoGuard v0.5는 결과값보다 **evidence lineage와 계산 trace**를 먼저 설계합니다. 모든 운영 시스템 연동은 바깥 adapter로 두고, 공개 패키지는 합성 입력에서 시작하는 결정론적 core만 포함합니다.

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

## Stage contracts

| Stage | Input contract | Output contract | Main invariant |
|---|---|---|---|
| ingestion | document bundle v1 | extracted records v2 | input order does not change records; every candidate has a source span and hash |
| preprocessing | extracted records + normalization policy | normalized evidence v3 | no candidate is silently discarded; selection is reproducible |
| legal | 8 article records + 34 eval cases | retrieval decision and citation trace | explicit instrument cannot leak to the other regulation |
| CBAM | normalized typed fields | cbam-scenario/3.0 | component, direct/indirect, process/precursor and shipment totals reconcile |
| forest | forest case v2 + band/reference CSV | mask evaluation + GeoJSON/SVG | grid and reference universe match exactly; output is row-major |
| pipeline | all versioned fixtures | 11 public artifacts | two executions and wheel-installed execution are byte-identical |
| benchmark | 10 synthetic/reference fixtures | 6 benchmark artifacts | offline execution and committed bytes are identical |

## Adapter and service boundaries

`ocr_adapter.py` converts Tesseract TSV, provider-neutral JSON or pdftotext text into the same document bundle consumed by ingestion. It does not execute an OCR engine. `api.py` exposes CBAM and legal functions through a local WSGI boundary but delegates to the same validators; it does not weaken provenance checks.

The geospatial benchmark is separate from the compact 6×6 forest visualization baseline. It validates a fixed projected CRS allow-list, affine geometry, acquisition/seasonality policy, cloud/nodata masking and tile holdout accounting. It does not download or reproject satellite scenes.

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
