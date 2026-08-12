# 산림 geospatial plumbing benchmark

이 벤치마크는 실제 위성 모델의 정확도를 주장하지 않습니다. 작은 합성 raster contract를 이용해 산림 변화 코드 앞뒤에서 자주 깨지는 좌표·마스크·시간·공간 분할 경계를 제3자가 반복 검증하도록 만든 기술 기준선입니다.

## 증명 범위

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

이 검증은 CRS registry 조회, raster reprojection, 영상 co-registration 또는 학습 모델을 구현하지 않습니다. `EPSG:32652` 의미는 작은 offline allowlist로 고정하며 결과에도 `registry_lookup_performed: false`를 남깁니다.

## 공개 fixture

| 파일 | 성격 |
|---|---|
| `data/benchmarks/forest/synthetic_geospatial_case.json` | 실행 manifest와 주장 경계 |
| `data/benchmarks/forest/benchmark.schema.json` | Draft 2020-12 machine-readable shape contract |
| `data/benchmarks/forest/synthetic_scene_pixels.csv` | 4×6 합성 red/NIR·QA 입력 |
| `data/benchmarks/forest/synthetic_reference_mask.csv` | 입력 band와 분리된 합성 binary reference |
| `data/benchmarks/forest/expected_summary.json` | 결정론적 golden summary |
| `data/benchmarks/forest/expected_cells.geojson` | 24개 셀의 결정론적 golden polygon 출력 |
| `data/benchmarks/forest/public_data_opt_in_manifest.json` | 실제 공개 위성 자료의 공식 discovery·terms metadata만 기록 |

커밋된 scene ID, reflectance, QA, 좌표와 reference는 모두 팀 작성 합성값입니다. UTM 좌표는 geometry 연산을 시험하기 위한 값이며 특정 기업·농장·현장을 나타내지 않습니다. Reference도 독립 현장조사가 아니므로 manifest와 summary에 `independent_ground_truth: false`를 명시합니다.

## 재현 명령

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

## 실제 Sentinel/Landsat opt-in 경계

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

- Sentinel-2/Landsat asset adapter와 실제 raster I/O가 없습니다.
- 대기보정 품질, cloud/shadow mask 오류, saturation, terrain shadow를 평가하지 않습니다.
- 다른 해상도의 band 정합, resampling kernel, sub-pixel registration을 구현하지 않습니다.
- 계절 label은 manifest 선언이며 phenology나 장기 composite로 검증하지 않습니다.
- UTM allowlist 하나만 다루며 EPSG registry 또는 geoid/epoch를 검증하지 않습니다.
- GeoJSON WGS84 reprojection과 geodesic area를 제공하지 않습니다.
- Reference는 팀 작성 합성 mask이며 독립 annotator·현장조사·공인 land-cover 제품이 아닙니다.
- 4×6 fixture는 correctness 회귀용이며 memory, streaming, COG window read, 대규모 tiling 성능을 증명하지 않습니다.
- NDVI threshold baseline은 CNN/XAI 또는 EUDR 규정 준수 판정이 아닙니다.

실제 remote-sensing benchmark라는 주장은 공개 scene pair, 재배포 권한, 독립 reference, spatially separated evaluation, cloud·seasonality·registration error analysis가 함께 검토된 뒤에만 가능합니다.
