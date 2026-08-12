# Synthetic OCR adapter fixture

These files contain no scanned participant, company, or competition data.
`synthetic_tesseract.tsv` is a hand-authored Tesseract-compatible interchange
fixture, not output offered as evidence of Tesseract or EcoGuard OCR accuracy.

The fixture deliberately produces two exact fields, one wrong value, one
missing field and one spurious field against `synthetic_field_reference.json`.
This makes precision, recall, mismatch, missing, and spurious accounting
independently testable instead of publishing a hard-coded perfect score.
