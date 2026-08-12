# Legal retrieval blind-style holdout

EcoGuard에는 개발 중 사용한 `data/reference/legal_eval.json`과 분리된 [`data/benchmarks/legal_blind.json`](../data/benchmarks/legal_blind.json)이 있습니다. 새 fixture는 문장 재사용, contrast 구분, hard negative 기권을 별도로 확인합니다.

이름의 **blind-style**은 저장 위치와 질문 집합을 개발 fixture에서 분리했다는 뜻입니다. 외부 평가자가 작성한 진짜 blind test는 아닙니다. 저장소 maintainer가 작성하고 초기 점수도 확인했으므로 독립적인 외부 타당성이나 법률 정확도의 증거로 해석하면 안 됩니다.

## 두 평가셋의 역할

| 구분 | 개발 fixture | blind-style holdout |
|---|---:|---:|
| 경로 | `data/reference/legal_eval.json` | `data/benchmarks/legal_blind.json` |
| positive | 16 | 16 |
| distractor | 8 | 8 |
| negative | 10 | 12 |
| 총 문항 | 34 | 36 |
| 목적 | retriever 개발·기본 회귀 | 별도 paraphrase·contrast·negative 회귀 |
| 외부 작성 | 아니오 | 아니오 |

두 fixture의 ID와 정규화 query는 겹치지 않습니다. holdout은 현재 corpus의 8개 article record만 평가합니다.

## 누수 방어

`ecoguard.regulatory.validate_blind_fixture`는 다음을 자동 확인합니다.

- corpus SHA-256이 고정값과 같은지
- 개발 fixture SHA-256이 고정값과 같고 schema-valid한 non-empty 평가셋인지
- 개발 fixture의 query를 그대로 재사용하지 않았는지
- case ID와 query가 중복되지 않는지
- corpus의 title, 한국어 summary, keyword, concept alias 중 12자 이상의 정규화 문구를 query에 그대로 넣지 않았는지
- positive, distractor, negative가 모두 있고 선언한 개수와 일치하는지
- `external_blind`가 반드시 `false`인지
- expected ID·instrument·status가 현재 corpus 안에서 유효한지
- 실제 retrieval decision이 각 문항의 expected status와 일치하는지

짧은 법률 용어까지 금지하지는 않습니다. 예를 들어 `CBAM`, `EUDR`, `실사`, `검증인`, `위험 평가`는 article을 식별하는 핵심 도메인 단어이므로 사용할 수 있습니다. 이 정책은 장문 복사를 막는 기계적 기준이지 의미적 독립성을 보증하지 않습니다.

## 문항 구성

- positive 16개: 각 article마다 개발 query와 다른 한국어 표현 2개
- distractor 8개: 이웃 개념을 함께 제시하되 정답 article과 피해야 할 article을 분리
- negative 12개: 인증서·탄소가격·좌표·위험·검증 같은 단어가 있어도 법률 citation을 요구하지 않는 UI, 디자인, 모델 튜닝, 글쓰기 질문과 완전한 범위 밖 질문

negative는 단순 무관 질문만 모은 것이 아닙니다. 법률 corpus와 어휘가 겹쳐도 citation 요청이 아니라면 기권하는지를 확인합니다.

## 고정 baseline

2026-08-12에 현재 8개 article corpus와 `legal-bm25f-v2.1`, `k=3`으로 확인한 결과입니다.

| 지표 | 값 |
|---|---:|
| Recall@3 | 1.0000 |
| MRR | 1.0000 |
| positive coverage | 1.0000 |
| negative abstention rate | 1.0000 |
| false support rate | 0.0000 |
| distractor rejection@1 | 1.0000 |
| instrument leakage@3 | 0.0000 |
| score trace coverage | 1.0000 |
| expected status match rate | 1.0000 |

이 수치는 작고 maintainer가 작성한 고정셋에서의 회귀 결과입니다. 다음을 의미하지 않습니다.

- CBAM 또는 EUDR 전체 법률 coverage
- 새로운 법령 버전에서의 성능
- 실제 사용자 traffic에서의 정확도
- 생성 답변의 citation faithfulness
- 법률 해석의 정확성 또는 법률 자문 품질
- 외부 evaluator가 수행한 blind benchmark

## 재현

coverage matrix와 holdout을 함께 검증하고 JSON summary를 출력합니다.

```bash
PYTHONPATH=src python -m ecoguard.regulatory
```

새 검증만 실행하려면 다음 명령을 사용합니다.

```bash
PYTHONPATH=src python -m unittest discover \
  -s tests \
  -p 'test_regulatory_coverage.py' \
  -v
```

검증기는 fixture 구조와 누수를 먼저 확인한 다음 기존 dependency-free retriever로 점수를 계산합니다. threshold를 통과해도 결과는 article-level retrieval 기준선일 뿐이며 답변 생성이나 법률 판단 단계는 없습니다.

## 다음 외부 검증

독립성을 높이려면 현재 개발자에게 보이지 않은 질문을 CBAM·EUDR 전문가가 별도로 작성하고, 법령 버전과 판정 지침을 먼저 고정한 뒤 sealed evaluation으로 실행해야 합니다. 최소한 다음 층을 분리해야 합니다.

1. 질문 작성자와 retriever 개발자
2. article relevance 판정자와 system 운영자
3. retrieval hit와 citation 내용 정확성
4. 단순 기권과 위험한 오인용
5. 법령 개정 전·후 corpus

그 평가가 끝나기 전까지 이 저장소는 `external_blind: false`를 유지합니다.
