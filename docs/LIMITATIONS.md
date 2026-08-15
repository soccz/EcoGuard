# 한계와 다음 검증

## 이 공개본이 증명하지 않는 것

### 대회 당시 운영 백엔드가 아니다

공개 코드는 발표의 기술 논지를 검증 가능하게 다시 만든 v0.5 baseline입니다. 대회 당시 OCR·Legal RAG·산림 모델 전체 코드의 복원본이나 실제 은행 시스템이 아닙니다.

### Core 사례는 합성이고, 선택형 위성 연구만 공개 derivative를 쓴다

기업, 거래, 문서, 설비, 좌표, 배출집약도, 가격과 core reference mask는
시연용 합성 사례입니다. 실제 기업 성능, 은행 연동, 통관 결과 또는 위성 현장을
뜻하지 않습니다. 법령 URL만 공식 EUR-Lex를 가리키며 한국어 요약은 팀 작성
비공식 metadata입니다.

예외는 core wheel 밖의 `research/forest_xai/data/public_fixture`입니다. 이는
Bragagnolo 등의 CC BY 4.0 Sentinel-2 데이터에서 만든 소형 `.npy`
derivative이며 출처·선택 row·변환·hash를 data card에 고정합니다. 이 예외는
실제 공개 pixel을 처리하는 코드 경계를 증명할 뿐, 현장 성능을 증명하지 않습니다.

### OCR vision model은 포함하지 않는다

Tesseract TSV·provider-neutral JSON·pdftotext 어댑터와 합성 field benchmark는 포함하지만 OCR 엔진을 실행하거나 평가하지 않습니다. 공개본은 extraction boundary, alias mapping, unit normalization, source lineage, candidate selection, conflict detection을 검증합니다. 실제 scan 품질별 character/field recognition accuracy는 측정하지 않습니다.

### 법률 retrieval 평가는 작고 닫혀 있다

8개 article record와 34개 개발 query, 별도로 저장한 36개 maintainer-authored post-hoc blind-style query로 구성합니다. `Recall@3=1.0`과 negative abstention 1.0은 이 작은 고정 파일들의 회귀 결과일 뿐, 외부 독립 blind 평가나 모든 EU 법률·언어·개정·질문에 대한 일반화 성능이 아닙니다.

Paragraph는 각 article record의 metadata 범위입니다. Paragraph별 공식 원문 chunk를 검색하는 시스템이 아니므로 “몇 항을 언제나 정확히 찾는다”고 주장하지 않습니다. LLM answer generation, citation faithfulness, legal conclusion correctness도 평가하지 않습니다.

### CBAM은 기술 인벤토리 가격 민감도다

직접·간접·전구물질 구성요소와 trace는 합성 산술을 재현합니다. 그러나 구성요소의 법정 포함 여부를 판정하지 않습니다. Implementing Regulation 2025/2547의 전체 계산 규칙, 2025/2620의 free-allocation adjustment, 실제 certificate price, Article 9의 실제 납부·rebate·통화환산·독립 확인, 면제와 신고 절차는 구현하지 않습니다.

따라서 결과에 `statutory_calculator: false`를 기록하며 exposure를 payable amount나 의무액으로 사용하지 않습니다.

### 산림 core는 합성 plumbing benchmark이다

Core의 6×6 reflectance 회귀셋과 4×6 geospatial benchmark는 모두
합성입니다. 후자는 선언된 cloud/shadow/nodata mask, acquisition season,
affine transform과 tile holdout 처리를 검사하지만 실제 영상에서 그 정보를
생성하거나 품질을 평가하지 않습니다. 방사·대기 보정, raster I/O,
reprojection, co-registration과 temporal compositing을 구현하지 않았습니다. Core의
F1과 IoU는 metric code path 검증값이지 실제 위성 성능이 아닙니다.

### 공개 Sentinel-2 CNN은 단일시점 산림피복 capability fixture다

선택형 연구는 실제 공개 Sentinel-2 L2A 4-band derivative에서
`TinyForestCoverSegmenter`를 학습·평가하고 Grad-CAM을 만듭니다. 그러나 train
24 chip·2 scene과 evaluation 12 chip·2 scene만 선택한 작은 maintainer-authored
fixture입니다. Scene overlap은 0이지만 외부 독립·blind benchmark가 아니며,
지리·계절·cloud·shadow·sensor 일반화를 평가하지 않았습니다. F1
0.947917과 IoU 0.900991은 이 단일시점 forest/non-forest fixture에만 해당하며,
발표 수치나 산림변화·훼손 정확도로 읽으면 안 됩니다.

