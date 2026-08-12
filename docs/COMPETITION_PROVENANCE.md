# Competition work and public reconstruction

이 저장소의 Git history는 대회 당시 비공개 개발 저장소를 공개한 이력이 아닙니다. 수상 이후 공개 가능한 합성 입력과 검증 경계로 **새로 정리한 재현 저장소**이므로, 최근 commit 날짜를 대회 당시 개발 증거로 해석하면 안 됩니다.

## 개발 책임과 팀 결과

- GitHub 소유자 **[@soccz](https://github.com/soccz)**: 대회 당시 CBAM 계산·가격 민감도, 산림 변화 분석, 데이터 처리·검증 핵심 엔진의 단독 개발 책임
- Team UniHana 3인: 문제 정의, 서비스 화면, 발표와 프로젝트 운영을 포함한 공동 출품·공동 수상
- 이 문서는 다른 팀원의 개인 이름·역할 평가를 공개하지 않습니다.

## 무엇이 당시 것이고 무엇이 공개 재구성인가

| 기술 축 | 대회 당시 보관 자료 | 공개 저장소에서 다시 만든 증거 | 동일하다고 주장하지 않는 것 |
|---|---|---|---|
| 문서 처리 | 합성 무역문서 생성기와 발표용 추출 화면 | OCR adapter contract, 원문 span/hash, 단위 정규화, 후보 선택 ledger와 benchmark | 특정 상용 OCR 엔진의 정확도 |
| CBAM | CarbonCast 초기 Python 계산과 EcoGuard 발표 시나리오 | 품목×component DAG, direct/indirect 및 process/precursor 대사, 가격 민감도, provenance 재검증 | 법정 납부액 계산기 또는 EU 신고 인증 |
| 산림 | 위성/XAI 및 현장형 시각화 발표 화면 | 합성 red/NIR 기준선, reference mask 평가, geotransform·cloud/nodata·spatial split 검증 | 대회 화면의 모델·정확도 또는 운영 위성 pipeline |
| 법률 | EU 조문 탐색·응답 흐름 | official identifier binding, citation retrieval, 기권, 고정·blind evaluation | 생성형 법률 답변이나 법률 자문 |

## 비공개 원본의 제한적 확인 가능성

[`competition_archive_attestation.json`](../data/reference/competition_archive_attestation.json)은 팀 보관 자료 3개의 class, byte 수, SHA-256과 공개 구현의 대응 관계만 기록합니다. 원본은 참여자·제3자 권리와 비공개 구현을 보호하기 위해 저장소에 넣지 않습니다.

이 manifest가 입증하는 범위도 제한적입니다.

1. 나중에 통제된 자리에서 제시한 파일이 지금 기록한 byte와 같은지는 SHA-256으로 대조할 수 있습니다.
2. 파일시스템 수정 시각은 참고 metadata일 뿐, 공인 timestamp나 독립적인 저작권 증명은 아닙니다.
3. 개발 책임은 저장소 소유자의 명시적 attestation이며, 상장·외부 보도는 팀의 수상 사실을 별도로 뒷받침합니다.

이 구분은 “수상 뒤에 만든 공개 검증 코드”를 “대회 당시 그대로 운영된 코드”로 과장하지 않으면서, 핵심 기술이 어떤 자료에서 어떤 검증 가능한 구현으로 발전했는지를 남기기 위한 것입니다.
