# CBAM 규정 coverage 경계

이 문서는 EcoGuard의 계산 코드를 공식 CBAM 원문과 대조한 **선택 요구사항 매핑**입니다. 법률 의견, 완전한 규정 목록, 공식 신고 계산기, 인증서 의무량 또는 지급액 산정이 아닙니다. 세부 머신 판독 원본은 [`data/reference/cbam_rule_coverage.json`](../data/reference/cbam_rule_coverage.json)입니다.

확인일은 **2026-08-12**입니다. 운영에 적용하기 전에는 EUR-Lex의 최신 consolidated text, 후속 delegated/implementing act, 집행기관 지침을 다시 확인하고 CBAM·관세·배출량 검증 전문가의 검토를 받아야 합니다.

## 결론

선택한 15개 요구사항 중 법정 경로 전체를 구현했다고 표시한 항목은 없습니다.

| 상태 | 개수 | 의미 |
|---|---:|---|
| `implemented` | 0 | 선택한 법정 요구사항을 이 코드만으로 충족한다고 평가한 항목 |
| `partial` | 8 | 추적 가능한 기술 하위 단계 또는 산술적 유사성은 있지만 법적 조건·입력·절차가 빠진 항목 |
| `not_implemented` | 7 | 법정 판정 또는 절차를 구현하지 않은 항목 |

이 구분에서 source hash, 단위 검증, Decimal 계산, reconciliation은 구현된 기술 통제입니다. 그러나 그 통제를 Annex V 장부, Article 8 검증 또는 법정 인증서 계산과 동일시하지 않습니다.

## 고정한 공식 원문

