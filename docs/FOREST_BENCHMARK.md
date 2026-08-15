# 산림 benchmark와 선택형 Forest XAI

이 저장소의 산림 증거는 입력·task·metric이 다른 네 개 코드 경로입니다.
한 경로의 수치를 다른 경로의 성능으로 읽지 않아야 합니다.

| 증거 경로 | 입력 | 구현 | 증명하는 것 | 증명하지 않는 것 |
|---|---|---|---|---|
| Core NDVI·geospatial | 6×6, 4×6 합성 band/reference | dependency-free NDVI, CRS·affine·QA·tile holdout, GeoJSON/SVG | metric·지리공간 contract의 결정론적 재현 | 실제 위성 정확도 |
| Public forest cover | CC BY 4.0 Sentinel-2 4-band derivative, 단일시점 | CNN 학습·추론·평가, checkpoint, Grad-CAM | 실제 공개 pixel을 다루는 소형 capability fixture | 전후 변화·훼손, 외부 일반화 |
| Synthetic change mechanics | 프로그램으로 만든 before/after 4-band pair | change CNN, Grad-CAM, local latent JVP | train→evaluate→explain 코드 경로 | 실제 위성 metric, GAN·HiGAN, 인과 설명 |
| Post-award concept reconstruction | 공개 fixture로 새로 학습한 tiny GAN + 합성 높이장 | latent `z0 → z1` 보간·forest-score JVP, 2.5D RGB/probability drape | 발표 아이디어의 두 연산을 현재 코드로 실행·검증 | 당시 구현, HiGAN, photorealism, 실제 고도·3D |

실제 bi-temporal 산림변화, 발표 수치 `83.4% → 96.2%`, HiGAN 재현,
위성에서 고도·3D를 복원하는 pipeline은 네 경로 어느 것으로도 검증되지 않습니다.

## Core geospatial plumbing의 증명 범위

`src/ecoguard/geospatial.py`는 외부 runtime dependency 없이 다음을 fail-closed 방식으로 검사합니다.

- `EPSG:32652` projected-metre CRS의 authority, code, name, kind, unit 조합
- GDAL 순서 6계수 affine geotransform과 0이 아닌 determinant
- affine corner에서 만든 셀 polygon, determinant에서 계산한 셀 면적
- red/NIR의 nodata와 before/after cloud·shadow QA를 NDVI 전에 제외하는 정책
- UTC acquisition timestamp, 전후 순서, 경과기간, 동일 season label, day-of-year 허용차
- 크기가 나누어떨어지지 않아도 `clip`하는 row-major 결정론적 tiling
- tile 전체를 train 또는 holdout 중 하나에만 두는 spatial split
- 별도 reference CSV의 작성자·시각·방법·라이선스·독립 ground-truth 여부
- 유효한 holdout 셀만 사용하는 confusion matrix와 precision/recall/F1/IoU
- manifest·scene CSV·reference CSV의 byte 수와 SHA-256

이 core 검증은 CRS registry 조회, raster reprojection, 영상 co-registration 또는
학습 모델을 구현하지 않습니다. `EPSG:32652` 의미는 작은 offline
allowlist로 고정하며 결과에도 `registry_lookup_performed: false`를 남깁니다.

## Core 공개 fixture

| 파일 | 성격 |
|---|---|
| `data/benchmarks/forest/synthetic_geospatial_case.json` | 실행 manifest와 주장 경계 |
| `data/benchmarks/forest/benchmark.schema.json` | Draft 2020-12 machine-readable shape contract |
| `data/benchmarks/forest/synthetic_scene_pixels.csv` | 4×6 합성 red/NIR·QA 입력 |
| `data/benchmarks/forest/synthetic_reference_mask.csv` | 입력 band와 분리된 합성 binary reference |
| `data/benchmarks/forest/expected_summary.json` | 결정론적 golden summary |
| `data/benchmarks/forest/expected_cells.geojson` | 24개 셀의 결정론적 golden polygon 출력 |
| `data/benchmarks/forest/public_data_opt_in_manifest.json` | 실제 공개 위성 자료의 공식 discovery·terms metadata만 기록 |

