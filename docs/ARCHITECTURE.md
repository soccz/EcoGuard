# Architecture

    OCR / table extraction / manual entry adapter
                        │
                        ▼
            raw record boundary (synthetic JSON)
                        │
                        ▼
          normalize aliases, units and candidates
              │              │
              │              └── provenance + review issues
              ▼
          typed regulatory evidence
              ├──────── legal article retriever + citation eval
              ├──────── CBAM exposure scenarios
              └──────── independent synthetic NDVI change baseline
                                  │
                                  ▼
                     JSON + human-review HTML report

## Module contracts

| Module | Input | Output |
|---|---|---|
| preprocessing | OCR-like records | normalized fields, all candidates, source location, issues |
| legal | query and article metadata | ranked citations and evaluation metrics |
| cbam | typed normalized fields | actual/default exposure scenarios and assumptions |
| forest | red/NIR pixels | NDVI deltas, loss flags and SVG |
| report | four module results | scoped evidence packet for human review |

The runtime uses only the Python standard library. The release verification runs the full unit-test suite, reproduction command, wheel installation, and golden-output diff.
