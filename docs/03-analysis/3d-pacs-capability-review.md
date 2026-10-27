# 3D PACS 능력 검토

**작성일**: 2026-06-06
**대상**: WeRU.B PACS의 3D 영상 처리(MPR/MIP/VRT) 능력
**근거**: OHIF v3.12.0 / Cornerstone3D 소스(`werub-viewer/.ohif-src`) + WeRU.B 모드·config 정독
**관련**: [[werub_viewer_session_20260606]], `docs/01-plan/pacs-plan.md` (scope)

---

## 0. 핵심 요약

| 3D 기능 | 엔진(Cornerstone3D) | WeRU.B 뷰어 노출 | 비고 |
|---|:---:|:---:|---|
| **MPR** (다평면 재구성) | ✅ | ✅ Layout 버튼 + Crosshairs | axial/coronal/sagittal |
| **MIP / MinIP / Average** | ✅ blend modes | 🟡 부분 (블렌드 설정 필요) | `getCornerstoneBlendMode` |
| **3D VRT** (Volume Rendering) | ✅ | ✅ Layout 버튼 + 3D Rotate | volume3d toolGroup, CT-Bone 프리셋 |
| **4-up** (3 MPR + 1 VR) | ✅ `fourUp.ts` | ✅ Layout 선택 | |
| **GPU 가속** | ✅ WebGL | ✅ (콘솔 "using GPU rendering") | |

**핵심 발견**: **3D VRT(볼륨 렌더링)는 이미 엔진+UI에 존재**하며 Layout 버튼으로 접근 가능하다. 그러나 `docs/01-plan/pacs-plan.md`의 v1.0 scope는 *"3D VRT — Out (v2.0)"* 로 명시 → **scope 문서가 실제 능력을 과소평가**(MPR/HP 정정 사례와 동일 패턴). 다만 임상 워크플로우용 **검증·튜닝·노출 강화**는 미완으로, "능력 보유 ≠ 임상 검증 완료"를 구분해야 한다.

---

## 1. 엔진 능력 (Cornerstone3D / OHIF v3.12)

### 1.1 Hanging Protocols (`extensions/cornerstone/src/hps/`)
- `mpr.ts` — MPR 3평면
- `fourUp.ts` — 3 MPR + 1 3D 볼륨
- `main3D.ts`, `primary3D.ts`, `only3D.ts` — 3D 볼륨 렌더링 레이아웃
- `mprAnd3DVolumeViewport.ts` — MPR + 3D 동시
- `primaryAxial.ts`, `frameView.ts`

### 1.2 도구·toolGroup (`modes/basic/src/initToolGroups.ts`)
- `initMPRToolGroup` — MPR + **Crosshairs**(동기화)
- `volume3d` toolGroup — 3D 렌더링
- 툴바: **3D Rotate**(TrackballRotate), **Layout**(레이아웃 선택), Crosshairs

### 1.3 렌더링 모드
- **VRT**: `volumeRenderingCustomization.ts` + ViewportPresets (CT-Bone 등). `main3D.ts`가 `CT: 'CT-Bone'` 프리셋 적용.
- **MIP/MinIP/Average**: `getCornerstoneBlendMode` — MAXIMUM/MINIMUM/AVERAGE_INTENSITY_BLEND.
- **W/L 프리셋(VR)**: ct-lung(1500/-600), ct-bone(2500/480).

---

## 2. WeRU.B 뷰어 노출 현황

- 사용 모드 = 패치된 **longitudinal** (route /viewer). mode-basic 상속 → `volume3d`·`mpr` toolGroup, Layout/3D Rotate/Crosshairs 버튼 보유.
- **Layout 버튼** → grid / MPR / 3D 레이아웃 전환 가능.
- config(`werub-app-config.js`): `strictZSpacingForVolumeViewport: true`(볼륨 재구성 시 균일 Z-간격 강제), `maxNumberOfWebWorkers: 3`, GPU 렌더링 활성.

→ **3D/MPR/VRT는 "Layout 버튼"으로 접근 가능한 상태.** 별도 개발 없이 동작(다만 아래 갭 참조).

---

## 3. Scope vs 실제

| | pacs-plan.md v1.0 scope | 실제 |
|---|---|---|
| 2D + MPR/MIP | In ✅ | ✅ 가용 |
| **3D VRT** | **Out (v2.0)** | ✅ **엔진+UI 이미 가용** (Layout→3D) |

