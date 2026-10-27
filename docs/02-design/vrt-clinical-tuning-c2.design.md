# C2. 3D VRT 임상 튜닝 — 경량 스코프 설계 (2026-07-11)

> v2.0 트랙C C2. 착수 전 측정(2026-07-11): `vrt_metrics` 30일 = **실 임상 사용 0건**
> (전 기록이 E2E 계정 dr.kim·study 1건·11회, 타임스탬프가 E2E 실행일과 일치).
> C1 HTJ2K와 동일한 저수요 신호이나, "UX 장벽(영문 26프리셋·깊은 진입)" 가설이 있어
> **경량 스코프**(뷰어 설정 수준 + 텔레메트리)로 진행하고, 사용률이 오르면
> 커스텀 프리셋 저장·임상 검증(전체 C2)을 착수한다. — 사용자 결정 2026-07-11

## 1. 현황 (v11.6 + 68f83ef)

| 항목 | 상태 |
|------|------|
| 3D 렌더링 | OHIF 3.12 내장 volume3d, HP 4종(main3D/only3D/primary3D/mprAnd3DVolumeViewport) |
| VR 프리셋 | cornerstone 코어 `VIEWPORT_PRESETS` **26개 전부** 노출 (`volumeRenderingCustomization.ts`) |
| 프리셋 한글 라벨 | ✅ 완료(68f83ef) — `i18n/ko-KR.json` WindowLevelActionMenu ns + `VolumeRenderingPresetsContent` t() 패치 |
| 3D 진입 | 레이아웃 셀렉터 Advanced 목록 영문 하드코딩("3D main" 등) — `layoutSelector.advancedPresetGenerator` 커스터마이징 미사용 |
| 텔레메트리 | HP 전환만 (`vrt_metrics.protocol_id`) — 프리셋 선택은 미기록 |
| 측정 잠금 | volume3d toolGroup에 측정도구 미등록(구조적) + 참고용 배지 — 유지 |

## 2. 스코프 (경량)

### 2-1. VR 프리셋 큐레이션 (26 → 13, 한국 임상 순서)
- **지점**: werub-ai `getCustomizationModule` — default scope `'cornerstone.3dVolumeRendering'`
  오버라이드(`_update` 병합, 기존 `viewportOverlay.topRight` `$push`와 동일 메커니즘).
  코어 파일 패치 불요 → 드리프트 최소.
- **목록(순서 고정)**: CT-Bone, CT-Soft-Tissue, CT-Lung, CT-Cardiac, CT-Chest-Contrast-Enhanced,
  CT-Coronary-Arteries, CT-Pulmonary-Arteries, CT-Liver-Vasculature, CT-AAA, CT-MIP,
  MR-Default, MR-Angio, MR-MIP — 13종 전부 한글 i18n 기존재.
- `name`은 룩업 키(cornerstone `setProperties({preset})`·아이콘)이므로 **불변**, 표시만 i18n.

### 2-2. 3D 진입 UX — 레이아웃 셀렉터 한글화·정리
- **지점**: werub-ai에서 `layoutSelector.advancedPresetGenerator` 커스터마이징 제공.
- 항목·순서: MPR → **3D 메인(3d-main)** → **MPR+3D 4분할(3d-four-up)** → 3D 단독(3d-only)
  → 3D 주화면(3d-primary) → Axial 우선(axial-primary) → 프레임 뷰(frame-view). 한글 타이틀.
- protocolId(하이픈)는 셀렉터 명령용이며 HP id(카멜)와 별개 — 기존 매핑 그대로 사용, 변경 없음.

### 2-3. 프리셋 선택 텔레메트리
- **뷰어**: `VolumeRenderingPresetsContent.handleApply`에서 `document` CustomEvent
  `werub:vrt-preset-applied` 발행(기존 werub-source.patch 훅에 1줄) →
  `vrtTelemetry.ts`가 수신, `POST /pacs-api/api/v1/vrt/events/preset` (실패 무해 catch).
- **백엔드**: `vrt_metrics`에 `preset_name VARCHAR NULL` 추가(schema_migrations 러너).
  - `POST /vrt/events/preset` — protocol_id='preset' + preset_name 저장, 기존 rate-limit 재사용.
  - `GET /vrt/metrics/summary` — `by_protocol`은 `preset_name IS NULL`로 한정(집계 오염 방지),
    `by_preset`(최근 30일 preset_name별 uses/users/studies) 추가.

### 비스코프 (사용률 게이트 뒤로)
커스텀 프리셋 저장(TF 영속화 백엔드)·임상 검증 프로토콜·모달리티별 신규 HP 제작·서버 GPU(C3).
**재개 트리거**: by_protocol+by_preset 30일 실사용(E2E 제외)이 유의미(예: 주간 10+ 세션)해지면 전체 C2 착수.

## 3. 배포·검증
- 뷰어: build.sh(NX_SKIP_NX_CACHE 내장) → dist rsync → docker build/run. 빌드 후 번들 grep(큐레이션 반영) 검증.
- 백엔드: vrt.py(볼륨마운트→restart), schema_migrations는 부팅 1회 DDL.
- E2E: `08-vrt.spec.ts` 확장 — ① 레이아웃 셀렉터 한글 항목("3D 메인") 노출·클릭→main3D 텔레메트리(기존 수정),
  ② 프리셋 이벤트 API→summary `by_preset` 반영, ③ capability/summary 기존 회귀.
