# Official reference manifest

이 디렉터리에는 원문 전체가 아니라 검색·평가에 필요한 조문 메타데이터와 한국어 요약만 저장합니다. 법적 효력은 아래 공식 원문을 기준으로 합니다.

메타데이터 확인일은 2026-08-11입니다. CELEX 기본 법령 식별자를 고정했지만
운영에 사용하려면 EUR-Lex의 최신 consolidated text와 후속 시행규칙을 다시
확인해야 합니다.

## CBAM

- Regulation (EU) 2023/956, consolidated 2025-10-20: <https://eur-lex.europa.eu/eli/reg/2023/956/2025-10-20/eng>
- Commission Implementing Regulation (EU) 2025/2547, embedded-emissions calculation methods: <https://eur-lex.europa.eu/eli/reg_impl/2025/2547/oj/eng>
- Commission Implementing Regulation (EU) 2025/2620, free-allocation adjustment: <https://eur-lex.europa.eu/eli/reg_impl/2025/2620/oj/eng>
- European Commission, CBAM definitive regime: <https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-definitive-regime_en>
- European Commission, legislation and guidance: <https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-legislation-and-guidance_en>

선택한 검색 단위는 Article 6(신고), 7(내재배출량 계산), 8(검증), 9(제3국에서 지불한 탄소가격)입니다.

2025/2547과 2025/2620은 공개본이 각각 생산공정 방법론과 공식 free-allocation adjustment를 완전히 구현한다고 주장하지 않도록 경계를 확인하는 데 사용했습니다. 합성 component trace는 산술·provenance 검증용이며 두 시행규칙의 coverage table이 아닙니다.

## EUDR

- Regulation (EU) 2023/1115, consolidated 2025-12-26: <https://eur-lex.europa.eu/eli/reg/2023/1115/2025-12-26/eng>
- European Commission implementation overview: <https://environment.ec.europa.eu/topics/forests/deforestation/regulation-deforestation-free-products_en>

선택한 검색 단위는 Article 4(사업자 의무), 9(정보·지리좌표), 10(위험평가), 11(위험완화)입니다.

## Scope note

- 요약문은 기술 시연용이며 법률 번역문이 아닙니다.
- 법령 버전과 개정법은 `source_manifest.json`에 고정했습니다.
- `normalization_policy.json`은 법령이 아니라 합성 문서 후보 선택을 재현하기 위한 팀 작성 정책입니다.
- CBAM 가격과 기본값은 시점에 따라 바뀔 수 있으므로 코드에 규제값으로 고정하지 않고 사례 입력으로 전달합니다.
- 저장소의 계산은 노출도 시나리오이며 공식 신고나 인증서 의무액 산정을 대체하지 않습니다.
