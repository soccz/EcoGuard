# GAN latent와 2.5D 수상 후 재구성 카드

## 이 artifact의 정체

대회 발표에서는 GAN 계열 잠재공간 보간과 z축/현장형 시각화를 산림 파트에
적용하는 방향을 시도했습니다. 그러나 저장소와 팀 보관 자료 전수조사에서 당시
GAN 학습·추론 코드, notebook, checkpoint 또는 같은 결과를 다시 만들 수 있는
생성 artifact를 찾지 못했습니다.

이 디렉터리의 구현은 그 공백을 당시 성과처럼 채우지 않습니다. 공개
Sentinel-2 derivative fixture와 공개된 forest-cover CNN을 사용해 두 아이디어의
기계적 핵심을 **수상 후 새로 작성하고 검증한 개념 재구성**입니다. 모든 JSON은
`post_award_reconstruction`, `not_a_higan_reproduction`,
`not_evidence_of_presentation_metrics`, `not_photorealistic` 경계를 고정합니다.

## Latent GAN 계약

| 항목 | 고정값 |
|---|---|
| 학습 입력 | public train split, 24개 B4/B3/B2/B8 `[4,64,64]` chip |
| Generator | 16차원 latent → nearest-neighbor upsampling + convolution 4-band `[4,64,64]` output |
| Critic | 4-band chip → real/fake logit |
| 총 parameter | 53,749 |
| 학습 | CPU, seed `20260812`, 120 epochs, batch 12, Adam lr `0.0002` |
| 고정 loss | critic `0.775737`, generator `1.622545` |
| Tensor-state SHA-256 | `a29396193ec04c6c75d9dd165fc1a1988eb84b3169dabbabd2b70e477414c828` |
| Checkpoint file SHA-256 | `3f1ba332dc8cd43445008fac715c30a77818c3640a75b2659e1ebc7417006332` |

Checkpoint file hash는
[`latent_gan.pt.metadata.json`](artifacts/public_demo/reconstruction/latent_gan.pt.metadata.json)을
정본으로 합니다. Loader는 sidecar의 file SHA-256을 먼저 확인하고
`torch.load(..., weights_only=True)`를 사용한 뒤 embedded metadata와 tensor-state
hash를 다시 대조합니다. 이 경로는 hash-pinned committed checkpoint용이며 임의의
외부 checkpoint를 안전한 입력으로 받아들이는 일반 loader가 아닙니다.

이 GAN은 공개 derivative pixel을 학습 입력으로 사용하지만 작은 capability
reconstruction일 뿐입니다. FID/KID, 외부 holdout, 인간 평가, 생태학적 평가 또는
photorealism 검증이 없습니다. 특정 HiGAN 논문·architecture·loss·checkpoint의
재현도 아닙니다.

## Latent interpolation과 JVP

고정 seed에서 `z0`, `z1`을 만들고 8개 alpha로 선형 보간합니다. Generator의
각 frame을 committed single-date forest-cover CNN에 넣어 mean forest
probability를 기록합니다. Latent path length는 `4.24485588`이며,
`location_alpha=0.5`에서 `z1-z0`의 단위 방향에 대한 forest-score
Jacobian-vector product `0.01209233`을 정확히 계산합니다. JSON은
`unit_direction_norm=1`과 `unit_path_direction_derivative`를 함께 기록해 전체
endpoint displacement의 미분과 혼동하지 않게 합니다.

Committed JSON에는 다음이 함께 binding됩니다.

- GAN·classifier checkpoint SHA-256
- alpha 8개와 forest probability 8개
- unit latent direction의 midpoint JVP
- `files.contact_sheet`에 binding한 4×2, 1048×520 contact-sheet PNG path와
  SHA-256
- post-award/not-HiGAN/not-photorealistic claim boundary

한 latent segment의 확률 곡선과 한 지점의 방향미분은 경로가 실행됨을 보여 줄
뿐입니다. 방향이 의미론적인 산림 요인이라는 것, 인과 counterfactual이라는 것,
생성 장면이 실제 관측이라는 것을 증명하지 않습니다.

