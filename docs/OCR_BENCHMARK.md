# OCR 출력 어댑터와 필드 벤치마크

## 범위

EcoGuard는 OCR 모델을 구현하거나 소유한다고 주장하지 않는다. 이 모듈은
외부 도구가 로컬에서 만든 출력물을 기존 ingestion 계약으로 변환하고,
설정된 field alias가 추출한 원시 값을 사람이 만든 정답과 비교한다.

```text
외부 OCR 또는 text extractor
  -> Tesseract TSV / generic JSON / pdftotext text
  -> ecoguard.ocr_adapter
  -> ocr-document-bundle/1.0
  -> ecoguard.ingestion
  -> exact field precision / recall / F1 + error breakdown
```

어댑터는 Python 표준 라이브러리만 사용한다. 네트워크 요청, PDF 렌더링,
OCR 실행, 이미지 보정, 표 구조 인식은 하지 않는다. 따라서 이 결과만으로
스캔 PDF 인식률, 특정 OCR 제품 성능 또는 운영 문서 정확도를 주장할 수 없다.

## 지원 입력

### Tesseract-compatible TSV

`tesseract --psm ... tsv`처럼 `level`, `page_num`, `block_num`, `par_num`,
`line_num`, `word_num`, `left`, `top`, `width`, `height`, `conf`, `text` 열이 있는 TSV를 받는다. `level=5`의
비어 있지 않은 word만 사용한다.

- word는 page/block/paragraph/line 좌표로 묶는다.
- line text는 `word_num` 순서로 공백을 넣어 결합한다.
- line confidence는 word confidence의 산술평균이다.
- block마다 다시 시작할 수 있는 Tesseract line 번호는 page-local 순번으로
  다시 부여한다.
- 중복 논리 word 좌표, 음수 `left/top`, 0 이하 `width/height`, `[0, 100]` 밖 confidence는 거절한다. Pixel bounding box 자체는 출력 bundle에 보존하지 않는다.

Tesseract 실행은 사용자가 별도로 수행해야 한다. EcoGuard는 실행파일을
다운로드하거나 subprocess로 호출하지 않는다.

### Provider-neutral JSON

중첩형은 다음 최소 계약을 사용한다.

```json
{
  "pages": [
    {
      "page": 1,
      "lines": [
        {"line": 1, "text": "NET WT : 190 MT", "confidence": 0.98}
      ]
    }
  ]
}
```

flat list 또는 `{"lines": [...]}`도 가능하다.

```json
[
  {"page": 1, "line": 1, "text": "NET WT : 190 MT", "confidence": 98}
]
```

`page`와 `line`을 생략하면 입력 순서에 따라 1부터 부여한다. confidence가
없으면 기본값은 `0.0`이며, `--confidence-scale percent`를 지정한 경우에만
입력 confidence를 `[0, 100]`으로 해석한다. vendor별 중첩 응답 전체를
추측해서 해석하지 않으므로, AWS/Azure/Google 등의 응답은 이 작은 계약으로
명시적으로 매핑해야 한다. layout·bounding-box 같은 추가 키는 보존하지 않는다.

### pdftotext plain text

form feed(`\f`)를 page 경계로, non-blank line을 line 경계로 사용한다.
`pdftotext`는 confidence를 제공하지 않으므로 기본 confidence는 `0.0`이다.
사용자가 `--default-confidence`를 바꿀 수 있지만, 그 값은 측정된 OCR
confidence가 아니라는 점을 결과 해석에 남겨야 한다. 또한 text-layer
추출은 이미지 OCR과 동일하지 않다.

## 재현 가능한 합성 benchmark

저장소 root에서 다음을 실행한다.

```bash
PYTHONPATH=src python3 scripts/benchmark_ocr.py
```

기본 입력은 다음 두 합성 파일이다.

- `data/benchmarks/ocr/synthetic_tesseract.tsv`
- `data/benchmarks/ocr/synthetic_field_reference.json`

