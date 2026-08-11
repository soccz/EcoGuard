# EcoGuard

**비정형 무역자료를 계산 가능한 값으로 바꾸는 것보다, 그 값이 어디에서 왔고 왜 선택됐는지 증명하는 일이 더 어려웠습니다.** EcoGuard는 이 증명 과정을 코드로 재구성한 3인 팀의 무역금융 교육용 PoC입니다.

2026 하나 청년 금융인재 양성 프로젝트에서 Team UniHana가 개발·발표했습니다. 공개 저장소는 대회 화면을 복제하지 않고, 팀이 중요하게 본 기술을 합성 데이터와 결정론적 테스트로 다시 실행합니다.

```text
7개 합성 문서의 OCR line payload
  → label 추출 + 원문 span/SHA-256
  → 단위·별칭 정규화 + 후보 선택 trace
  → 문서 간 충돌·누락 validation ledger
  → CBAM/EUDR 조문 retrieval + 기권 평가
  → CBAM component 산식 DAG + 가격 민감도
  → NDVI mask + reference 평가 + GeoJSON
  → 사람이 검토하는 JSON/HTML evidence packet
```

> OCR 이미지 인식 모델, 법률 LLM, 법정 CBAM 계산기, 운영 위성 모델을 주장하지 않습니다. 공개 코드가 증명하는 범위와 증명하지 않는 범위를 각 산출물에 함께 기록합니다.

## 한 번에 재현하기

Python 3.11 이상과 표준 라이브러리만 있으면 런타임에 네트워크가 필요하지 않습니다.

```bash
git clone https://github.com/soccz/EcoGuard.git
cd EcoGuard
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
./scripts/reproduce.sh
```

더 강한 배포 검증:

```bash
./scripts/verify_release.sh
```

이 명령은 다음을 한 번에 확인합니다.

1. 전체 단위·회귀·통합 테스트
2. source tree compile
3. wheel build
4. 임시 virtualenv 설치
5. 설치된 wheel을 대상으로 전체 테스트 재실행
6. 저장소 밖의 빈 작업 디렉터리에서 실행
7. `artifacts/examples/`와 생성 결과의 byte-for-byte diff

`make test`, `make reproduce`, `make verify`도 같은 진입점을 제공합니다.

## 현재 공개본이 실제로 검증하는 것

| 단계 | 공개 입력 | 결정론적 출력과 검증 | 경계 |
|---|---|---|---|
| Document ingestion | 7개 문서, 37개 OCR line | 30개 후보, document/page/line/character span, line·document SHA-256 | 이미지 OCR 정확도는 평가하지 않음 |
| Preprocessing | 후보값 + 선택 정책 | 26개 정규 필드, kg→t, 별칭, 문서 권위, 후보 순위, 3개 review issue, 1개 tolerance observation | 운영 정책이나 자동 승인 기준이 아님 |
| Legal retrieval | CBAM/EUDR 조문 메타데이터 8건 | BM25F score trace, instrument/intent gate, structured abstention, 평가 34건 | LLM 생성 답변·법률 자문이 아님 |
| CBAM | 품목별 공정/전구물질 × 직접/간접 구성요소 | 11-step 산식 DAG, leaf provenance, SEE·중량·축별 양방향 대사, 3개 가격 민감도 | 법정 인증서 의무액이 아님 |
| Forest | 6×6 합성 red/NIR + 별도 reference mask | NDVI, confusion matrix, Precision/Recall/F1/IoU, connected region, 36-cell GeoJSON/SVG | 실제 위성 모델 정확도·EUDR 판정이 아님 |
| Evidence packet | 모든 중간 산출물 | JSON/HTML 보고서 + 입력/출력 SHA-256 manifest | 사람이 최종 검토함 |

고정 회귀 fixture의 대표 결과:

```text
Ingestion         7 documents · 37 lines · 30 candidates
Normalization     26 fields · 3 review issues · 1 tolerance observation
Legal eval        16 positive + 8 distractor + 10 hard-negative
                   Recall@3 1.0 · MRR 1.0 · negative abstention 1.0
                   false support 0.0 · instrument leakage 0.0
CBAM inventory    direct 970.50 + indirect 140.86 = 1,111.36 tCO2e
                   process 731.36 + precursor 380.00 = 1,111.36 tCO2e
Forest reference  TP 11 · FP 1 · FN 1 · TN 23
                   F1 0.916667 · IoU 0.846154
```

Legal의 1.0은 의도적으로 고정한 작은 회귀셋이 기대 citation을 회수한다는 뜻입니다. 일반 EU 법률 검색 성능으로 해석하지 않습니다. Forest 지표도 실제 영상 성능이 아니라 metric code가 오탐·미탐을 드러내는지 확인하는 합성 reference 결과입니다.

