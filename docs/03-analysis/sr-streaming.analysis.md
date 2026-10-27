# PoC Analysis: sr-streaming — SR 게이트 판정

**Feature**: sr-streaming (3d-ai-performance Track B)
**Phase**: Check (PoC 게이트)
**Date**: 2026-06-11
**판정**: ⛔ **SR 단계 보류** — 게이트 수치는 통과하나 bicubic 대비 우위 입증 실패

---

## 측정 방법

- 표본: **운영 데이터** CT/MR 12슬라이스 (CT 10, MR 2 — 각 study 최대 시리즈의 중간 슬라이스)
- 경로: WADO-RS `/rendered`(8-bit, 표시 보조 용도와 동일) → ×0.5 다운스케일(점진 표시의
  "저해상도 우선" 페이로드 시뮬레이션) → ×2 복원 3종 비교 → 원본 대비 SSIM/PSNR
- 모델: bicubic(베이스라인) / FSRCNN ×2 / EDSR ×2 (OpenCV dnn_superres)
- 지연: CPU(Apple Silicon) 측정 — GPU(RTX 5080) 환산 시 EDSR ~30–100ms 추정

## 결과 (n=12 평균)

| 방법 | SSIM | PSNR(dB) | 지연(CPU) |
|------|:----:|:--------:|:---------:|
| bicubic | **0.9784** | 39.46 | **0.16ms** |
| FSRCNN ×2 | 0.9746 ⬇ | 40.03 | 21ms |
| EDSR ×2 | 0.9832 | 40.98 | 3,130ms |

게이트 기준 대비:
- SSIM ≥ 0.92: **3종 모두 통과** — 단, **bicubic조차 0.978**로 기준을 크게 상회
- 지연 ≤ 100ms(GPU): EDSR GPU 환산 시 통과 가능성 높음 (CPU 3.1s)

## 판정 근거

1. **bicubic 대비 우위가 사실상 없음** — EDSR의 이득은 SSIM +0.0048, PSNR +1.5dB.
   FSRCNN은 SSIM에서 bicubic보다 **나쁨**(0.9746 < 0.9784)
2. SR 왕복 비용(브라우저→백엔드→AI서버 GPU→백엔드→브라우저, 모델 탑재·운영 복잡도)이
   +0.005 SSIM을 정당화하지 못함 — bicubic은 클라이언트에서 0.2ms, 외부 의존 0
3. CT/MR은 평활(smooth) 영상이라 보간 손실 자체가 작음 — 모체 Plan의 리스크
   ("흉부 CT 등 평활 영상에서 SR 우위 없음 흔함")가 그대로 실증됨
4. 모체 설계 §1 결정 4의 미달 조항 적용: **"미달 시 점진 표시만 출시 또는 보류"**

## 결론 및 후속 옵션

**SR 단계(AI 서버 모델 탑재 + SR 프록시) 보류.** 데이터가 투자 가치를 부정한다.

남은 선택지 (모체 설계 단계 5):
- **(A) 저해상도 점진 표시 단독** — bicubic 기반 lowres-first(SSIM 0.978이면 프리뷰로 충분),
  뷰어 점진 로더 + 측정 잠금 구현. 단, Track A 프리페치 적중 시 효과 중복 — 콜드 오픈/원격
  환경에서만 가치. 뷰어 심부 수정 리스크 대비 가치 평가 필요
- **(B) 보류 후 재평가** — Track A 적중률 데이터(1~2주) 확인 후, 콜드 오픈 비중이 크면 (A) 착수

권고: **(B)** — 프리페치 적중률이 높으면 점진 표시의 잔여 가치가 작다. stats 데이터로 결정하는
것이 Track A와 같은 데이터 기반 의사결정 노선과 일치한다.

## 원시 데이터

`scripts/sr_poc_results_20260611.json` (12행, 슬라이스별 SSIM/PSNR/지연).
PoC 하니스: `scripts/sr_poc.py` — WADO-RS 실데이터 fetch → bicubic/FSRCNN/EDSR 복원 비교.
재실행: venv에 `numpy pillow opencv-contrib-python scikit-image httpx` 설치 +
FSRCNN_x2.pb/EDSR_x2.pb(Saafke GitHub) 다운로드 후 실행.