정답 field identity는 `(document, label, occurrence)`이고, 같은 label이 한
문서에서 반복되면 읽기 순서에 따라 occurrence가 증가한다. 값 비교는 Unicode
NFC와 연속 whitespace 정리만 적용하며 대소문자, 숫자, 단위, 구두점은
자동 보정하지 않는다.

의도된 결과는 다음과 같다.

```text
expected fields       4
predicted fields      4
true positive         2
false positive        2
false negative        2
precision / recall    0.5 / 0.5
F1                    0.5
value mismatch        1
missing               1
spurious              1
```

wrong value는 같은 field를 찾았더라도 exact field extraction 성공이 아니다.
따라서 value mismatch 1건은 FP 1건과 FN 1건을 동시에 만든다. 이 합성
점수는 오류 집계 코드의 회귀 fixture이며 OCR 모델 성능 수치가 아니다.
prediction이 0건이라 precision 분모가 없는 경우처럼 정의되지 않는 metric은
완벽한 점수로 채우지 않고 JSON `null`로 기록한다. Reference는 provenance가
있는 non-empty field 목록이어야 한다.

직접 만든 로컬 파일은 다음처럼 평가할 수 있다.

```bash
PYTHONPATH=src python3 scripts/benchmark_ocr.py \
  --input /path/to/local-output.tsv \
  --format tesseract-tsv \
  --reference /path/to/local-field-reference.json \
  --document-id local-document \
  --document-type commercial_invoice \
  --language ko-en
```

기본 committed fixture를 실행한 결과만
`classification=team_authored_synthetic_error_fixture`로 표시한다. 사용자 지정
`--input` 또는 `--reference`를 넣으면 결과는
`caller_supplied_reference_unverified`로 표시되며, EcoGuard가 OCR engine을
호출했다거나 정답의 출처를 검증했다는 뜻이 아니다.

정답 JSON은 다음 형식이다.

```json
{
  "schema_version": "ocr-field-reference/1.0",
  "case_id": "local-case",
  "notice": "Caller-authored reference; provenance and review status are recorded separately.",
  "fields": [
    {
      "document": "local-document",
      "label": "NET WT",
      "occurrence": 1,
      "value": "190 MT"
    }
  ]
}
```

`case_id`와 `document`가 adapter 실행 인자와 일치해야 한다. reference의
중복 identity는 조용히 덮어쓰지 않고 오류로 처리한다.

## 실제 공개 자료로 확장할 때의 계약

committed public input은 계속 합성으로 유지한다. 공개·공식 PDF를 평가할
경우 파일을 사용자가 명시적으로 내려받아 로컬 경로로 전달하고, 결과 보고서에
최소한 다음을 별도 기록해야 한다.

- 원문 공식 URL과 라이선스 또는 재사용 근거
- 내려받은 원문 byte SHA-256과 확인 날짜
- OCR engine 이름·정확한 버전·언어팩·page segmentation 설정
- PDF renderer와 해상도, 전처리 설정
- 정답 작성자, 이중 검수 여부, blind 평가 분리 방식
- 문서·field 유형별 표본 수와 confidence/error 관계

향후 downloader를 추가한다면 main runtime이나 reproduction에 넣지 않는다.
고정 URL·expected SHA-256·license를 가진 manifest와 별도 opt-in script로만
구성하고, hash가 다르면 평가 전에 중단해야 한다. 현재 저장소는 어떤 외부
benchmark 파일도 자동 다운로드하지 않는다.

## 해석 한계

- alias가 구성되지 않은 field는 OCR이 정확해도 추출되지 않는다.
- line grouping이 달라지면 alias extraction 결과도 달라질 수 있다.
- 원시 값 exact score는 후속 단위 정규화 성능과 다른 지표다.
- 합성 fixture는 실제 폰트, blur, skew, table, handwriting, 다국어 OCR을
  대표하지 않는다.
- confidence 평균은 engine calibration 검증이 아니다. `correct_mean`과
  `incorrect_prediction_mean`은 진단값일 뿐 표본이 작으면 일반화할 수 없다.
