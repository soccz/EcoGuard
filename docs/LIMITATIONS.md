# 한계와 다음 검증

## 이 공개본이 증명하지 않는 것

### 대회 당시 운영 백엔드가 아니다

공개 코드는 발표의 기술 논지를 검증 가능하게 다시 만든 v0.4 baseline입니다. 대회 당시 OCR·Legal RAG·산림 모델 전체 코드의 복원본이나 실제 은행 시스템이 아닙니다.

### 모든 사례 데이터는 합성이다

기업, 거래, 문서, 설비, 좌표, 배출집약도, 가격과 reference mask는 시연용 합성 사례입니다. 실제 기업 성능, 은행 연동, 통관 결과 또는 위성 현장을 뜻하지 않습니다. 법령 URL만 공식 EUR-Lex를 가리키며 한국어 요약은 팀 작성 비공식 metadata입니다.

### OCR vision model은 포함하지 않는다

입력은 OCR 직후의 line payload를 시뮬레이션합니다. 공개본은 extraction boundary, alias mapping, unit normalization, source lineage, candidate selection, conflict detection을 검증합니다. 스캔 품질별 character/field recognition accuracy는 측정하지 않습니다.

### 법률 retrieval 평가는 작고 닫혀 있다

8개 article record와 34개 team-authored query로 구성한 회귀 fixture입니다. `Recall@3=1.0`과 negative abstention 1.0은 이 파일의 회귀 결과일 뿐, 모든 EU 법률·언어·개정·질문에 대한 일반화 성능이 아닙니다.

Paragraph는 각 article record의 metadata 범위입니다. Paragraph별 공식 원문 chunk를 검색하는 시스템이 아니므로 “몇 항을 언제나 정확히 찾는다”고 주장하지 않습니다. LLM answer generation, citation faithfulness, legal conclusion correctness도 평가하지 않습니다.

### CBAM은 기술 인벤토리 가격 민감도다

직접·간접·전구물질 구성요소와 trace는 합성 산술을 재현합니다. 그러나 구성요소의 법정 포함 여부를 판정하지 않습니다. Implementing Regulation 2025/2547의 전체 계산 규칙, 2025/2620의 free-allocation adjustment, 실제 certificate price, Article 9의 실제 납부·rebate·통화환산·독립 확인, 면제와 신고 절차는 구현하지 않습니다.

따라서 결과에 `statutory_calculator: false`를 기록하며 exposure를 payable amount나 의무액으로 사용하지 않습니다.

### 산림은 실제 remote-sensing benchmark가 아니다

6×6 합성 reflectance와 team-authored reference mask입니다. 실제 위성 방사·대기 보정, cloud/shadow mask, spatial registration, temporal compositing, land-cover classifier, boundary polygon, 현장 검증, CNN/XAI를 포함하지 않습니다. F1과 IoU는 metric code path를 검증하기 위한 값입니다.

### 보안·운영 통제는 범위 밖이다

공개 baseline은 개인정보, 접근제어, 감사 저장소, key management, bank API, queue/retry, model registry, regulation update workflow를 구현하지 않습니다. 모든 출력은 자동 금융 판단이 아니라 human-review 자료입니다.

## 다음 검증 순서

| 우선순위 | 다음 검증 | 완료 조건 |
|---|---|---|
| 1 | OCR adapter benchmark | 라이선스가 명확한 공개 scan set, field-level precision/recall, 실패 사례와 비용 공개 |
| 2 | Document schema expansion | 표 병합, 다국어, 중복 revision, 서명·발행시각·문서 우선순위 테스트 |
| 3 | Legal corpus expansion | 공식 원문 paragraph chunk, amendment/version test, 더 큰 blind query set, citation faithfulness 평가 |
| 4 | CBAM methodology review | 공식 입력 source manifest, 규제범위 decision table, 2025/2547·2620 rule coverage와 전문가 검토 기록 |
| 5 | Remote-sensing benchmark | 라이선스가 명확한 public tile, spatial split, reference provenance, cloud/seasonality error analysis |
| 6 | Operational controls | 개인정보·권한·감사로그·재처리·규정 버전·human override 검증 |

실제 파일럿을 주장하려면 입력 사용권, 익명화, 평가 설계, 실패 기준, 법무·규제 검토와 책임 경계를 먼저 문서화해야 합니다.