| 문서 | CELEX | 사용 범위 |
|---|---|---|
| [Regulation (EU) 2023/956, consolidated 2025-10-20](https://eur-lex.europa.eu/eli/reg/2023/956/2025-10-20/eng) | `02023R0956-20251020` (`32023R0956`) | Articles 2, 2a, 6–9, 21–22, 31; Annexes I–VII |
| [Regulation (EU) 2025/2083](https://eur-lex.europa.eu/eli/reg/2025/2083/oj/eng) | `32025R2083` | 2025-10-20 consolidated version의 개정 근거 |
| [Implementing Regulation (EU) 2025/2547](https://eur-lex.europa.eu/eli/reg_impl/2025/2547/oj/eng) | `32025R2547` | 실제값·기본값, system boundary, functional unit, precursor 방법 |
| [Implementing Regulation (EU) 2025/2621](https://eur-lex.europa.eu/eli/reg_impl/2025/2621/oj/eng) | `32025R2621` | 공식 기본값·mark-up·생산경로 표와 적용 조건 |
| [Implementing Regulation (EU) 2025/2546](https://eur-lex.europa.eu/eli/reg_impl/2025/2546/oj/eng) | `32025R2546` | 검증, site visit, materiality, verification report |
| [Implementing Regulation (EU) 2025/2548](https://eur-lex.europa.eu/eli/reg_impl/2025/2548/oj/eng) | `32025R2548` | CBAM 인증서 가격 계산·공개 |
| [Implementing Regulation (EU) 2025/2620](https://eur-lex.europa.eu/eli/reg_impl/2025/2620/oj/eng) | `32025R2620` | free-allocation adjustment |

Consolidated text는 EUR-Lex가 제공하는 문서화 도구이며, 그 페이지 자체도 Official Journal에 실린 원문이 authentic version이라고 밝힙니다. 따라서 JSON은 consolidated CELEX와 개정 Official Journal act를 함께 고정했습니다.

## 요구사항별 평가

| ID | 선택 요구사항 | 상태 | 현재 코드가 하는 일 | 주요 미구현 범위 |
|---|---|---|---|---|
| `CBAM-SCOPE-001` | 물품·원산지·지역·면제 | `not_implemented` | CN 코드가 8자리 숫자인지만 확인 | Annex I/III lookup, 원산지, 관세절차, 면제 |
| `CBAM-DEMINIMIS-002` | 연간 단일 질량 기준 | `not_implemented` | 한 합성 shipment의 질량만 처리 | importer·연도별 누적, Annex VII 기준, 초과 시 처리 |
| `CBAM-DECLARATION-003` | 신고 수량·배출량·인증서 항목 | `partial` | 두 item 질량과 기술 배출량을 합산 | 연간 신고 grouping, registry, 법정 인증서 수 |
| `CBAM-CN-MAPPING-004` | CN과 goods category/system boundary 매핑 | `partial` | 문자열 형식과 provenance 유지 | 공식 CN lookup, GHG/category/functional unit |
| `CBAM-ACTUAL-EMISSIONS-005` | 실제 내재배출량 | `partial` | 미리 주어진 component intensity × 수입 질량 | 설비 activity data, attributed emissions, sector method |
| `CBAM-PRECURSOR-006` | 복합재·전구물질 | `partial` | 합성 precursor component를 별도 합산 | 적격성, 투입량, reporting period, 설비별 가중평균 |
| `CBAM-INDIRECT-007` | 간접배출 포함 조건 | `partial` | 주어진 indirect component를 기술 인벤토리에 포함 | Annex II 판정, 전력 factor, actual-electricity 증빙 |
| `CBAM-DEFAULTS-008` | 공식 기본값 | `partial` | 합성 default intensity × shipment mass | Commission 값·버전·국가·품목·mark-up 선택 |
| `CBAM-RECORDS-009` | 계산 장부와 보존 | `partial` | 원문 위치·hash·계산 step을 보존 | Annex V 완전성, 공식 report, 4년 보존·registry |
| `CBAM-VERIFICATION-010` | 공인 검증 | `not_implemented` | 로컬 provenance만 검증 | accreditation, assurance, site visit, materiality, report |
| `CBAM-THIRD-COUNTRY-PRICE-011` | 제3국 탄소가격 감축 | `partial` | 두 단가의 차이를 0 아래로 내리지 않는 민감도 산술 | 적격성, 환급·보상, 납부 증빙, 독립 확인, 환율, 인증서 수 변환 |
| `CBAM-CERTIFICATE-PRICE-012` | 공식 인증서 가격 | `not_implemented` | 합성 단가를 입력으로 받음 | Commission 공개 가격, 2026 분기·이후 주간 기준, 거래량 가중 |
| `CBAM-FREE-ALLOCATION-013` | 무상할당 조정 | `not_implemented` | 없음 | 2025/2620 실제값·기본값·전구물질 조정 |
| `CBAM-CERTIFICATE-COUNT-014` | 제출할 인증서 수 | `not_implemented` | `statutory_calculator: false` | 검증 배출량, Article 9 감축, Article 31 조정 |
| `CBAM-SURRENDER-015` | registry 제출·분기 잔고 | `not_implemented` | offline JSON만 생성 | 계정·구매·보유·제출·기한·분기 reconciliation |

## 산식이 닮은 부분과 다른 부분

EcoGuard의 공개 산식은 다음 기술 시나리오입니다.

```text
technical inventory
= Σ(item mass × supplied component intensity)

educational exposure
= technical inventory
  × analyst scenario factor
  × max(supplied certificate price − supplied third-country price, 0)
```

공식 경로에는 먼저 goods·origin·exemption 판정, production system boundary, 실제값 또는 기본값 적격성, 전구물질·간접배출 처리, accredited verification이 필요합니다. 그 뒤 Article 9 감축과 Article 31 free-allocation adjustment를 반영해 인증서 수를 정하고, Article 21과 Implementing Regulation 2025/2548의 기간별 공식 가격 및 Article 22의 registry 절차를 적용합니다.

따라서 EcoGuard의 `scenario_exposure_factor`는 phase-in 또는 free-allocation factor가 아니며, `certificate_price_eur_per_tco2e`도 Commission 공식 가격이라고 보장하지 않습니다. 제3국 가격 단순 차감도 Article 9 적격성이나 인증서 감축 산식의 구현이 아닙니다.

## 전문가 검토가 남은 지점

모든 15개 행은 `expert_review.required: true`입니다. 특히 다음 검토 없이 상태를 `implemented`로 올리면 안 됩니다.

- 관세 전문가의 CN 코드·원산지·관세절차·면제 판정
- CBAM 전문가의 적용시점, 신고 grouping, 기본값과 후속 시행규칙 검토
- 설비 배출량 전문가의 monitoring plan, system boundary, activity level, precursor allocation 검토
- accredited verifier의 verification scope, materiality, report 검토
- Article 9의 실제 납부·환급·보상·독립 확인·환율·인증서 변환 검토
- Article 31 및 Implementing Regulation 2025/2620의 free-allocation adjustment 검토
- Article 21·22의 공식 가격, registry account, 구매·잔고·제출 절차 검토

## 자동 검증

외부 dependency 없이 source binding, 상태 집계, 완전성 주장, 전문가 검토 플래그를 확인합니다.

```bash
PYTHONPATH=src python -m ecoguard.regulatory
PYTHONPATH=src python -m unittest discover -s tests -p 'test_regulatory_coverage.py' -v
```

검증기는 비공식 URL, stale count, `complete_statutory_coverage: true`, `legal_advice: true`, 전문가 검토 제거를 거부합니다. 이 검증은 JSON의 정합성을 확인할 뿐 규정 해석의 정확성을 인증하지 않습니다.
