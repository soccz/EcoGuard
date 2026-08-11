# 주장-증거 검증표

이 표는 README의 핵심 정량·기술 주장을 공개 입력, 실행 코드, 정확한 회귀 테스트와 committed artifact에 연결합니다. 수치가 맞는지만 보는 golden replay에 더해, 의미 있는 입력 변경에는 결과가 변하고 순서·표기만 다른 동등 입력에는 결과가 유지되는지도 구분합니다.

## 핵심 주장과 직접 증거

| 공개 주장 | 입력 | 실행 코드 | 직접 검증 테스트 | 확인할 산출물·근거 |
|---|---|---|---|---|
| Team UniHana 대상(상장 표기: 금융감독원상), 상장·상금 1천만 원 | 팀 보관 수상 기록 + 외부 공식 보도 | 계산 코드 대상 아님 | 수동 source cross-check | 공개 보고서의 개인정보 제거 수상 사진; [연합뉴스](https://www.yna.co.kr/view/AKR20260724041100002), [하나금융 제공 보도자료 게재본](https://www.hankyung.com/article/202607243395P) |
| 13팀·54명, 약 4개월 과정과 약 3개월 1:1 멘토링 | 외부 공식 보도 | 계산 코드 대상 아님 | 수동 source cross-check | [하나금융 제공 보도자료 게재본](https://www.hankyung.com/article/202607243395P); 수상은 아래 합성 baseline의 정확도 증명이 아님 |
| 7개 문서·37 line → 30 candidate | `data/synthetic/trade_case_documents.json` | `ecoguard.ingestion.extract_document_bundle` | `test_ingestion.DocumentIngestionTests.test_document_bundle_becomes_auditable_candidate_records` | `artifacts/examples/extracted_records.json`의 `summary` |
| 26 field·3 issue·1 observation | 위 document bundle + `data/reference/normalization_policy.json` | `ecoguard.preprocessing.normalize_records` | `test_preprocessing.PreprocessingTests.test_fixture_claim_counts_are_exact_and_auditable` | `artifacts/examples/normalized_evidence.json`의 `summary` |
| kg/MT, CN, 비율, 탄소가격 단위 정규화 | 같은 입력 | `ecoguard.preprocessing._normalize` 계열 | `test_preprocessing.PreprocessingTests.test_units_components_and_aliases_are_normalized` | `artifacts/examples/normalized_evidence.json`의 `fields` |
| OCR 메모의 모호한 숫자·부호·범위·배율·복합단위를 조용히 exact 값으로 만들지 않음 | leading decimal, 지수표기, Unicode minus/slash, 부등식, `negative/음수`, `thousand/천`, rate 단위 공격 입력 | `_canonical_numeric_view`, `_number`, `_single_recognized_token` | `test_preprocessing.PreprocessingTests.test_unsupported_numeric_and_unit_tokens_are_not_partially_matched`; `test_cbam.CbamTests.test_raw_ambiguous_values_cannot_reach_cbam_calculation` | parse failure 후보와 review issue로 남고 CBAM 필수 입력 경계에서 중단 |
| 문장 중간 substring·한 line 복수 label을 field로 추측하지 않음 | `CABINET WT`, `미출하량`, `M5 순중량 및 출하량` | `ecoguard.ingestion._match_alias` | `test_ingestion.DocumentIngestionTests.test_ascii_aliases_require_word_boundaries`; `test_ingestion.DocumentIngestionTests.test_korean_aliases_require_leading_label_boundaries`; `test_ingestion.DocumentIngestionTests.test_multiple_field_aliases_on_one_line_are_quarantined` | `unmatched_lines`에 이유와 원문을 보존 |
| 원문 span·line/document hash와 선택 provenance | extraction 결과 전체 line | `extract_document_bundle`, `normalize_records` | `test_preprocessing.PreprocessingTests.test_selection_trace_keeps_span_hash_and_document_authority`; `test_preprocessing.PreprocessingTests.test_tampered_adapter_provenance_cannot_enter_calculation_fields` | `extracted_records.json`, `normalized_evidence.json` |
| Legal corpus 8건·eval 34건(16 positive, 8 distractor, 10 negative), Recall@3/MRR/negative abstention 1.0 | `data/reference/legal_corpus.json`, `data/reference/legal_eval.json` | `ecoguard.legal.LegalRetriever`, `evaluate` | `test_legal.LegalRetrievalV2Tests.test_corpus_keeps_eight_article_records_and_paragraph_metadata`; `test_legal.LegalRetrievalV2Tests.test_evaluation_reports_retrieval_and_selective_metrics` | `artifacts/examples/legal_retrieval_evaluation.json` |
| Legal corpus 2개 기본법과 방법론 경계 2개 시행법의 CELEX·ELI·확인일이 source manifest와 일치 | `legal_corpus.json`, `source_manifest.json` | `ecoguard.legal.validate_source_manifest` | `test_legal.LegalRetrievalV2Tests.test_corpus_is_bound_to_pinned_source_manifest`; `test_pipeline.PipelineTests.test_reproduction_rejects_legal_manifest_corpus_mismatch` | 두 legal artifact의 `source_binding`에 corpus/methodology 역할을 분리; 누락·불일치 시 artifact 생성 전 실패 |
| OOD·미지원 Article은 citation을 만들지 않고 기권 | 같은 corpus와 hard-negative query | `LegalRetriever.retrieve` | `test_legal.LegalRetrievalV2Tests.test_hard_negatives_abstain_with_structured_reason`; `test_legal.LegalRetrievalV2Tests.test_unknown_explicit_article_abstains_instead_of_substituting` | evaluation의 `decision`, `reason_code`, `results` |
| Legal 평가 label 자체가 중복·미등록·상충하지 않음 | `legal_eval.json` | `ecoguard.legal._validate_evaluation_cases` | `test_legal.LegalRetrievalV2Tests.test_evaluation_rejects_duplicate_unknown_and_self_contradictory_labels` | 유효하지 않은 fixture는 artifact 생성 전 실패 |
| CBAM 기술 인벤토리 11-step DAG와 총 1,111.36 tCO2e | normalized evidence | `ecoguard.cbam.calculate_exposure` | `test_cbam.CbamTests.test_calculation_trace_is_complete_topological_and_arithmetic`; `test_cbam.CbamTests.test_v3_golden_inventory_and_legacy_comparison` | `artifacts/examples/cbam_exposure.json` |
| direct 970.50 + indirect 140.86, process 731.36 + precursor 380.00 | 품목별 4개 component intensity | `calculate_exposure` axis reconciliation | `test_cbam.CbamTests.test_direct_indirect_and_process_precursor_axes_reconcile` | `cbam_exposure.json`의 `technical_inventory.component_axes` |
| 3개 가격 민감도 €97,244.00 / €77,795.20 / €66,681.60 | 가격·factor evidence와 analyst assumption | `ecoguard.cbam._price_scenario` | `test_cbam.CbamTests.test_three_price_sensitivity_scenarios_reproduce_exactly` | `cbam_exposure.json`의 `sensitivity_scenarios` |
| Default-value 배출도 mass와 default intensity에서 추적 가능 | normalized shipment mass/default intensity | `calculate_exposure`의 `default_value_fixture.embedded_emissions` | `test_cbam.CbamTests.test_default_value_trace_derives_emissions_from_evidence` | `cbam_exposure.json`의 `default_value_scenario.pricing_trace` |
| CBAM 계산 전에 value·unit·CN·모든 후보의 raw normalization·source span·line/document hash·confidence·정책 권위·선택 순위·후보 완전성을 재검증 | retained 37 source lines, document manifest, full policy, normalized typed field | `validate_normalized_evidence`, `_validate_candidate_source`, `_validated_ranked_candidates`, `_expected_candidate_index`, `_decimal`, `_text`, `_source` | `test_cbam.CbamTests.test_units_cn_and_evidence_hash_are_validated_at_calculation_boundary`; `test_cbam.CbamTests.test_calculation_revalidates_candidate_against_retained_source_lines`; `test_cbam.CbamTests.test_calculation_rejects_hidden_candidate_and_manifest_count_tampering` | 미선택 상위 후보를 parse failure로 위조하거나 conflict 후보를 삭제하거나 authority/confidence/rank를 바꿔도 계산 전에 `ValueError` |
| Forest 6×6에서 TP=11·FP=1·FN=1·TN=23, F1=0.916667, IoU=0.846154 | `forest_case.json`, `forest_pixels.csv`, `forest_reference_mask.csv` | `ecoguard.forest.analyze_forest_case`, `evaluate_binary_mask` | `test_forest.ForestV2Tests.test_manifest_case_has_exact_prediction_reference_and_metrics` | `forest_change.json`, `forest_change.geojson`, `forest_change.svg` |
| 36-cell RFC 7946 형태 GeoJSON과 TP/FP/FN/TN SVG | 같은 forest result | `build_regions_geojson`, `render_change_svg` | `test_forest.ForestV2Tests.test_geojson_is_complete_stable_and_rfc7946_shaped`; `test_forest.ForestV2Tests.test_svg_is_valid_xml_with_all_confusion_classes` | `forest_change.geojson`, `forest_change.svg` |
| Manifest 8 input·10 output의 byte/hash가 실제 파일과 일치 | 모든 공개 input + artifact | `ecoguard.pipeline.reproduce` | `test_contracts.PublicContractTests.test_manifest_hashes_match_every_committed_input_and_output_byte` | `artifacts/examples/artifact_manifest.json` |
| 공개 fixture 4종은 Draft 2020-12 JSON Schema와 runtime의 핵심 contract를 함께 만족 | trade bundle, normalization policy, forest case, artifact manifest | `schemas/*.schema.json` + 각 runtime loader | `test_contracts.PublicContractTests.test_public_fixtures_validate_against_draft_2020_12_schemas`; `test_contracts.PublicContractTests.test_forest_schema_rejects_invalid_runtime_contract_examples` | const·required·additionalProperties·decimal string·nested shape 오류를 거절 |
| runtime은 network I/O 없이 재현 가능 | packaged/public fixture | `ecoguard.pipeline.reproduce` | `test_pipeline.PipelineTests.test_reproduction_performs_no_network_io` | 임시 디렉터리의 11개 public artifact |
| 설치 wheel을 저장소 밖에서 실행해 golden과 byte-identical | wheel에 포함된 resource 8개 | `scripts/verify_release.sh` | `test_resources.PackagedResourceTests.test_package_contains_only_declared_public_resources`; script가 clean source snapshot build, source/installed-wheel tests와 `diff -ru`를 모두 실행 | stale ignored `build/` 파일의 wheel 재유입 차단; `artifacts/examples/` 전체; build dependency 최초 확보까지 offline이라는 주장은 아님 |

## 입력 변화와 동등 변형

| 성질 | 변형 | 검증 테스트 | 기대 결과 |
|---|---|---|---|
| Mutation sensitivity: trade | 인증서 가격 한 line을 87.50→88.00으로 변경 | `test_pipeline.PipelineTests.test_one_source_line_mutation_changes_lineage_and_cbam_result` | line/input hash와 normalized price가 바뀌고 실제-data exposure가 €97,799.68로 변함; 다른 7개 input hash는 유지 |
| Mutation sensitivity: forest | 한 cell의 after red/NIR를 바꿔 loss flag 추가 | `test_forest.ForestV2Tests.test_one_band_mutation_changes_mask_metrics_regions_and_visuals` | FP 1→2, TN 23→22, F1 0.916667→0.88, region·GeoJSON·SVG 변화 |
| Order invariance: document | document/page/line 순서 반전 | `test_ingestion.DocumentIngestionTests.test_input_order_does_not_change_extraction`; `test_cbam.CbamTests.test_document_input_order_does_not_change_cbam_result` | canonical extraction과 CBAM 결과 동일 |
| Order/Unicode invariance: legal | corpus 순서 반전, full-width Unicode query | `test_legal.LegalRetrievalV2Tests.test_corpus_order_and_unicode_formatting_do_not_change_ranking` | corpus hash와 citation ranking 동일 |
| Order/notation invariance: forest | CSV 행 순서 반전, `0.18`→`0.1800` | `test_forest.ForestV2Tests.test_input_row_order_does_not_change_any_output`; `test_forest.ForestV2Tests.test_equivalent_decimal_notation_does_not_change_outputs` | JSON result·GeoJSON·SVG 의미 결과 동일 |

## 실행

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
./scripts/verify_release.sh
```

두 번째 명령이 완료돼야 source tree뿐 아니라 fresh wheel, 저장소 밖 runtime과 committed golden까지 함께 검증한 것입니다.
