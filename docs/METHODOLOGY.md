# 재현 방법론

EcoGuard 공개본의 질문은 하나입니다.

> 비정형 입력에서 얻은 값을 어떻게 규제 검토가 가능한 추적 가능한 증거로 바꿀 것인가?

## 1. 원자료 경계

공개본은 OCR vision model을 포함하지 않습니다. 대신 OCR·표 추출 서비스가 반환할 법한 document/page/line/text/confidence 구조를 입력 contract로 둡니다. 7개 합성 문서의 37개 line에는 단위 변형, 수기 메모, 반올림, 누락, alias 오탐 가능성을 의도적으로 넣었습니다.

Ingestion은 line 앞에서 시작하는 알려진 label의 가장 긴 match를 선택하고 label 뒤 원문을 후보로 남깁니다. 문장 중간의 부분 문자열과 서로 독립된 label이 둘 이상인 line은 추측하지 않고 unmatched evidence로 격리합니다. 예를 들어 “배출계수 : 배분근거 미첨부”는 label은 분명하지만 숫자가 없어 다음 normalization 단계에서 parse failure가 됩니다.

각 후보의 evidence identity는 document/page/line, character span, raw line, line SHA-256, document SHA-256으로 구성됩니다.
Normalization 경계에서는 raw line에서 line hash를 다시 계산하고, 모든 matched/unmatched line으로 document hash를 재구성해 manifest와 대조합니다. confidence가 유한한 0–1 범위를 벗어나거나 provenance가 깨진 후보는 낮은 점수로 선택하는 대신 계산 불가능한 후보로 격리합니다.

v0.3부터 document hash에는 page·line·confidence·text가 함께 들어가고, normalized artifact에는 전체 선택 정책과 retained line confidence가 포함됩니다. 이전 공개 artifact와 호환된다고 오해하지 않도록 extraction output은 2.0.0, normalized evidence와 evidence packet은 3.0 계열로 올렸습니다. 입력 document bundle contract(`ocr-document-bundle/1.0`)와 Forest fixture 2.0은 변경하지 않았습니다.

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

숫자가 필요한 한 필드에 `190/191 t`처럼 둘 이상의 숫자 후보가 있으면 첫 숫자를 임의 선택하지 않고 parse failure로 보냅니다. 반대로 `190,000 kg`와 `190 MT`처럼 단위만 다른 동등 표기는 같은 정규값으로 수렴합니다.

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
명시한 instrument의 Article 번호가 작은 공개 코퍼스에 없으면 가장 비슷한 다른 조문을 대신 반환하지 않고 `article_not_in_corpus`로 기권합니다. 평가를 실행하기 전에는 case ID 중복, 미등록 expected/forbidden ID, 서로 겹치는 label과 negative case의 잘못된 기대 citation도 거부합니다.

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
계산 경계는 37개 retained OCR line에서 line/document hash를 다시 만들고, 선택 provenance가 후보·원문 span·문서 manifest와 같은지 확인합니다. 이어 선택값을 raw value에서 다시 정규화해 unit과 8자리 CN code까지 대조합니다. 이는 전자서명은 아니며, 공개 fixture 내부의 변조·불일치를 계산 전에 드러내는 무결성 경계입니다. Default-value 비교도 `shipment mass × default intensity`를 별도 trace node로 남겨 실제 component sum에서 파생된 것처럼 표시하지 않습니다.

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
한 band cell을 바꾸면 prediction, confusion matrix, connected regions, GeoJSON과 SVG가 함께 변하는 mutation test를 둡니다. CSV 행 순서나 `0.18`/`0.1800` 같은 동등 소수 표기만 바꾸면 결과는 동일해야 합니다.

## 6. 증거 패킷과 hash

Pipeline은 각 단계 JSON을 먼저 쓰고, forest GeoJSON/SVG와 사람이 읽는 HTML을 생성합니다. 단계 JSON의 `reproduction` 블록은 해당 단계의 input subset과 전체 입력 SHA-256 manifest를 기록합니다. 최종 `artifact_manifest.json`은 자신을 제외한 10개 출력의 byte 수와 hash를 기록해 GeoJSON/SVG/HTML까지 묶습니다.

결정론 검증은 같은 source tree에서 두 번 실행하는 것에 그치지 않습니다. wheel 설치 후 저장소 바깥에서 packaged resource만으로 실행해 committed golden output과 바이트 단위로 비교합니다.
Manifest의 선언값은 테스트에서 각 공개 입력·산출물의 실제 byte 수와 SHA-256을 다시 계산해 대조합니다. 재현 pipeline이 네트워크 socket을 만들지 않는 테스트도 별도로 실행합니다. 이는 runtime offline 성질을 검증하며, build dependency를 처음 받는 wheel build까지 오프라인이라고 주장하지 않습니다.