![Eight-frame latent interpolation contact sheet](artifacts/public_demo/reconstruction/latent_interpolation.png)

## 합성 높이 2.5D drape 계약

Evaluation sample `S2-EV-003`의 RGB와 committed CNN forest probability를
결정론적 합성 높이장 위에 drape합니다. 높이장은 seed `20260812`에서 만든 8×8
coarse noise를 3×3 average pool(stride 1, padding 1)로 한 번 평활화한 뒤, x/y
격자에서 64×64로 bilinear height interpolation(`align_corners=true`)하고 min-max
정규화한 값입니다.
`height_grid_size=8`, `vertical_scale=1.0`인
preview PNG와 JSON은 input checkpoint, evaluation fixture, sample ID, seed,
grid·height scale, mean probability, claim boundary와 output SHA를 기록합니다.
JSON은 다음 기계 판독 artifact도 hash·shape·dtype에 binding합니다.

- `terrain_height.npy`: `[64,64]` float32 합성 높이
- `terrain_probability.npy`: `[64,64]` float32 모델 확률
- `terrain_vertices.npy`: `[33,33,3]` float32, 1,089 vertex
- `terrain_faces.npy`: `[1024,4]` int32, 1,024 quad face

![2.5D drape over synthetic height](artifacts/public_demo/reconstruction/terrain_drape.png)

이 높이는 Sentinel-2 band, Grad-CAM, DEM, stereo, LiDAR, photogrammetry에서
추정한 것이 아닙니다. 따라서 결과를 위성→3D reconstruction, digital twin,
실제 지형 또는 지형 정확도 증거로 부르면 안 됩니다. 정확한 표현은
**“공개 RGB·모델 확률을 합성 bilinear height field에 얹은 2.5D drape”**입니다.

## 실행과 검증

```bash
python -m pip install \
  --index-url https://download.pytorch.org/whl/cpu \
  "torch==2.13.0"
python -m pip install -r research/forest_xai/requirements.txt
python -m research.forest_xai.scripts.verify_reconstruction
```

Verifier는 committed checkpoint·sidecar·JSON·PNG·NPY의 hash와
machine-readable claim boundary를 검사하고 latent interpolation/JVP와 2.5D
drape·mesh arrays를 임시 디렉터리에 재생성해 대조합니다. Committed PNG 자체의
SHA-256은 정확히 고정하되, CPU kernel에 따른 마지막 반올림·압축 byte 차이를
실패로 오인하지 않도록 재생성 contact sheet는 decode한 RGB channel의 최대 오차를
2/255로 제한합니다. Probability curve와 JVP, committed 2.5D file SHA는 exact
계약을 유지합니다. 재생성한 float32 height·probability·vertex는 CPU backend
차이를 고려해 절대오차 `1e-6` 이내로, integer face index는 exact하게 비교합니다.
120-epoch CPU 학습까지 반복하려면 다음을 실행합니다.

```bash
python -m research.forest_xai.scripts.verify_reconstruction --retrain
```

PyTorch checkpoint container byte는 tensor가 같아도 달라질 수 있으므로 full
audit은 각 checkpoint file을 각 sidecar SHA에 대조하고, 재학습 동일성은
tensor-state hash·metadata·exact numeric semantics와 bounded preview replay로
판단합니다.

Full retrain의 기준 환경은 CI와 같은 Ubuntu x86_64·CPython 3.12·
`torch 2.13.0+cpu`입니다. 다른 platform/build에서는 fast verifier를 사용할 수
있지만, 부동소수점 backend와 `torch_version` metadata까지 같은 재학습 동일성을
보장하지 않습니다.

## 주장하지 않는 것

- 대회 당시 동일 코드·가중치가 있었다는 주장
- HiGAN/HIGAN 논문 또는 공개 구현 재현
- 발표의 `83.4% → 96.2%` 재현
- photorealistic satellite generation 또는 생성 품질 우위
- 실제 before/after 산림변화 탐지
- 위성영상에서 고도·기하를 복원한 3D
- 산림훼손 원인·합법성·EUDR 판단 또는 운영 일반화
