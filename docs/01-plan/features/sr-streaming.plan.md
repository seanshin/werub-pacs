# Plan: sr-streaming — AI 초해상도(SR) 점진적 스트리밍 (3d-ai-performance Track B)

**Feature**: sr-streaming
**Phase**: Check 완료 — **PoC 게이트 판정: SR 보류** (`docs/03-analysis/sr-streaming.analysis.md`)
**Priority**: MEDIUM (PoC 게이트 결과에 따라 조정)
**Start Date**: 2026-06-11
**모체 설계**: `docs/archive/2026-06/3d-ai-performance/02-3d-ai-performance.design.md` §3 (Track B)

---

## Executive Summary

v11.4 Track A(예측 프리페칭)의 후속. 프리페치 비적중·원격 환경에서도 첫 화면 표시를
단축하기 위해, 저해상도를 먼저 표시하고 AI 초해상도(SR)로 보강한 뒤 원본 도착 시
교체한다. **프리뷰 전용 + 측정 잠금**으로 SaMD 경계 밖에서 운용(모체 설계 §3.2).

**전제 게이트 (모체 설계 §1 결정 4)**: SR 모델 PoC —
대표 CT/MR 케이스에서 **SSIM ≥ 0.92**(원본 대비, bicubic 대비 우위 입증 포함) +
**슬라이스당 추론 ≤ 100ms**(GPU 기준). **미달 시 SR 단계를 제외하고 저해상도 점진
표시만 출시하거나 보류.**

## 사전 조사 결과 (2026-06-11 실측)

- **AI 서버에 SR 엔드포인트 없음**: `example.org/ollama`는 미존재 경로에도 405를 반환하는
  서버로, `/api/sr`·`/api/vision/upscale` 모두 실제 라우트 아님 → SR 모델 신규 탑재 필요
- **AI 서버는 별도 시스템**(SSH 터널 뒤 GPU 머신) — 모델 탑재는 AI 서버측 작업으로,
  이 레포에서 직접 배포 불가. PoC 통과 시 AI 서버 작업 항목으로 분리
- **운영 데이터**: CT 9건, MR 4건 보유 — PoC 표본 충분

## 단계

| # | 작업 | 산출물 | 의존성 |
|---|------|--------|--------|
| 1 | **SR PoC** — 운영 CT/MR 슬라이스로 bicubic vs SR(FSRCNN/EDSR 등) SSIM·지연 측정 | PoC 보고(분석 문서) | 없음(로컬 실행) |
| 2 | 게이트 판정 | 진행/축소/보류 결정 | 1 |
| 3 | (통과 시) AI 서버 SR 엔드포인트 탑재 | AI 서버측 작업 | 2 |
| 4 | (통과 시) 백엔드 SR 프록시 `viewer_sr.py` + 뷰어 점진 표시/측정 잠금 | 모체 설계 §3.1·§3.3 | 3 |
| 5 | (미달 시 대안) 저해상도 점진 표시 단독 — Orthanc /rendered 512px 우선 표시 | 뷰어 변경만 | 2 |

## 리스크

- SR이 bicubic 대비 우위가 없으면(흉부 CT 등 평활 영상에서 흔함) 기능 가치 자체가 무산 —
  PoC에 **bicubic 베이스라인 비교 필수**
- PoC는 8-bit 렌더 이미지 기준(표시 보조 용도와 일치). 원시 픽셀(16-bit) SR은 측정 왜곡
  리스크가 더 커서 스코프 제외 유지
- AI 서버 탑재는 외부 의존 — 이 사이클의 Do는 PoC+판정까지, 탑재 이후는 후속 사이클로 분리 가능

## 성공 기준

1. PoC가 게이트 수치(SSIM, 지연)를 정량 산출하고 bicubic 대비 우위 여부를 입증
2. 판정 결과가 분석 문서로 기록되고 다음 행동(3~4 또는 5)이 결정됨
