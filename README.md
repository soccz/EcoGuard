# EcoGuard

EcoGuard는 기업의 비정형 수출 데이터를 규제 검토가 가능한 구조로 정리하고, EU 법령 근거와 CBAM 비용 시나리오, 산림 변화 증거를 하나의 검토 보고서로 연결하는 **3인 팀의 무역금융 PoC**입니다.

2026 하나 청년 금융인재 양성 프로젝트에서 Team UniHana가 개발·발표했습니다.

> 이 저장소는 대회용 제품 화면을 그대로 공개하는 곳이 아닙니다. 발표 당시 가장 증명하기 어려웠던 기술을, 합성 데이터와 결정론적 테스트로 다시 실행할 수 있게 정리한 기술 저장소입니다.

## 우리가 증명하려던 것

현업의 원천자료는 완성된 보고서가 아니라 메모, 제각각인 표, 누락된 값, 서로 맞지 않는 단위에 가깝습니다. EcoGuard가 중요하게 본 지점은 OCR 모델 자체보다 **OCR 이후의 데이터 전처리**였습니다.

```text
비정형 OCR 출력·메모
  → 필드와 단위 정규화
  → 원본 위치(provenance) 보존
  → 문서 간 불일치 탐지
  → EU 법령의 조문(article) 단위 근거 검색
  → CBAM 노출도 계산
  → 산림 변화 증거 요약
  → 사람이 검토하는 보고서
```

기술을 구현하는 것보다 “왜 이 결과를 믿을 수 있는가”를 증명하는 일이 더 어려웠습니다. 그래서 공개본은 점수나 화려한 화면보다 입력, 중간 산출물, 법률 근거, 테스트를 남기는 데 초점을 둡니다.

## 재현 범위

| 모듈 | 이 저장소에서 재현되는 것 | 경계 |
|---|---|---|
| Data preprocessing | 단위 변환, 별칭 매핑, 후보값 선택, 출처 추적, 불일치 플래그 | OCR 엔진 자체는 포함하지 않음 |
| Legal retrieval | CBAM·EUDR의 조문 메타데이터 검색과 citation hit 평가 | 법률 자문이나 생성형 답변이 아님 |
| CBAM exposure | 품목별 중량×집약도 검산, 실측·기본값 비교와 가격 민감도 | 공식 신고액·법적 의무액 계산기가 아님 |
| Forest change | 별도 합성 red/NIR fixture의 NDVI·손실 영역·면적 | 거래 사례와 결합된 위성 증빙이나 EUDR 판정이 아님 |
| Evidence report | 거래 사례와 독립 기술 기준선을 구분해 HTML/JSON으로 통합 | 자동 승인·거절 시스템이 아님 |

모든 사례 기업명, 식별자, 좌표, 거래 문서와 계산 수치는 합성 시연 데이터입니다. 법령 메타데이터는 확인일과 통합본 버전을 고정한 팀 작성 검색 요약입니다. EcoGuard는 하나은행의 공식 제품이 아니며, 법률·통관·금융 자문을 제공하지 않습니다.

## 빠른 재현

Python 3.11 이상만 필요하며 런타임 외부 패키지는 사용하지 않습니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m ecoguard reproduce --output artifacts/generated
```

또는:

```bash
./scripts/reproduce.sh
```

생성 결과:

```text
artifacts/generated/
├── normalized_evidence.json
├── legal_retrieval_evaluation.json
├── legal_issue_citations.json
├── cbam_exposure.json
├── forest_change.json
├── forest_change.svg
├── ecoguard_evidence_report.json
└── ecoguard_evidence_report.html
```

## 기술 구조

```text
data/synthetic/ocr_records.json
        │
        ▼
src/ecoguard/preprocessing.py
        │ normalized fields + provenance + issues
        ├──────────────┐
        ▼              ▼
legal.py            cbam.py
조문 검색             비용 노출도
        │              │
        └──────┬───────┘
               │
forest.py ─────┤
독립 NDVI 기준선│
               ▼
           report.py
        검토용 HTML / JSON
```

## 저장소 안내

| 경로 | 내용 |
|---|---|
| `src/ecoguard/` | 재현 가능한 핵심 코드 |
| `data/synthetic/` | 공개 가능한 합성 입력 |
| `data/reference/` | 팀 작성 검색 메타데이터, 버전 manifest와 공식 원문 링크 |
| `tests/` | 단위·통합·citation 회수 테스트 |
| `docs/` | 방법론, 발전 과정, 한계 |
| `artifacts/examples/` | 재현 명령의 기준 출력 |

대회 당시 정적 시연 화면과 전체 발표자료는 새 공개 저장소와 공개 이력에서 제외했습니다.

## 핵심 설계 원칙

1. **원본을 잃지 않는다.** 정규화된 값에는 문서·페이지·필드 위치를 함께 남깁니다.
2. **계산과 가정을 분리한다.** CBAM 가격·배출집약도·적용계수는 입력값이며 결과에 다시 기록됩니다.
3. **법률 답변보다 검색 근거를 먼저 평가한다.** 기대 조문이 상위 검색 결과에 들어오는지 자동 테스트합니다.
4. **모델 수치를 과장하지 않는다.** 공개 데이터로 재현할 수 없는 정확도는 성과로 사용하지 않습니다.
5. **사람이 최종 판단한다.** 출력은 검토 신호와 보완 항목이지 자동 승인 도장이 아닙니다.

## 문서

- [방법론](docs/METHODOLOGY.md)
- [개발 과정](docs/DEVELOPMENT_JOURNEY.md)
- [기술 구조](docs/ARCHITECTURE.md)
- [한계와 다음 검증](docs/LIMITATIONS.md)
- [공식 법령 출처](data/reference/README.md)

## 공개 자료

전체 발표자료와 실제 시연 주소는 공개하지 않습니다. 포트폴리오에는 개인정보를 제거한 4쪽 요약본과 정적 화면만 제공합니다.

- [공개용 4쪽 프로젝트 발췌본](presentation/EcoGuard_Selected_Excerpt.pdf)
- [재현된 증거 보고서 예시](artifacts/examples/ecoguard_evidence_report.html)

## 라이선스

코드는 [MIT License](LICENSE)로 배포합니다. EU 법령의 법적 효력은 EUR-Lex에 게시된 공식 원문을 기준으로 하며, 저장소의 요약문은 검색 실험용 메타데이터입니다.