위 표의 core scene ID, reflectance, QA, 좌표와 reference는 모두 팀 작성
합성값입니다. UTM 좌표는 geometry 연산을 시험하기 위한 값이며 특정
기업·농장·현장을 나타내지 않습니다. Reference도 독립 현장조사가 아니므로
manifest와 summary에 `independent_ground_truth: false`를 명시합니다.

## Core 재현 명령

기존 `ecoguard reproduce` 산출물과 버전 경계를 바꾸지 않도록 별도 module entry point를 사용합니다.

```bash
PYTHONPATH=src python3 -m ecoguard.geospatial \
  data/benchmarks/forest/synthetic_geospatial_case.json \
  --summary /tmp/ecoguard-forest-summary.json \
  --geojson /tmp/ecoguard-forest-cells.geojson

cmp data/benchmarks/forest/expected_summary.json \
  /tmp/ecoguard-forest-summary.json
cmp data/benchmarks/forest/expected_cells.geojson \
  /tmp/ecoguard-forest-cells.geojson
```

`--summary`와 `--geojson`을 생략하면 summary를 stdout으로 출력합니다. 입력 file path는 manifest와 같은 디렉터리의 단일 filename만 허용하므로 absolute path와 `..` traversal을 거절합니다.

## 고정 결과

| 검증 항목 | 결과 |
|---|---:|
| Grid | 4 rows × 6 cols = 24 pixels |
| Affine | `[500000, 10, 0, 4100000, 0, -10]` |
| Pixel / total planar area | 100m² / 2,400m² |
| Tile | 2×3 pixels, row-major 4개 |
| Split | train 12 / holdout 12 pixels |
| Mask | valid 20 / masked 4 pixels |
| Holdout mask | holdout 12개 중 3개 제외 |
| Evaluation universe | valid holdout 9 pixels |
| Confusion matrix | TP 4 · FP 1 · FN 1 · TN 3 |
| Metrics | Precision 0.8 · Recall 0.8 · F1 0.8 · IoU 0.666667 |
| Acquisition policy | 같은 `dry` label, day-of-year 차이 2일, 전체 경과 368.001389일 |

오탐과 미탐을 각각 하나씩 넣은 이유는 metric code가 완벽한 synthetic 답을 그대로 복사하는지 확인하는 대신, prediction과 reference가 어긋나는 경우를 보존하는지 검증하기 위해서입니다. 이 수치는 실제 현장 성능이 아닙니다.

## Geometry와 GeoJSON 경계

GDAL-order transform은 다음 식으로 pixel corner를 계산합니다.

```text
x = x_origin + col × pixel_width + row × row_rotation
y = y_origin + col × col_rotation + row × pixel_height

pixel area = abs(pixel_width × pixel_height
                 − row_rotation × col_rotation)
```

각 exterior ring은 닫혀 있고 counter-clockwise이며, fixture의 모든 polygon 면적은 정확히 100m²입니다. 전체 24개 polygon 면적 합은 2,400m²입니다.

Golden `.geojson`은 **현재 정수 계수 fixture의** affine 결과를 정확히 검사하려고 native projected coordinate를 유지합니다. 일반 입력은 JSON 수치로 내보낼 때 IEEE-754 float 표현 범위의 정밀도를 사용합니다. RFC 7946 교환 형식은 WGS84 longitude/latitude를 요구하므로 출력에 `rfc7946_wgs84: false`와 reprojection 경고를 넣습니다. 따라서 이 파일을 일반 웹 지도에 바로 올리는 것이 아니라, 실제 adapter에서 CRS-aware library로 WGS84에 재투영한 뒤 별도 정확도·axis-order 검사를 해야 합니다.

## Mask와 평가 universe

마스크 이유는 독립적으로 보존합니다.

```text
nodata_before / nodata_after
qa_before:cloud / qa_before:shadow
qa_after:cloud  / qa_after:shadow
```