→ MPR(분석 F7), 모달리티 HP에 이어 **3D VRT도 OHIF 기본 제공**. scope 문서는 "신규 개발 필요"로 봤으나 실제론 "활성화·검증" 수준. **scope 갱신 권장.**

---

## 4. 요구사항 / 전제

- **볼륨 데이터**: 다중 슬라이스 CT/MR + **균일한 슬라이스 간격·기하**. `strictZSpacingForVolumeViewport: true`라 **비균일 간격 시리즈는 볼륨 렌더 불가**(2D 스택만).
- **GPU/WebGL**: MPR/VRT는 GPU 가속 필요(콘솔 "using GPU rendering" 확인). **GPU 없는 클리닉 PC는 느리거나 실패** 가능.
- **메모리**: 볼륨 로딩은 전체 시리즈를 메모리에 적재 → 대용량 CT(수백~수천 슬라이스)는 메모리 부담.
- **전송구문**: Cornerstone3D가 디코딩(J2K/JPEG-LS 등) → 제약 적음.

---

## 5. 갭 (임상용 3D PACS 완성도)

| # | 갭 | 영향 |
|---|---|---|
| G1 | **임상 검증 미완** — 3D 기능은 가용하나 WeRU.B 판독 워크플로우로 검증·홍보 안 됨 | "동작 가능" ≠ "임상 사용 검증" |
| G2 | **3D 전용 HP·툴바 부재** — Layout 버튼 수동 전환만, 모달리티별 3D 자동 레이아웃 없음 | 판독 속도 |
| G3 | **VR 프리셋 한국형 미튜닝** — OHIF 기본(CT-Bone 등). 2D는 한국 임상 W/L 7종 튜닝했으나 VR은 미반영 | 일관성 |
| G4 | **`strictZSpacing` 엄격** — 비균일 CT 시리즈 볼륨 렌더 차단 | 실무 영상 호환성 |
| G5 | **GPU/메모리 요구 미문서화** — 배포 PC 하드웨어 가이드 없음 | 클리닉 도입 |
| G6 | **scope 문서 불일치** — 3D VRT를 v2.0/Out으로 표기 | 규제/계획 정합 |

---

## 6. 권장 (우선순위) — 진행 결과 (2026-06-06)

1. ✅ **3D 실증 + scope 정정 완료** — 133슬라이스 LIDC 흉부 CT로 **MPR 3평면(axial/sagittal/coronal) 브라우저 실증**. `pacs-plan.md` scope 정정(3D VRT 엔진 가용). (commit b76d5bf)
2. ✅ **한국형 VR 프리셋 완료** (라벨) — VR 프리셋 메뉴 i18n(폐/뼈/연부조직/심장/폐동맥 등). *3D 전용 자동 HP는 생략* — OHIF Layout 버튼으로 충분, 자동 적용은 단일/비균일 시리즈 오작동 위험. (commit 68f83ef)
3. ✅ **GPU/메모리 배포 가이드 완료** — `docs/3d-viewing-hardware-guide.md` (클라이언트 렌더링, 기능별 사양, 워크스테이션 등급, 폴백). (commit fceebc8)
4. ✅ **`strictZSpacing` 정책 결정 — `true` 유지** — 비균일 슬라이스 간격 시리즈를 볼륨 렌더에서 차단하는 현 설정을 **유지**한다. 비균일 간격으로 강제 볼륨 재구성하면 **기하가 부정확 → 측정값 오류 위험**(사용자 강조 원칙). 안전(엄격)을 정확도보다 우선. 비균일 영상이 빈번한 기관은 운영 판단으로 보간 옵션을 별도 검토하되, 기본은 엄격 유지.

> 결론: 3D PACS 능력은 **엔진 보유 + MPR 실증 + 한국형 라벨 + 배포 가이드**로 정합화됐다. 본격 임상 3D(전용 HP, 검증)는 임상 요구 발생 시 확장.

---

## 부록: 빠른 사용법 (현재 가능)
CT/MR 다중슬라이스 스터디 열기 → 툴바 **Layout 버튼** → **MPR** 또는 **3D(Volume)** 레이아웃 선택 → Crosshairs(MPR 동기화)/3D Rotate(회전). VRT는 GPU 필요.
