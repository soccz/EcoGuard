# Synthetic fixtures

이 디렉터리의 기업·문서·식별자·좌표·수치는 전부 팀이 만든 합성 데이터입니다. 실제 기업 파일이나 대회 비공개 자료를 포함하지 않습니다.

## Trade case

`trade_case_documents.json`은 이미지 OCR이 끝난 직후의 line-oriented payload를 재현합니다. 7개 문서, 37개 OCR line, line confidence를 포함하며 다음 이상값을 의도적으로 넣었습니다.

| 증거 | 의도 |
|---|---|
| Invoice `190,000 kg` / Packing list `190 MT` | 서로 다른 단위의 동일값 정규화 |
| Operator memo `약 191톤?` | 낮은 권위의 수기 메모와 확정 문서 충돌 |
| Sheet `5.849263` / memo `5.85` | 허용오차 안의 반올림 변형 |
| `검증서 번호 : [blank]` | 필수 증빙 누락 |
| “배출계수 : 배분근거 미첨부” | label은 있으나 숫자가 없는 line의 parse failure |
| M5·M12 component intensity | 공정/전구물질 × 직접/간접 축의 산식 대사 |
| 전기·LNG 사용량 | 배출계수·배분근거가 없을 때 계산하지 않는 경계 |

`ingestion.py`는 label 뒤의 원문을 후보로 추출하면서 document/page/line/character span과 SHA-256을 보존합니다. `preprocessing.py`는 `data/reference/normalization_policy.json`을 이용해 후보를 선택하되 다른 후보를 삭제하지 않습니다.

## Forest case

산림 파일은 실제 위성 타일이 아니라 red/NIR band와 reference mask를 직접 만든 합성 격자입니다. 지표는 모델 성능 주장이 아니라 threshold·mask·metric 구현을 검증하는 회귀 fixture입니다.

## Safety boundary

- 실제 인물, 기업, 계좌, 세관 신고, 은행 시스템 식별자를 넣지 않습니다.
- fixture 결과를 실제 CBAM 의무액이나 EUDR 적합성 판정으로 사용하지 않습니다.
- 공개 재현에 필요한 최소 데이터만 유지하며 대회 전체 발표자료와 Live Demo 주소는 포함하지 않습니다.
