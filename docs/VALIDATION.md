# 주장-증거 검증표

이 문서는 README의 핵심 정량·기술 주장을 공개 입력, 실행 코드,
회귀 테스트와 committed artifact에 연결합니다. 수치가 맞는지만 보는 golden
replay에 더해, 의미 있는 입력 변경에는 결과가 변하고 순서·표기만 다른
동등 입력에는 결과가 유지되는지도 구분합니다.

Core v0.5는 dependency-free wheel·`tests/`의 **174개 test method**로 검증합니다.
선택형 `research/forest_xai`는 PyTorch 전용 환경·별도 연구 테스트·artifact를
사용합니다. 아래 두 검증표의 수치와 성공 기준은 합산하지 않습니다.

## Core v0.5 핵심 주장과 직접 증거

| 공개 주장 | 입력 | 실행 코드 | 직접 검증 테스트 | 확인할 산출물·근거 |
|---|---|---|---|---|
| Team UniHana 대상(상장 표기: 금융감독원상), 상장·상금 1천만 원 | 팀 보관 수상 기록 + 외부 공식 보도 | 계산 코드 대상 아님 | 수동 source cross-check | [상세 보고서의 개인정보 제거 수상 사진](https://soccz.github.io/projects/ecoguard/#award); [연합뉴스](https://www.yna.co.kr/view/AKR20260724041100002), [하나금융 제공 보도자료 게재본](https://www.hankyung.com/article/202607243395P) |
| 13팀·54명, 약 4개월 과정과 약 3개월 1:1 멘토링 | 외부 공식 보도 | 계산 코드 대상 아님 | 수동 source cross-check | [하나금융 제공 보도자료 게재본](https://www.hankyung.com/article/202607243395P); 수상은 아래 합성 baseline의 정확도 증명이 아님 |
| 7개 문서·37 line → 30 candidate | `data/synthetic/trade_case_documents.json` | `ecoguard.ingestion.extract_document_bundle` | `test_ingestion.DocumentIngestionTests.test_document_bundle_becomes_auditable_candidate_records` | `artifacts/examples/extracted_records.json`의 `summary` |
| Tesseract TSV·generic JSON·pdftotext 출력이 공통 ingestion 계약으로 변환되고 field 오류가 분리됨 | `data/benchmarks/ocr/*` + adapter 공격 입력 | `ecoguard.ocr_adapter` | `test_ocr_adapter.OcrAdapterTests.test_synthetic_fixture_exercises_every_error_bucket`; `test_ocr_adapter.OcrAdapterTests.test_tesseract_words_become_stable_lines_with_mean_confidence` | `artifacts/benchmarks/ocr_field_benchmark.json`: TP/FP/FN 2/2/2, mismatch/missing/spurious 각 1; 합성 오류 fixture이며 OCR 정확도 주장이 아님 |
| 26 field·3 issue·1 observation | 위 document bundle + `data/reference/normalization_policy.json` | `ecoguard.preprocessing.normalize_records` | `test_preprocessing.PreprocessingTests.test_fixture_claim_counts_are_exact_and_auditable` | `artifacts/examples/normalized_evidence.json`의 `summary` |
| kg/MT, CN, 비율, 탄소가격 단위 정규화 | 같은 입력 | `ecoguard.preprocessing._normalize` 계열 | `test_preprocessing.PreprocessingTests.test_units_components_and_aliases_are_normalized` | `artifacts/examples/normalized_evidence.json`의 `fields` |
| OCR 메모의 Unicode minus 부호를 잃지 않고, 모호한 숫자·범위·배율·복합단위를 exact 값으로 오인하지 않음 | leading decimal, 지수표기, Unicode minus 부호, Unicode slash 복합단위, 부등식, `negative/음수`, `thousand/천`, rate 단위 공격 입력 | `_canonical_numeric_view`, `_number`, `_single_recognized_token` | `test_preprocessing.PreprocessingTests.test_numeric_grammar_preserves_supported_grouping_and_signs`; `test_preprocessing.PreprocessingTests.test_unsupported_numeric_and_unit_tokens_are_not_partially_matched`; `test_cbam.CbamTests.test_raw_ambiguous_values_cannot_reach_cbam_calculation` | 지원하는 Unicode minus는 음수 부호를 보존한 뒤 CBAM의 non-negative guard가 거절하고, 부분 숫자·범위·배율·복합단위는 parse failure와 review issue로 남아 필수 입력 경계에서 중단 |
| 문장 중간 substring·한 line 복수 label을 field로 추측하지 않음 | `CABINET WT`, `미출하량`, `M5 순중량 및 출하량` | `ecoguard.preprocessing.match_alias` | `test_ingestion.DocumentIngestionTests.test_ascii_aliases_require_word_boundaries`; `test_ingestion.DocumentIngestionTests.test_korean_aliases_require_leading_label_boundaries`; `test_ingestion.DocumentIngestionTests.test_multiple_field_aliases_on_one_line_are_quarantined` | `unmatched_lines`에 이유와 원문을 보존 |
| 원문 span·line/document hash와 선택 provenance | extraction 결과 전체 line | `extract_document_bundle`, `normalize_records` | `test_preprocessing.PreprocessingTests.test_selection_trace_keeps_span_hash_and_document_authority`; `test_preprocessing.PreprocessingTests.test_tampered_adapter_provenance_cannot_enter_calculation_fields` | `extracted_records.json`, `normalized_evidence.json` |
| Legal corpus 8건·eval 34건(16 positive, 8 distractor, 10 negative), Recall@3/MRR/negative abstention 1.0 | `data/reference/legal_corpus.json`, `data/reference/legal_eval.json` | `ecoguard.legal.LegalRetriever`, `evaluate` | `test_legal.LegalRetrievalV2Tests.test_corpus_keeps_eight_article_records_and_paragraph_metadata`; `test_legal.LegalRetrievalV2Tests.test_evaluation_reports_retrieval_and_selective_metrics` | `artifacts/examples/legal_retrieval_evaluation.json` |
| Legal corpus 2개 기본법과 방법론 경계 2개 시행법의 CELEX·ELI·확인일이 source manifest와 일치 | `legal_corpus.json`, `source_manifest.json` | `ecoguard.legal.validate_source_manifest` | `test_legal.LegalRetrievalV2Tests.test_corpus_is_bound_to_pinned_source_manifest`; `test_pipeline.PipelineTests.test_reproduction_rejects_legal_manifest_corpus_mismatch` | 두 legal artifact의 `source_binding`에 corpus/methodology 역할을 분리; 누락·불일치 시 artifact 생성 전 실패 |
| OOD·미지원 Article은 citation을 만들지 않고 기권 | 같은 corpus와 hard-negative query | `LegalRetriever.retrieve` | `test_legal.LegalRetrievalV2Tests.test_hard_negatives_abstain_with_structured_reason`; `test_legal.LegalRetrievalV2Tests.test_unknown_explicit_article_abstains_instead_of_substituting` | evaluation의 `decision`, `reason_code`, `results` |
| Legal 평가 label 자체가 중복·미등록·상충하지 않음 | `legal_eval.json` | `ecoguard.legal._validate_evaluation_cases` | `test_legal.LegalRetrievalV2Tests.test_evaluation_rejects_duplicate_unknown_and_self_contradictory_labels` | 유효하지 않은 fixture는 artifact 생성 전 실패 |
| 개발셋과 분리한 blind-style 36건(16 positive·8 distractor·12 negative)이 threshold를 통과하고 외부 blind로 오인되지 않음 | `data/benchmarks/legal_blind.json` | `ecoguard.regulatory.evaluate_blind_fixture` | `test_regulatory_coverage.RegulatoryCoverageTests.test_blind_style_fixture_is_separate_and_explicitly_not_external`; `test_regulatory_coverage.RegulatoryCoverageTests.test_blind_style_evaluation_is_deterministic_and_meets_frozen_thresholds` | `artifacts/benchmarks/legal_blind_evaluation.json`; maintainer 작성 post-hoc holdout |
| CBAM 기술 인벤토리 11-step DAG와 총 1,111.36 tCO2e | normalized evidence | `ecoguard.cbam.calculate_exposure` | `test_cbam.CbamTests.test_calculation_trace_is_complete_topological_and_arithmetic`; `test_cbam.CbamTests.test_v3_golden_inventory_and_legacy_comparison` | `artifacts/examples/cbam_exposure.json` |
| direct 970.50 + indirect 140.86, process 731.36 + precursor 380.00 | 품목별 4개 component intensity | `calculate_exposure` axis reconciliation | `test_cbam.CbamTests.test_direct_indirect_and_process_precursor_axes_reconcile` | `cbam_exposure.json`의 `technical_inventory.component_axes` |
| 3개 가격 민감도 €97,244.00 / €77,795.20 / €66,681.60 | 가격·factor evidence와 analyst assumption | `ecoguard.cbam._price_scenario` | `test_cbam.CbamTests.test_three_price_sensitivity_scenarios_reproduce_exactly` | `cbam_exposure.json`의 `sensitivity_scenarios` |
| Default-value 배출도 mass와 default intensity에서 추적 가능 | normalized shipment mass/default intensity | `calculate_exposure`의 `default_value_fixture.embedded_emissions` | `test_cbam.CbamTests.test_default_value_trace_derives_emissions_from_evidence` | `cbam_exposure.json`의 `default_value_scenario.pricing_trace` |
| CBAM 계산 전에 value·unit·CN·모든 후보의 raw normalization·source span·line/document hash·confidence·정책 권위·선택 순위·후보 완전성을 재검증 | retained 37 source lines, document manifest, full policy, normalized typed field | `validate_normalized_evidence`, `_validate_candidate_source`, `_validated_ranked_candidates`, `_expected_candidate_index`, `_decimal`, `_text`, `_source` | `test_cbam.CbamTests.test_units_cn_and_evidence_hash_are_validated_at_calculation_boundary`; `test_cbam.CbamTests.test_calculation_revalidates_candidate_against_retained_source_lines`; `test_cbam.CbamTests.test_calculation_rejects_hidden_candidate_and_manifest_count_tampering` | 미선택 상위 후보를 parse failure로 위조하거나 conflict 후보를 삭제하거나 authority/confidence/rank를 바꿔도 계산 전에 `ValueError` |
| 공식 EUR-Lex에 대조한 선정 CBAM 요구사항 15개 중 partial 8·미구현 7·완전 구현 0 | `data/reference/cbam_rule_coverage.json` | `ecoguard.regulatory.validate_coverage_matrix` | `test_regulatory_coverage.RegulatoryCoverageTests.test_no_selected_statutory_pathway_is_claimed_complete`; `test_regulatory_coverage.RegulatoryCoverageTests.test_coverage_matrix_binds_official_eur_lex_sources_and_check_date` | `artifacts/benchmarks/cbam_rule_coverage_report.json`; 모든 행에 expert review와 누락 입력을 고정 |
| Forest 6×6에서 TP=11·FP=1·FN=1·TN=23, F1=0.916667, IoU=0.846154 | `forest_case.json`, `forest_pixels.csv`, `forest_reference_mask.csv` | `ecoguard.forest.analyze_forest_case`, `evaluate_binary_mask` | `test_forest.ForestV2Tests.test_manifest_case_has_exact_prediction_reference_and_metrics` | `forest_change.json`, `forest_change.geojson`, `forest_change.svg` |
| 36-cell RFC 7946 형태 GeoJSON과 TP/FP/FN/TN SVG | 같은 forest result | `build_regions_geojson`, `render_change_svg` | `test_forest.ForestV2Tests.test_geojson_is_complete_stable_and_rfc7946_shaped`; `test_forest.ForestV2Tests.test_svg_is_valid_xml_with_all_confusion_classes` | `forest_change.geojson`, `forest_change.svg` |
| 합성 geospatial case가 CRS/affine area, cloud/nodata, 시간·계절, tile holdout과 reference provenance를 검증 | `data/benchmarks/forest/*` | `ecoguard.geospatial.analyze_geospatial_benchmark` | `test_geospatial.GeospatialBenchmarkTests.test_summary_proves_geospatial_mask_temporal_and_holdout_plumbing`; `test_geospatial.GeospatialBenchmarkTests.test_only_valid_holdout_pixels_contribute_to_reported_metrics` | `artifacts/benchmarks/forest_geospatial_summary.json`: valid holdout 9, TP4/FP1/FN1/TN3; 실제 위성 정확도 아님 |
| Local API가 동일 CBAM 검증과 Legal 기권 경계를 사용하며 production-ready로 표시되지 않음 | normalized golden + query JSON | `ecoguard.api.application` | `test_api.LocalApiTests.test_cbam_endpoint_reuses_validated_calculation_boundary`; `test_api.LocalApiTests.test_health_identifies_non_production_package_version`; `test_api.LocalApiTests.test_boundary_rejects_bad_media_json_size_path_and_method` | `/health`, `/v1/cbam/calculate`, `/v1/legal/retrieve`; 인증 없는 loopback 예제 |
| Manifest 8 input·10 output의 byte/hash가 실제 파일과 일치 | 모든 공개 input + artifact | `ecoguard.pipeline.reproduce` | `test_contracts.PublicContractTests.test_manifest_hashes_match_every_committed_input_and_output_byte` | `artifacts/examples/artifact_manifest.json` |
| 공개 fixture 4종은 Draft 2020-12 JSON Schema와 runtime의 핵심 contract를 함께 만족 | trade bundle, normalization policy, forest case, artifact manifest | `schemas/*.schema.json` + 각 runtime loader | `test_contracts.PublicContractTests.test_public_fixtures_validate_against_draft_2020_12_schemas`; `test_contracts.PublicContractTests.test_forest_schema_rejects_invalid_runtime_contract_examples` | const·required·additionalProperties·decimal string·nested shape 오류를 거절 |
| runtime은 network I/O 없이 재현 가능 | packaged/public fixture | `ecoguard.pipeline.reproduce` | `test_pipeline.PipelineTests.test_reproduction_performs_no_network_io` | 임시 디렉터리의 11개 public artifact |
| Benchmark 10 input·5 non-manifest output의 byte/hash가 고정되고 network 없이 재현됨 | OCR/geospatial/legal/CBAM benchmark fixture + legal source manifest | `ecoguard.benchmark.run_benchmarks` | `test_benchmark_pipeline.BenchmarkPipelineTests.test_suite_writes_all_outputs_deterministically`; `test_benchmark_pipeline.BenchmarkPipelineTests.test_suite_performs_no_network_io` | `artifacts/benchmarks/benchmark_manifest.json` + 5 output |
| 생성형 속성 입력에서도 명시적 범위·복합단위·lineage 변조가 계산값이 되지 않고 mask가 universe를 분할 | Hypothesis가 고정 설정으로 생성한 입력 | parser/CBAM/forest/API 경계 | `test_properties.ParserPropertyTests.test_explicit_mass_bounds_never_become_exact_values`; `test_properties.CalculationPropertyTests.test_binary_mask_confusion_matrix_always_partitions_universe` | release verifier가 branch coverage 85% 이상과 함께 실행 |
| 대회 보관 자료와 공개 재구성의 시간·증거 한계를 구분 | `competition_archive_attestation.json` | 계산 대상 아님 | `test_competition_provenance.CompetitionProvenanceTests.test_private_archive_attestation_is_minimal_and_unambiguous` | SHA는 추후 byte 대조용이며 공인 timestamp·독립 저작권 증명이 아님 |
| 동일 commit의 wheel SHA가 일치하고, 설치 wheel을 저장소 밖에서 실행해 golden과 byte-identical | Git tracked source와 wheel에 포함된 resource 8개 | `scripts/verify_release.sh` | `test_resources.PackagedResourceTests.test_package_contains_only_declared_public_resources`; script가 dirty/untracked guard, tracked-only snapshot, `SOURCE_DATE_EPOCH` 고정 2회 build, wheel SHA 비교, source/installed-wheel tests와 `diff -ru`를 모두 실행 | ignored 파일은 release snapshot에서 제외; build dependency 최초 확보까지 offline이라는 주장은 아님 |

## 선택형 Forest XAI의 별도 증거

이 표의 공개 위성 축은 **단일시점 forest-cover segmentation**입니다.
합성 before/after 축은 모델·설명 코드의 smoke test이고, 수상 후 재구성 축은
발표 아이디어의 GAN latent와 2.5D 연산을 현재 공개 계약으로 구현합니다. 셋을 합쳐 실제
bi-temporal change model이라고 주장하지 않습니다.

| 공개 주장 | 입력·고정 계약 | 직접 검증 | committed 산출물·결과 | 해석 경계 |
|---|---|---|---|---|
| 재배포 가능한 공개 Sentinel-2 derivative | Bragagnolo 등 Zenodo DOI `10.5281/zenodo.4498086`, CC BY 4.0; Hugging Face mirror commit `516251c601e1d2fe579f8e2d15589140f94383b9`와 shard·row·hash·downsampling | strict loader가 manifest, NPY SHA-256, dtype, shape, finite/range, sample ID를 fail-closed 검사 | train 24 / evaluation 12 chip, 각 `[N,4,64,64]` | 원본 8-bit 설명과 mirror의 255 초과 실측값이 다르며, preparation은 pinned mirror→derivative를 재현 |
| Scene-separated split | train 2 source scenes, evaluation 2 source scenes | verifier·학습 경로가 scene ID 교집을, verifier가 sample ID 교집을 거절 | scene overlap 0 | 외부·blind split이 아니고 maintainer-selected fixture |
| CNN checkpoint binding | `TinyForestCoverSegmenter`, 2,929 parameters, CPU seed 20260812, threshold 0.55 | safe checkpoint load, checkpoint/sidecar SHA, tensor-state SHA, fixture·normalization·config binding | checkpoint SHA-256 `270fe3c7f857cfee541240ae8af09968e76b194c367539904c64f619953f168c` | SHA-256은 변조 탐지용이지 서명·공인 timestamp·저자성 증명이 아님 |
| Committed checkpoint CPU 재평가 | evaluation 12 chip·49,152 pixel | verifier가 추론·metric JSON을 새로 만들어 committed JSON 전체와 대조 | F1 0.947917, precision 0.979623, recall 0.918200, IoU 0.900991, pixel accuracy 0.947550; TP/FP/FN/TN 23,460/488/2,090/23,114 | 산림변화·훼손·현장 성능이 아닌 작은 forest-cover capability fixture |
| Grad-CAM 재생성 | evaluation sample `S2-EV-003`, source reference mask로 target region 고정 | RGB·reference·probability·Grad-CAM을 재생성해 각 SHA-256 대조 | explanation JSON 1개 + PNG 4개; public demo 전체 9 file | 모델 민감도이지 인과·생태학적 근거·metric 개선 증거가 아님 |
| 합성 change CNN·JVP mechanics | 고정 seed로 생성한 before/after 4-band rectangle/noise·change mask | 연구 테스트가 shape/range, train→evaluate→explain, Grad-CAM, JVP direction, checkpoint tamper guard를 검사 | generated checkpoint·metric·Grad-CAM·NPZ·JVP trace | 실제 위성 metric이 아니며 GAN·HiGAN·causal counterfactual이 아님 |
| 수상 후 tiny-GAN 재구성 | public train split, 고정 seed·CPU config, `z0`·`z1`, committed forest-cover CNN | checkpoint/sidecar file·tensor hash, exact forest probability curve·alpha 0.5 unit-path JVP, decode한 contact-sheet RGB의 최대 replay 오차 2/255 | tiny generator/critic checkpoint, interpolation JSON·PNG; committed PNG SHA exact, path length 4.24485588, derivative 0.01209233 | 당시 code가 아님; 특정 HiGAN·photorealism·생성 품질·발표 수치 증거가 아님 |
| 수상 후 2.5D height-field 재구성 | evaluation RGB·forest probability + 결정론적 synthetic coarse height | x/y 격자 bilinear height interpolation, drape, height/probability와 1089-vertex/1024-face mesh를 재생성; committed SHA exact, float replay 절대오차 1e-6, integer faces exact | terrain JSON·PNG, `[64,64]` float32 height/probability, `[33,33,3]` float32 vertices, `[1024,4]` int32 faces | 합성 높이이며 DEM·stereo·LiDAR 또는 위성에서 복원한 3D가 아님 |
| 명시적 claim boundary | public JSON은 single-date, synthetic change JSON은 not-a-GAN, reconstruction JSON은 post-award·not-HiGAN·not-photorealistic·synthetic-height를 고정 | 연구 test suite + public/reconstruction 전용 verifier | core 174개 test method·wheel·benchmark count에 포함하지 않음 | 실제 bi-temporal change, `83.4% → 96.2%`, HiGAN, satellite-derived elevation은 미재현 |

연구 트랙의 fast verification은 committed checkpoint를 재학습하지 않고 추론·설명
artifact를 재생성합니다. `--retrain`을 붙이면 80 epoch CPU 학습 후 tensor
state·metadata·metric까지 추가로 비교합니다. PyTorch container byte는 동일한 tensor에서도
달라질 수 있으므로, 재학습 audit은 새 checkpoint file의 byte를 committed checkpoint와
강제하지 않고 각 sidecar의 file hash와 tensor-state hash를 따로 검사합니다.
Reconstruction verifier도 committed GAN과 2.5D 산출물의 hash·claim boundary를
검사하고 interpolation/drape를 재생성합니다. Committed file SHA는 exact하게
고정하고, float machine-array replay는 절대오차 1e-6, integer faces는 exact,
latent contact sheet는 decode RGB 최대 2/255로 대조합니다. `--retrain`을 붙였을
때만 tiny GAN CPU 학습을 반복해 tensor state·metadata·numeric semantics와 bounded
preview를 대조합니다.

## 입력 변화와 동등 변형

| 성질 | 변형 | 검증 테스트 | 기대 결과 |
|---|---|---|---|
| Mutation sensitivity: trade | 인증서 가격 한 line을 87.50→88.00으로 변경 | `test_pipeline.PipelineTests.test_one_source_line_mutation_changes_lineage_and_cbam_result` | line/input hash와 normalized price가 바뀌고 실제-data exposure가 €97,799.68로 변함; 다른 7개 input hash는 유지 |
| Mutation sensitivity: forest | 한 cell의 after red/NIR를 바꿔 loss flag 추가 | `test_forest.ForestV2Tests.test_one_band_mutation_changes_mask_metrics_regions_and_visuals` | FP 1→2, TN 23→22, F1 0.916667→0.88, region·GeoJSON·SVG 변화 |
| Order invariance: document | document/page/line 순서 반전 | `test_ingestion.DocumentIngestionTests.test_input_order_does_not_change_extraction`; `test_cbam.CbamTests.test_document_input_order_does_not_change_cbam_result` | canonical extraction과 CBAM 결과 동일 |
| Order/Unicode invariance: legal | corpus 순서 반전, full-width Unicode query | `test_legal.LegalRetrievalV2Tests.test_corpus_order_and_unicode_formatting_do_not_change_ranking` | corpus hash와 citation ranking 동일 |
| Order/notation invariance: forest | CSV 행 순서 반전, `0.18`→`0.1800` | `test_forest.ForestV2Tests.test_input_row_order_does_not_change_any_output`; `test_forest.ForestV2Tests.test_equivalent_decimal_notation_does_not_change_outputs` | JSON result·GeoJSON·SVG 의미 결과 동일 |

## Core v0.5 실행

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
./scripts/verify_release.sh
```

두 번째 명령은 clean worktree에서만 실행되며, 완료돼야 source tree, 두 번 재현한 동일 wheel, 저장소 밖 runtime과 committed golden까지 함께 검증한 것입니다. GitHub Actions는 이 계약을 Python 3.11·3.12·3.13·3.14에서 각각 실행합니다.

## 선택형 Forest XAI 실행

```bash
python -m pip install \
  --index-url https://download.pytorch.org/whl/cpu \
  "torch==2.13.0"
python -m pip install -r research/forest_xai/requirements.txt
python -m unittest discover -s research/forest_xai/tests -v
python -m research.forest_xai.scripts.verify_public_demo
python -m research.forest_xai.scripts.verify_reconstruction
```

전체 CPU 재학습 audit이 필요한 경우에만 다음을 별도로 실행합니다.

```bash
python -m research.forest_xai.scripts.verify_public_demo --retrain
python -m research.forest_xai.scripts.verify_reconstruction --retrain
```

이 실행은 core wheel을 변경하거나 core 174개 test method에 연구 결과를
더하지 않습니다. 세부 입력·model claim은 [data card](../research/forest_xai/DATA_CARD.md)와
[model card](../research/forest_xai/MODEL_CARD.md),
[reconstruction card](../research/forest_xai/RECONSTRUCTION_CARD.md)를 함께 읽어야 합니다.