## 1. OCR 이후의 데이터 전처리

현업 자료는 완성된 표보다 자유로운 메모, 서로 다른 단위, 약칭, 빈칸에 가깝다는 피드백에서 출발했습니다. 합성 fixture에는 다음과 같은 line이 함께 들어 있습니다.

```text
총 출하 중량 : 190,000 kg
NET WT | 190 MT
출하량 = 약 191톤? 최종 인보이스 재확인 필요
배출계수 : 5.85 tCO2/t 정도, 아직 검증 전
검증서 번호 : [blank]
설비 에너지 메모 — 배출계수와 배분근거 미첨부
```

`ingestion.py`는 label 뒤의 후보를 추출하면서 원문 span과 hash를 보존합니다. `preprocessing.py`는 `normalization_policy.json`에 따라 다음 순서로 후보를 선택합니다.

```text
parse 가능 여부 > 문서 권위 > confidence > 안정적인 입력 순서
```

- Invoice의 190t와 Packing list의 190t는 단위가 달라도 같은 값으로 정규화합니다.
- Operator memo의 191t는 낮은 권위라도 삭제하지 않고 material conflict로 남깁니다.
- 5.849263과 5.85는 설정된 `0.001` 허용오차 안의 rounding variance로 구분합니다.
- “배출계수와 배분근거 미첨부”처럼 alias를 우연히 포함한 문장은 parse failure로 남깁니다.
- 비어 있는 검증서 번호는 high-severity review 항목이 됩니다.

선택값뿐 아니라 모든 후보, 선택 순위, 변환 종류, 원문 위치가 `normalized_evidence.json`에 남습니다.

## 2. 조문 retrieval을 어떻게 테스트했는가

법률 자료를 RAG에 넣었을 때 중요한 것은 자연스러운 답변뿐 아니라 관련 조문을 실제로 찾았는지 검증하는 일이라는 현업 의견을 받았습니다. 공개본은 생성 모델 대신 **RAG의 retrieval 단계만 분리한 dependency-free 기준선**을 제공합니다.

- regulation/article/title/keyword/concept/팀 작성 요약을 분리한 field-weighted BM25F
- 한국어 word token과 낮은 가중치의 2·3-character n-gram
- CBAM/EUDR 명시 시 다른 규정 후보를 제외하는 instrument filter
- instrument, legal intent, specific concept가 부족하면 기권
- 점수가 낮거나 순위 차이가 작으면 `abstained` 또는 `review`
- 결과마다 citation, CELEX, Article/paragraph metadata, EUR-Lex URL, corpus entry hash
- BM25 word/character, phrase, article bonus와 field별 score trace

평가셋은 positive 16건, hard-negative 10건, 인접 조문 distractor 8건입니다. `CBAM` 단독, 공동인증서, 일반 지도 표시, 농장 체험처럼 법률 질문으로 뒷받침되지 않는 질의는 기권하는지 함께 테스트합니다.

```bash
ecoguard legal-search \
  "실제 배출량을 쓰려는데 검증서가 없으면 어떤 조항을 확인해야 하나"

ecoguard legal-search "농장 좌표를 지도에 표시하는 방법"
```

두 번째 명령은 관련 단어가 있어도 법률 의도가 부족하므로 citation을 억지로 만들지 않습니다.

## 3. CBAM component trace

기존 발표 수치처럼 이미 완성된 SEE를 곱하는 데서 멈추지 않고, 합성 M5·M12 품목의 구성요소를 다시 합산합니다.

```text
품목 기술 인벤토리 =
  공정 직접배출 + 공정 간접배출
  + 전구물질 직접배출 + 전구물질 간접배출

가격 민감도 =
  기술 인벤토리
  × 시나리오 노출계수
  × max(인증서 가격 − 제3국 탄소가격, 0)
```

각 산식 노드에는 `step_id`, 정확한 피연산자, 단위, 반올림 전 결과가 있습니다. 원문 입력 leaf는 evidence ID를, 중간값은 `derived_from` step ID를, 분석자 민감도 입력은 assumption ID를 가집니다. 다음 두 축이 같은 `1,111.36 tCO2e`로 대사됩니다.

```text
direct 970.50 + indirect 140.86
process 731.36 + precursor 380.00
```

전기 970,000kWh와 LNG 39,300Nm³도 원문 증거로 보존하지만, 배출계수와 공정 배분근거가 없으므로 임의로 CO₂e로 변환하지 않습니다. 결과는 `statutory_calculator: false`이며 공식 CBAM factor, 무상할당 조정, Article 9 적격성, 인증서 의무량을 구현하지 않습니다.

## 4. 산림 변화 평가 코드

