# 재현 방법론

EcoGuard 공개본의 질문은 하나입니다.

> 비정형 입력에서 얻은 값을 어떻게 규제 검토가 가능한 추적 가능한 증거로 바꿀 것인가?

## 1. 원자료 경계

공개본은 OCR vision model을 포함하지 않습니다. 대신 OCR·표 추출 서비스가 반환할 법한 document/page/line/text/confidence 구조를 입력 contract로 둡니다. 7개 합성 문서의 37개 line에는 단위 변형, 수기 메모, 반올림, 누락, alias 오탐 가능성을 의도적으로 넣었습니다.

Ingestion은 알려진 label의 가장 긴 match를 선택하고 label 뒤 원문을 후보로 남깁니다. 모호한 line도 숨기지 않습니다. 예를 들어 “배출계수와 배분근거 미첨부”는 `배출계수` label을 포함하지만 숫자가 없어 다음 normalization 단계에서 parse failure가 됩니다.

각 후보의 evidence identity는 document/page/line, character span, raw line, line SHA-256, document SHA-256으로 구성됩니다.

## 2. 정규화와 후보 선택

정규화 정책은 코드 밖 JSON에 고정합니다.

```text
valid parse
  → document authority
  → extraction confidence
  → stable order
```

변환 예:

- `190,000 kg` → `190 t`
- `190 MT` → `190 t`
- `7318.15.52` → `73181552`
- `100%` → ratio `1`
- `EUR 87.50 / tCO2e` → `87.5 EUR/tCO2e`

숫자 차이는 field별 Decimal 허용오차와 비교합니다. Shipment mass의 191t는 190t와 material conflict지만, 5.85와 5.849263의 차이 `0.000737`은 configured tolerance `0.001` 안의 observation입니다.

Validation ledger는 모든 required field와 consistency check를 pass/review/fail로 열거합니다. 최종 status만 남기지 않습니다.

## 3. 법률 citation retrieval

코퍼스는 CBAM Regulation Article 6–9와 EUDR Regulation Article 4, 9–11의 8개 article record입니다. Paragraph 값은 metadata이며 paragraph 원문을 별도 chunk로 인덱싱한 것은 아닙니다.

검색기는 다음을 결합합니다.

1. NFKC·casefold query normalization
2. regulation alias, article, title, keyword, concept, summary별 BM25F
3. 한국어 word token과 보조 2·3-character n-gram
4. concept별 capped phrase bonus
5. regulation과 함께 명시된 Article match bonus
6. instrument/legal-intent/specific-concept gate
7. minimum score와 ranking margin

출력은 supported/review/abstained 중 하나이며 기권 이유를 `out_of_domain`, `underspecified`, `ambiguous_instrument`, `low_score` 등으로 구분합니다.

평가 fixture:

| 유형 | 건수 | 목적 |
|---|---:|---|
| positive | 16 | 각 조문의 직접·의역 질문 회수 |
| distractor | 8 | Art 7/8, EUDR Art 10/11 같은 인접 조문 구분 |
| hard-negative | 10 | 규제 단어를 포함한 일반 질문에서 기권 |

Recall@k와 MRR은 citation을 기대하는 positive+distractor 24건을 분모로 계산합니다. 그 밖에 positive coverage, negative abstention, false support, distractor rejection, instrument leakage, trace coverage를 분리해 보고합니다. 현재 전부 통과하는 것은 이 34개 고정 회귀셋에 한정됩니다.

## 4. CBAM 기술 인벤토리와 가격 민감도

M5·M12 각각 네 구성요소를 입력 evidence로 받습니다.

```text
공정 직접 · 공정 간접 · 전구물질 직접 · 전구물질 간접
```

각 구성요소 내재배출은 다음과 같습니다.

```text
component emissions = shipment mass × component intensity
```

품목의 네 component 합계가 제출 SEE와 맞는지, 품목 중량 합계가 shipment mass와 맞는지, 전체 가중 SEE가 sheet의 aggregate SEE와 맞는지 Decimal 원정밀도로 대사합니다.

| 축 | 합성 결과 |
|---|---:|
| Direct | 970.50 tCO2e |
| Indirect | 140.86 tCO2e |
| Process | 731.36 tCO2e |
| Precursor | 380.00 tCO2e |
| Total | 1,111.36 tCO2e |

가격 민감도는 다음 단순 분석식입니다.

```text
exposure = technical inventory
         × scenario exposure factor
         × max(certificate price − third-country price, 0)
```

Published fixture의 €97,244, factor 0.8의 €77,795.20, factor 0.8·third-country price €12.50의 €66,681.60을 같은 trace API로 계산합니다.

`scenario_exposure_factor`는 공식 CBAM factor가 아닙니다. 직접/간접/전구물질의 법정 포함 범위, free-allocation adjustment, Article 9 적격성, 실제 certificate price 산식과 의무량은 구현하지 않습니다. 에너지 사용량만으로 배출량을 역산하지도 않습니다.

## 5. 합성 산림 reference 평가

별도 reference mask를 밴드 입력과 분리합니다. 예측 규칙은 다음과 같습니다.

```text
NDVI = (NIR − Red) / (NIR + Red)
loss = NDVI_before ≥ 0.45 and NDVI_after − NDVI_before ≤ −0.25
```

Reference는 일부러 예측과 완전히 같지 않습니다.

```text
TP=11 · FP=1 · FN=1 · TN=23
Precision=Recall=F1=0.916667 · IoU=0.846154
```

이는 실제 모델 성능이 아니라 binary metric·mask·region·visualization 코드가 오탐과 미탐을 올바르게 보존하는지 보는 fixture입니다. 완벽한 F1=1을 만들지 않은 이유도 여기에 있습니다.

## 6. 증거 패킷과 hash

Pipeline은 각 단계 JSON을 먼저 쓰고, forest GeoJSON/SVG와 사람이 읽는 HTML을 생성합니다. 단계 JSON의 `reproduction` 블록은 해당 단계의 input subset과 전체 입력 SHA-256 manifest를 기록합니다. 최종 `artifact_manifest.json`은 자신을 제외한 10개 출력의 byte 수와 hash를 기록해 GeoJSON/SVG/HTML까지 묶습니다.

결정론 검증은 같은 source tree에서 두 번 실행하는 것에 그치지 않습니다. wheel 설치 후 저장소 바깥에서 packaged resource만으로 실행해 committed golden output과 바이트 단위로 비교합니다.