필요한 band 중 하나라도 nodata이거나 어느 시점의 QA가 cloud/shadow이면 NDVI와 prediction은 `null`입니다. Reference label은 삭제하지 않지만 그 셀은 confusion matrix에 들어가지 않습니다. 이 fixture에는 cloud-before, nodata-after, shadow-after, cloud-after가 각각 한 개씩 있습니다.

보고 metric의 universe는 다음 교집합입니다.

```text
declared holdout tile
∩ complete reference label
∩ valid before bands and QA
∩ valid after bands and QA
```

Train tile의 예측은 출력에서 확인할 수 있지만 보고 metric에는 포함하지 않습니다. 이 rule은 학습되지 않았으므로 spatial holdout은 일반화 성능의 증거가 아니라 leakage-safe split plumbing의 증거입니다.

## 선택형 공개 Sentinel-2 forest-cover CNN

`research/forest_xai` 경로는 core wheel·174개 테스트·artifact 수치에서
분리된 PyTorch 연구 트랙입니다. Bragagnolo 등의 [CC BY 4.0
Sentinel-2 dataset](https://doi.org/10.5281/zenodo.4498086)에서 B4/B3/B2/B8
4-band derivative를 만들어 단일시점 forest/non-forest segmentation을 수행합니다.
Machine-readable mirror는 Hugging Face commit
`516251c601e1d2fe579f8e2d15589140f94383b9`에 고정하고 각 shard의
SHA-256·선택 row를 fixture manifest에 기록합니다.

| 항목 | 고정 계약 |
|---|---|
| Input | train `[24, 4, 64, 64]`, evaluation `[12, 4, 64, 64]` |
| Split | train 2 source scenes / evaluation 2 source scenes / scene overlap 0 |
| Model | `TinyForestCoverSegmenter`, 2,929 parameters, threshold 0.55 |
| Evaluation | F1 0.947917, precision 0.979623, recall 0.918200, IoU 0.900991, pixel accuracy 0.947550 |
| Confusion | TP 23,460 / FP 488 / FN 2,090 / TN 23,114 |
| Explanation | evaluation sample `S2-EV-003`의 RGB·reference·probability·Grad-CAM 4개 PNG |

별도 환경에 고정 의존성을 설치한 뒤 다음을 실행합니다.

```bash
python -m pip install \
  --index-url https://download.pytorch.org/whl/cpu \
  "torch==2.13.0"
python -m pip install -r research/forest_xai/requirements.txt
python -m unittest discover -s research/forest_xai/tests -v
python -m research.forest_xai.scripts.verify_public_demo
```

마지막 명령은 모델을 재학습하지 않고 다음을 한번에 검증합니다.

1. 모든 committed NPY의 hash·shape·dtype·range와 scene 분리
2. checkpoint·sidecar·tensor-state·fixture binding
3. CPU 재추론으로 `evaluation.json` 전체 일치
4. RGB·reference·probability·Grad-CAM 재생성 및 SHA-256 일치
5. single-date forest cover일 뿐이라는 machine-readable claim boundary

80 epoch CPU 재학습으로 tensor state·metadata·metric까지 다시 확인하려면
마지막 명령에 `--retrain`을 붙입니다. 소스·derivative 계약은
[`DATA_CARD.md`](../research/forest_xai/DATA_CARD.md), 모델·metric·위험은
[`MODEL_CARD.md`](../research/forest_xai/MODEL_CARD.md)를 기준으로 합니다.

### 공개 fixture의 한계

이 결과는 maintainer가 선택한 4 scene·36 chip의 소형 capability fixture입니다.
독립 외부 평가, blind row 선택, 지리·계절·cloud·shadow 강건성 평가가 없습니다.
또한 원본 dataset 설명의 8-bit 표현과 pinned Hugging Face Parquet mirror의
실측 수치 범위(255 초과)가 일치하지 않으므로, preparation path는 mirror에서
committed derivative로의 변환을 재현할 뿐 원본 archive와 mirror의 수치 표현
동일성을 증명하지 않습니다. 데이터 카드에 기록한 변환·해석 경계를
함께 읽어야 합니다.

## 선택형 합성 before/after CNN·JVP

동일한 연구 디렉터리의 두 번째 축은 프로그램으로 만든 before/after 4-band
pair와 change mask를 사용합니다. 작은 change CNN의 학습·추론·평가,
segmentation Grad-CAM, encoder/generator latent에 대한 local classifier-score JVP,
checkpoint tamper guard를 실행합니다.

```bash
python -m research.forest_xai train \
  --device cpu --seed 20260812 --epochs 12 \
  --output-dir research/forest_xai/_runs/demo
python -m research.forest_xai evaluate \
  --device cpu \
  --checkpoint research/forest_xai/_runs/demo/forest_xai_checkpoint.pt \
  --output research/forest_xai/_runs/demo/evaluation.json
python -m research.forest_xai explain \
  --device cpu \
  --checkpoint research/forest_xai/_runs/demo/forest_xai_checkpoint.pt \
  --sample-index 1 --direction decrease \
  --output-dir research/forest_xai/_runs/demo/explanation
```

JVP는 학습된 합성 classifier score의 한 국소 방향을 정확히 미분하는 기계적
검사입니다. GAN이 아니고, HiGAN/HIGAN 재현이 아니며, 인과
counterfactual이나 의미론적 latent factor도 아닙니다. 실제 공개 위성 평가에는
이 경로의 metric을 사용하지 않습니다.

## 수상 후 GAN latent·2.5D 개념 재구성

대회 발표에는 GAN 계열 latent 보간과 z축을 활용한 현장형 표현을 시도했다는
설명이 있었지만, 전수조사에서 당시 학습·추론 코드, notebook, checkpoint 또는
동일 결과를 재생성할 artifact는 발견되지 않았습니다. 따라서 다음 경로는 당시
구현을 복구한 것이 아니라, 두 아이디어의 기계적 핵심을 공개 입력으로 **수상 후
새로 구현한 재구성**입니다.

| 재구성 | 고정 입력 | 실행·산출물 | 경계 |
|---|---|---|---|
| Tiny GAN | public train split 24개 4-band 64×64 chip, seed·CPU config | generator/critic 학습, hash-pinned checkpoint+sidecar | 특정 HiGAN architecture/loss의 재현 아님; photorealism·품질 metric 없음 |
| Latent path | 결정론적 `z0`, `z1`, committed GAN과 forest-cover CNN | `z0 → z1` 8-frame contact sheet, path length 4.24485588, alpha 0.5 단위방향 forest-score JVP 0.01209233, PNG+JSON | 단일 latent 경로의 국소 반응이며 semantic factor·인과 설명 아님 |
| Relief drape | evaluation RGB·forest probability + 난수 seed로 만든 coarse height | vertical scale 1.0 bilinear height, 2.5D PNG와 height/probability `[64,64]`, vertices `[33,33,3]`, faces `[1024,4]` NPY | 높이는 합성값이며 DEM·stereo·LiDAR 또는 위성 추정 고도가 아님 |

Committed 결과의 빠른 hash·재생성 검사는 다음 전용 verifier로 실행합니다.

```bash
python -m research.forest_xai.scripts.verify_reconstruction
```

GAN CPU 학습까지 반복하는 full audit은 verifier의 `--retrain` 옵션을 사용합니다.
개별 명령과 정확한 schema, checkpoint, JVP, 2.5D 제한은
[`RECONSTRUCTION_CARD.md`](../research/forest_xai/RECONSTRUCTION_CARD.md)를
기준으로 합니다. 기존 합성 before/after 경로의 encoder/generator는 GAN이 아니며,
이번 tiny GAN 재구성과도 별도입니다.

## Core의 실제 Sentinel/Landsat opt-in 경계

`public_data_opt_in_manifest.json`에는 현재 공식 문서에서 확인한 discovery endpoint와 이용조건 링크만 있습니다.

- Copernicus Data Space Ecosystem의 [Sentinel-2 Level-2A STAC 문서](https://documentation.dataspace.copernicus.eu/APIs/STAC.html)와 [이용조건](https://dataspace.copernicus.eu/terms-and-conditions)
- USGS의 [Landsat STAC 문서](https://www.usgs.gov/landsat-missions/spatiotemporal-asset-catalog-stac)와 [public-domain 안내](https://www.usgs.gov/faqs/are-landsat-data-cloud-still-considered-be-within-public-domain)

이 metadata는 downloader가 아닙니다. 기본 runtime은 URL을 열지 않으며, credential·remote item·GeoTIFF/JP2/NetCDF도 저장소에 없습니다. 실제 장면을 쓰는 후속 작업은 사용자가 명시적으로 opt-in한 별도 adapter에서 다음 기록을 먼저 고정해야 합니다.

1. Provider, immutable scene ID, AOI, acquisition window
2. 당시 적용되는 terms/license와 source acknowledgement
3. Asset URL, download timestamp, byte SHA-256
4. Red/NIR scale·offset과 QA bit/class 해석
5. CRS, geotransform, resampling, co-registration, compositing 결정
6. Reference 작성자·방법·라이선스와 spatial split

다운로드한 raster와 credential은 untracked 상태로 유지합니다. 공개 제안이 필요하면 사용권을 다시 검토하고 scene manifest, hash, aggregate evidence, 실패 사례만 별도 검토해야 합니다.

## 남은 한계

- Core에 Sentinel-2/Landsat asset adapter와 실제 raster I/O가 없습니다.
- 대기보정 품질, cloud/shadow mask 오류, saturation, terrain shadow를 평가하지 않습니다.
- 다른 해상도의 band 정합, resampling kernel, sub-pixel registration을 구현하지 않습니다.
- 계절 label은 manifest 선언이며 phenology나 장기 composite로 검증하지 않습니다.
- UTM allowlist 하나만 다루며 EPSG registry 또는 geoid/epoch를 검증하지 않습니다.
- GeoJSON WGS84 reprojection과 geodesic area를 제공하지 않습니다.
- Core reference는 팀 작성 합성 mask이며 독립 annotator·현장조사·공인 land-cover 제품이 아닙니다.
- 4×6 fixture는 correctness 회귀용이며 memory, streaming, COG window read, 대규모 tiling 성능을 증명하지 않습니다.
- 공개 CNN은 4 scene·36 chip에 한정되며 external·seasonal·geographic validation이 없습니다.
- Grad-CAM은 모델 민감도이지 산림 변화 원인 또는 metric 개선의 증거가 아닙니다.
- 실제 before/after scene pair·change label을 쓰는 bi-temporal 평가가 없습니다.
- 수상 후 tiny GAN은 small capability reconstruction이며 생성 품질·일반화 평가가 없습니다.
- 2.5D drape의 높이는 합성이며 실제 DEM 또는 위성에서 추정한 고도가 아닙니다.
- NDVI threshold·CNN·XAI 어느 경로도 EUDR 규정 준수 판정이 아닙니다.
- 발표의 `83.4% → 96.2%`를 같은 데이터·task·split으로 재현하는 코드와 가중치가 없습니다.
- 특정 HiGAN/HIGAN 구현·논문 버전·학습 계약이 없으며 synthetic JVP나 수상 후 tiny GAN과 동일하지 않습니다.
- 고도 자료·다중시점·다시점 기하가 없으므로 위성→3D reconstruction을 구현하지 않습니다. 합성 높이장 drape는 2.5D 시각화일 뿐입니다.

실제 **산림변화** benchmark라는 주장은 공개 scene pair, 재배포 권한,
독립 change reference, spatially separated evaluation, cloud·seasonality·registration
error analysis가 함께 검토된 뒤에만 가능합니다. 3D가 필요하다면 라이선스가
명확한 DEM을 별도 입력으로 고정하고 분류·heatmap을 drape한 **2.5D 시각화**로
범위를 명시해야 하며, 위성 영상 자체에서 3D를 복원했다고 주장하면 안 됩니다.