재료 경계에도 주의가 필요합니다. 원본 dataset 설명의 8-bit 표현과 재현
경로에서 사용한 Hugging Face Parquet mirror의 실측 수치 범위(255 초과)가
일치하지 않습니다. 따라서 준비 스크립트는 pinned mirror→committed derivative를
재현하지만, mirror가 원본 archive와 동일한 수치 표현임을 증명하지는 않습니다.
정확한 source·conversion 계약은
[`DATA_CARD.md`](../research/forest_xai/DATA_CARD.md)의 경계를 따릅니다.

### 합성 before/after CNN·JVP는 실제 change model이 아니다

두 번째 연구 축은 프로그램으로 그린 before/after 4-band pair와 change
mask로 train→evaluate→explain 경로를 검사합니다. Local classifier-score JVP는
작은 latent direction에 대한 국소 민감도입니다. GAN·HiGAN, 인과 counterfactual,
의미론적 latent factor 또는 실제 위성 성능을 증명하지 않습니다.

### 수상 후 GAN·2.5D 재구성은 당시 구현이나 실사화 증거가 아니다

대회 발표에서 GAN latent 보간과 z축/현장형 표현을 시도했지만, 당시 GAN 코드,
notebook, checkpoint와 재현 가능한 생성 artifact는 전수조사에서 발견되지
않았습니다. 현재 `research/forest_xai`의 tiny GAN은 공개 fixture로 **수상 후
새로 학습한 개념 재구성**입니다. 한 `z0 → z1` 경로와 forest-score JVP가
실행된다는 것만 증명하며 HiGAN, 의미론적 latent, photorealism 또는 당시 성능을
증명하지 않습니다.

2.5D drape도 실제 RGB와 forest probability를 난수 seed로 만든 합성 높이장에
얹은 것입니다. x/y 격자의 bilinear height interpolation은 기계적으로 재현되지만 그 높이는 Sentinel-2,
DEM, stereo, LiDAR 또는 photogrammetry에서 얻은 값이 아닙니다. 상세 계약은
[`RECONSTRUCTION_CARD.md`](../research/forest_xai/RECONSTRUCTION_CARD.md)에
있습니다.

### 아직 공개 재현하지 못한 산림 주장

- 라이선스·scene ID·시간·공간 분할이 고정된 실제 bi-temporal change benchmark
- 특정 HiGAN/HIGAN 논문·공개 구현·학습 계약을 고정한 재현
- 발표 당시 `83.4% → 96.2%`를 같은 task·data·split·metric으로 다시 만드는 평가
- 위성 영상에서 고도·기하를 복원하는 3D pipeline

현재 추가된 합성 높이장 drape는 **2.5D 시각화**입니다. 향후 라이선스가
명확한 DEM을 입력으로 바꾸더라도 그 범위는 DEM drape이며, 위성 RGB 또는
Grad-CAM에서 높이를 복원했다고 부르면 안 됩니다.

### 보안·운영 통제는 범위 밖이다

공개 baseline은 개인정보, 접근제어, 감사 저장소, key management, bank API, queue/retry, model registry, regulation update workflow를 구현하지 않습니다. 모든 출력은 자동 금융 판단이 아니라 human-review 자료입니다.

## 다음 검증 순서

| 우선순위 | 다음 검증 | 완료 조건 |
|---|---|---|
| 1 | Public scan benchmark | 라이선스가 명확한 공개 scan set, 실제 OCR engine/version 고정, field-level precision/recall, 실패 사례와 비용 공개 |
| 2 | Document schema expansion | 표 병합, 다국어, 중복 revision, 서명·발행시각·문서 우선순위 테스트 |
| 3 | Legal corpus expansion | 공식 원문 paragraph chunk, amendment/version test, 더 큰 blind query set, citation faithfulness 평가 |
| 4 | CBAM methodology review | 현재 15개 coverage map을 공식 입력 source manifest·규제범위 decision table·전문가 검토와 연결 |
| 5 | Bi-temporal remote-sensing benchmark | 라이선스가 명확한 public scene pair에서 reprojection·co-registration을 수행하고 독립 change reference·cloud/seasonality 오류와 시공간 누수를 평가 |
| 6 | Operational controls | 개인정보·권한·감사로그·재처리·규정 버전·human override 검증 |

실제 파일럿을 주장하려면 입력 사용권, 익명화, 평가 설계, 실패 기준, 법무·규제 검토와 책임 경계를 먼저 문서화해야 합니다.
