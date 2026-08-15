# EcoGuard 문서 지도

이 문서는 질문별 시작점입니다. 검증된 릴리스와 현재 포트폴리오의 범위를 먼저
나누면 나머지 문서를 훨씬 빠르게 읽을 수 있습니다.

- **전체 고정 릴리스 재현:** [`v0.6.0` tag quickstart](../README.md#재현-범위부터-선택하기)는
  dependency-free core와 별도 Forest XAI 연구 트랙이 함께 있는 공개 tree를
  고정합니다. 연구 트랙은 core wheel·수치·test count에 포함되지 않습니다.
- **역사적 core-only 기준선:** `v0.5.0` tag에는 Sentinel-2/Grad-CAM과 수상 후
  GAN/2.5D 재구성이 없습니다.
- **현재 `main` 검토:** tag 이후 변경이 있을 수 있으므로 commit SHA를 함께 고정합니다.
- **가장 빠른 무네트워크 확인:** 저장소 루트에서 `make proof`를 실행하면 committed
  artifact의 대표 수치, 경계, byte 수와 SHA-256을 검증합니다.

## 5분 안에 보기

1. README의 [60초 기술 증거표](../README.md#60초-기술-증거표)에서 주장마다
   코드·테스트·artifact가 있는지 확인합니다.
2. [core proof flow](assets/core-proof-flow.svg)에서 실제 한 OCR line이 span/hash를
   유지한 채 정규 필드와 CBAM DAG, manifest로 이어지는 과정을 봅니다.
3. `make proof`를 실행하고 모든 줄이 `[PASS]`인지 확인합니다. 구현과 fail-closed
   테스트는 [`proof_summary.py`](../scripts/proof_summary.py)와
   [`test_proof_summary.py`](../tests/test_proof_summary.py)에 있습니다.
4. 무엇을 주장하지 않는지는 [한계](LIMITATIONS.md)에서 먼저 확인합니다.

## 재현과 배포 증거를 검토할 때

| 질문 | 읽을 곳 |
|---|---|
| 전체 data flow와 stage contract는? | [Architecture](ARCHITECTURE.md) |
| 수치가 어떤 입력·함수·테스트·artifact에 묶이는가? | [Claim-to-evidence validation](VALIDATION.md) |
| benchmark 설계와 해석 경계는? | [Methodology](METHODOLOGY.md) |
| 로컬 API와 운영 금지선은? | [Operations](OPERATIONS.md) |
| release가 clean snapshot·wheel·golden artifact를 어떻게 검증하는가? | [`verify_release.sh`](../scripts/verify_release.sh) |

재현 가능한 동일 결과를 인용할 때는 `main`이 아니라 tag를 고정합니다. v0.6 tag에는
연구 소스와 artifact도 있지만 core quickstart가 PyTorch 연구 검증까지 자동 실행하지는
않으므로, 같은 tag tree에서 별도 연구 명령을 사용합니다.

## CBAM·OCR lineage를 검토할 때

추천 순서는 다음과 같습니다.

1. [OCR adapter benchmark](OCR_BENCHMARK.md) — OCR engine이 아니라 TSV/JSON/text
   adapter와 field-error 분류를 어디까지 검증하는지
2. [Architecture의 evidence identity](ARCHITECTURE.md#evidence-identity) — raw line,
   character span, line/document SHA-256, `selected_from` 연결
3. [Methodology](METHODOLOGY.md) — 후보 선택, 정규화, reconciliation 방식
4. [CBAM rule coverage](CBAM_COVERAGE.md) — 15개 선정 규칙 중 partial 8,
   not implemented 7, implemented 0이라는 법정 범위 경계
5. committed [normalized evidence](../artifacts/examples/normalized_evidence.json),
   [11-step CBAM trace](../artifacts/examples/cbam_exposure.json),
   [artifact manifest](../artifacts/examples/artifact_manifest.json) — 문서 설명과 실제
   machine-readable 값 대조

## 산림·XAI를 검토할 때

세 증거 층을 섞지 않는 것이 핵심입니다.

| 증거 층 | 시작점 | 올바른 해석 |
|---|---|---|
| Core 합성 benchmark | [Forest benchmark](FOREST_BENCHMARK.md) | NDVI·CRS·mask·spatial holdout plumbing 회귀셋; 실제 위성 정확도 아님 |
| 공개 위성 연구 | [Forest XAI README](../research/forest_xai/README.md), [data card](../research/forest_xai/DATA_CARD.md), [model card](../research/forest_xai/MODEL_CARD.md) | 공개 Sentinel-2 단일시점 forest-cover CNN과 reference-targeted Grad-CAM |
| 수상 후 개념 재구성 | [Reconstruction card](../research/forest_xai/RECONSTRUCTION_CARD.md) | tiny GAN latent와 합성 높이 2.5D mechanics; 당시 HiGAN·실사·위성→3D 증거 아님 |

대회 당시 자료, 현재 구현, 아직 검증되지 않은 주장의 분리는
[Competition provenance](COMPETITION_PROVENANCE.md)에서 확인합니다.

## Claim audit를 할 때

다음 순서로 읽으면 강한 숫자만 떼어내 잘못 인용하는 일을 줄일 수 있습니다.

1. [Validation matrix](VALIDATION.md)에서 claim의 입력·코드·테스트·artifact·제한을
   한 행에서 대조합니다.
2. [Competition provenance](COMPETITION_PROVENANCE.md)에서 @soccz의 core 기술 개발
   책임과 Team UniHana 3인의 공동 출품·공동 수상 경계를 확인합니다.
3. [Legal blind-style holdout](LEGAL_BLIND_EVAL.md)에서 maintainer-authored 평가와
   외부 blind 검증의 차이, citation·abstention 조건을 확인합니다.
4. [Limitations](LIMITATIONS.md)에서 OCR 정확도, statutory CBAM, 실제 bi-temporal
   change, HiGAN, photorealism, satellite-derived elevation이 미검증임을 확인합니다.
5. 마지막으로 `make proof`를 실행해 문서가 가리키는 committed artifact와 hash가
   현재 tree에서 그대로 일치하는지 확인합니다.
