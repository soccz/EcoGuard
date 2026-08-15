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
| 산림 | 위성/XAI 비교 패널과 pseudo-360 standalone 화면 | Core의 합성 red/NIR·geospatial 기준선; 선택형 공개 Sentinel-2 단일시점 forest-cover CNN·Grad-CAM; 합성 before/after CNN·JVP; 수상 후 tiny-GAN latent·2.5D mechanics 재구성 | 대회 화면의 모델·정확도, 실제 bi-temporal change, 특정 HiGAN, 위성에서 복원한 3D 또는 운영 pipeline |
| 법률 | EU 조문 탐색·응답 흐름 | official identifier binding, citation retrieval, 기권, 고정·blind evaluation | 생성형 법률 답변이나 법률 자문 |

## 비공개 원본의 제한적 확인 가능성

[`competition_archive_attestation.json`](../data/reference/competition_archive_attestation.json)은 팀 보관 자료 5개의 class, byte 수, SHA-256과 공개 구현의 대응 관계만 기록합니다. 여기에는 2026-06 산림 XAI 비교 패널과 2026-07 pseudo-360 standalone 화면도 포함됩니다. 원본은 참여자·제3자 권리와 비공개 구현을 보호하기 위해 저장소에 넣지 않습니다.

이 manifest가 입증하는 범위도 제한적입니다.

1. 나중에 통제된 자리에서 제시한 파일이 지금 기록한 byte와 같은지는 SHA-256으로 대조할 수 있습니다.
2. 파일시스템 수정 시각은 참고 metadata일 뿐, 공인 timestamp나 독립적인 저작권 증명은 아닙니다.
3. 개발 책임은 저장소 소유자의 명시적 attestation이며, 상장·외부 보도는 팀의 수상 사실을 별도로 뒷받침합니다.

이 구분은 “수상 뒤에 만든 공개 검증 코드”를 “대회 당시 그대로 운영된 코드”로 과장하지 않으면서, 핵심 기술이 어떤 자료에서 어떤 검증 가능한 구현으로 발전했는지를 남기기 위한 것입니다.

## 발표 언어와 현재 재현 증거의 경계

발표 자료·대본에 등장한 시연 설명은 당시 프로젝트의 의도와 화면을
설명하는 provenance입니다. 아래 표는 그 문구를 현재 공개 코드의 실험 결과로
바꿔 인용하지 않기 위한 claim boundary입니다.

| 발표 시대 표현 | 현재 공개 증거 | 아직 필요한 동일성 증거 |
|---|---|---|
| `83.4% → 96.2%` | 공개 재현 성공 수치로 사용하지 않음. 현재 0.947917 F1은 서로 다른 단일시점 forest-cover fixture의 값 | 같은 task·dataset version·split·preprocessing·metric·checkpoint·evaluation code |
| HiGAN/HIGAN 활용 | 특정 논문·공개 구현의 재현이 없음. Synthetic local JVP는 명시적으로 `not_a_gan`, `not_a_reproduction` | 정확한 논문·commit·architecture·loss·data·weight·evaluation 계약 |
| Grad-CAM으로 개선 확인 | 현재 Grad-CAM은 한 모델의 국소 민감도 artifact일 뿐 metric 개선을 증명하지 않음 | 동일 데이터·split의 ablation과 부트스트랩 불확실성 |
| 위성 영상의 산림변화 | 공개 실제 위성 경로는 단일시점 forest cover. Before/after 경로는 합성 | 라이선스가 명확한 실제 scene pair, co-registration, 독립 change label, 시공간 holdout |
| 위성→3D | 수상 후 합성 높이 2.5D drape는 구현했지만 위성에서 고도를 복원하는 코드가 없음 | DEM·stereo·LiDAR·photogrammetry 중 적합한 고도 근거, 기하 검증, 정확도 평가 |

### 당시 시도의 기록과 수상 후 재구성

대회 산림 파트에서는 GAN 계열 잠재공간을 따라 장면을 보간하고, 화면의 z축을
활용해 산림 검토 장면을 더 입체적으로 표현하는 방향을 **시도·발표했습니다**.
팀 보관 attestation의 산림 XAI 비교 패널은 그 용어가 들어간 발표 화면이
존재했다는 사실만, pseudo-360 standalone record는 사전 렌더링 파노라마를
둘러보는 현장형 화면이 존재했다는 사실만 고정합니다. 두 hash record 모두 GAN
모델이 실행됐거나 실제 위성 고도가 복원됐다는 증거는 아닙니다.

전수조사에서는 대회 당시 GAN 학습·추론 코드, notebook, checkpoint 또는 동일
결과를 다시 만들 수 있는 생성 artifact를 찾지 못했습니다. 따라서 이 저장소는
그 작업을 당시 구현의 복구본으로 표시하지 않습니다. 대신
`research/forest_xai`에 공개 fixture로 작은 GAN을 새로 학습해 `z0 → z1`
interpolation과 forest-score JVP를 실행하고, 별도의 합성 높이장을 bilinear
보간해 Sentinel-2 RGB와 산림 확률을 drape하는 2.5D 경로를 **수상 후 개념
재구성**으로 둡니다. 입력·checkpoint·출력 hash와 제한은
[`RECONSTRUCTION_CARD.md`](../research/forest_xai/RECONSTRUCTION_CARD.md)에
고정합니다.

이 재구성은 시도의 기술적 메커니즘을 현재 코드로 보여 주지만, 당시 HiGAN
구현·학습 성과, `83.4% → 96.2%`, photorealism, 실제 전후 변화 탐지 또는
위성영상에서의 고도·3D 복원을 소급해 증명하지 않습니다.

선택형 공개 CNN·Grad-CAM은 발표 의도의 한 부분을 제3자가 실행할 수 있게
새로 만든 후속 증거입니다. 대회 당시 모델이나 가중치의 복원본이 아니며,
다른 task의 수치를 이어 붙여 발표 성능을 간접 입증하지 않습니다.
