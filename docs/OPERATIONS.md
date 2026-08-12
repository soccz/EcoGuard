# Local API and production boundary

`ecoguard-api`는 공개 엔진을 다른 프로그램에서 호출해 보는 **로컬 통합 예제**입니다. Python 표준 라이브러리 WSGI만 사용하며, 인증·권한·영구 저장소가 없는 만큼 인터넷에 노출하는 운영 서버가 아닙니다.

## 로컬 실행

```bash
python -m ecoguard.api --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/health
```

정규화된 공개 예제로 CBAM 기술 인벤토리를 계산할 수 있습니다.

```bash
curl -X POST http://127.0.0.1:8765/v1/cbam/calculate \
  -H 'Content-Type: application/json' \
  --data-binary @artifacts/examples/normalized_evidence.json
```

법률 검색은 생성형 답변이 아니라 citation retrieval 결과와 기권 사유를 반환합니다.

```bash
curl -X POST http://127.0.0.1:8765/v1/legal/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query":"CBAM 신고인의 검증 의무는 어느 조문인가?","limit":3}'
```

두 POST 응답 모두 `human_review_required: true`입니다. CBAM 응답의 `statutory_calculator`도 `false`이며, 자동 승인·법률 자문·통관 판정을 의미하지 않습니다.

## 공개 API가 고정한 것

- UTF-8 JSON만 수용하고 중복 key·NaN·Infinity, 빈 body, 알 수 없는 key를 거절
- 요청 body 최대 1 MB, legal query 최대 8,000자
- CBAM endpoint가 CLI와 동일한 provenance·unit·candidate 완전성 검증을 다시 실행
- Legal endpoint가 wheel에 포함된 corpus와 source manifest의 CELEX·ELI binding을 먼저 확인
- 명시적 기권 결과를 HTTP 오류로 바꾸지 않음
- cache 금지와 `nosniff` 응답 header

## 운영으로 가져가려면 필요한 것

| 영역 | 공개 예제 | 운영 전 필수 설계 |
|---|---|---|
| 인증·권한 | 없음, loopback 기본값 | OIDC/mTLS, tenant·role 분리, service account 회전 |
| 개인정보 | 합성 입력만 | field-level 최소수집, 암호화, 보존·삭제 정책, 접근 감사 |
| 원본 문서 | 요청 JSON | object storage, malware 검사, immutable source version, upload quota |
| 법령 버전 | wheel에 고정 | 공식 원문 동기화, 개정 diff, 법무 승인·rollback 기록 |
| 계산 정책 | versioned code/fixture | 승인된 factor registry, effective date, four-eyes policy, override ledger |
| 처리 안정성 | 동기 요청 | idempotency key, queue, retry/dead-letter, timeout·circuit breaker |
| 관측성 | 없음 | trace ID, structured log, latency/error/abstention drift, alert |
| 보안 | body cap만 | reverse proxy, TLS, WAF/rate limit, SAST/SBOM/취약점 대응 |
| 인간 판단 | flag만 반환 | 심사 UI, 근거 drill-down, 보완 요청, 최종 결정·이의제기 기록 |

운영 서비스는 공개 WSGI 예제를 그대로 배포하는 작업이 아니라, 위 경계를 별도 어댑터와 정책 계층으로 구현하는 후속 프로젝트입니다.