대회 당시 산림 화면의 모델 가중치·평가 데이터는 공개 성과로 재현할 수 없었습니다. 따라서 정확도 수치를 옮겨 적지 않고, 공개 가능한 합성 band와 독립 reference mask로 평가 경로를 새로 만들었습니다.

```text
NDVI = (NIR − Red) / (NIR + Red)
loss = NDVI_before ≥ 0.45 and ΔNDVI ≤ −0.25
```

- 원정밀도 `Decimal`로 threshold를 판정하고 직렬화할 때만 반올림
- 전체 6×6 좌표, reflectance 범위, duplicate/missing cell 검증
- 4/8방향 connected components
- zero denominator metric은 임의의 0이나 1 대신 `null`
- TP/FP/FN/TN SVG와 RFC 7946 형태의 36-cell GeoJSON
- CSV 행 순서를 뒤집어도 결과가 동일한 회귀 테스트

## 단계를 따로 실행하기

전체 pipeline과 같은 중간 경계를 CLI로 직접 확인할 수 있습니다.

```bash
ecoguard extract data/synthetic/trade_case_documents.json \
  --output /tmp/extracted.json

ecoguard normalize /tmp/extracted.json \
  --policy data/reference/normalization_policy.json \
  --output /tmp/normalized.json

ecoguard cbam-calculate /tmp/normalized.json \
  --output /tmp/cbam.json

ecoguard forest-analyze data/synthetic/forest_case.json \
  --geojson --output /tmp/forest.geojson
```

## 생성되는 증거 패킷

```text
artifacts/generated/
├── extracted_records.json
├── normalized_evidence.json
├── legal_retrieval_evaluation.json
├── legal_issue_citations.json
├── cbam_exposure.json
├── forest_change.json
├── forest_change.geojson
├── forest_change.svg
├── ecoguard_evidence_report.json
├── ecoguard_evidence_report.html
└── artifact_manifest.json
```

`artifact_manifest.json`에는 8개 입력과 나머지 10개 산출물의 byte 수·SHA-256이 기록됩니다. timestamp와 절대경로는 golden output에 넣지 않습니다.

## 저장소 구조

```text
src/ecoguard/
├── ingestion.py       # document line → field candidate + source span/hash
├── preprocessing.py   # normalization, selection policy, validation ledger
├── legal.py           # BM25F retrieval, abstention and evaluation
├── cbam.py            # component DAG, reconciliation and sensitivity
├── forest.py          # NDVI prediction, reference metrics, GeoJSON/SVG
├── pipeline.py        # deterministic orchestration and manifests
└── report.py          # human-review JSON/HTML packet

data/
├── synthetic/         # trade documents, band grid, reference mask
└── reference/         # normalization policy, legal corpus/eval/source manifest

tests/                 # unit, adversarial, determinism, CLI and integration tests
schemas/               # machine-readable public input contract
artifacts/examples/    # committed byte-stable golden outputs
docs/                  # methodology, architecture, journey and limitations
```

## 구현·시뮬레이션·제안 경계

| 상태 | 범위 |
|---|---|
| Implemented and tested | document-line extraction, preprocessing/lineage, BM25F retrieval/eval, component CBAM sensitivity, synthetic NDVI reference evaluation, reports/manifests |
| Simulated with synthetic inputs | OCR service output, document confidence, 기업·거래·설비, 가격·집약도, band/reference mask |
| Not implemented / proposed | OCR vision model, LLM answer generation, 전체 EU 법령 corpus, Hana 내부 연동, 법정 CBAM 의무 계산, 운영 위성/CNN/XAI, 자동 금융 승인 |

## 프로젝트 과정과 공개 자료

- [개발 과정: 기술보다 증명이 더 어려웠다](docs/DEVELOPMENT_JOURNEY.md)
- [재현 방법론](docs/METHODOLOGY.md)
- [기술 구조](docs/ARCHITECTURE.md)
- [한계와 다음 검증](docs/LIMITATIONS.md)
- [공식 법령 출처와 버전](data/reference/README.md)
- [공개용 4쪽 프로젝트 발췌본](presentation/EcoGuard_Selected_Excerpt.pdf)
- [생성된 evidence report 예시](artifacts/examples/ecoguard_evidence_report.html)

원본 Live Demo 주소와 대회 전체 발표자료는 공개하지 않습니다. 모든 사례 데이터는 합성이며, EcoGuard는 하나은행의 공식 제품이 아니고 법률·통관·금융 자문을 제공하지 않습니다.

## License

코드는 [MIT License](LICENSE)로 배포합니다. EU 법령의 법적 효력은 EUR-Lex 공식 원문을 기준으로 하며 저장소의 한국어 요약은 retrieval 실험용 비공식 메타데이터입니다.
