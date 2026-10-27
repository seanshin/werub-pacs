# WeRU.B Viewer 개선 기획서

**작성일**: 2026-06-05 (v2 — 상세 분석 반영)
**대상**: WeRU.B Viewer (OHIF v3.12.0 source build, Cornerstone3D)
**근거**: `docs/03-analysis/werub-viewer-analysis.md` (소스 2,655 LOC 전수 + OHIF 원본 대조 + 운영 실측)
**관련**: v10.1 DICOM AI 표준화([[dicom_ai_standard_compliance]]), `docs/01-plan/pacs-plan.md`

> **v2 정정 요지**: 상세 분석 결과, 표준 SEG/SR **렌더링 핸들러는 이미 존재**(`modes/basic`에 dicom-seg/-sr/-rt/-pdf 전부 포함). 따라서 P0은 "확장 추가"가 아니라 **재빌드+워크플로우 연결+검증**으로 정정. 또한 **배포 번들이 ~3주 stale(v7.0)** 임이 확인되어 "재빌드·배포"가 새로운 최우선 전제로 추가됨.

---

## 1. 현재 상태 (분석 확정)

| 구성 | 내용 | 상태 |
|---|---|:---:|
| 베이스 | OHIF v3.12.0 소스 빌드, ko-KR i18n, 한글 formatPN, YYYY-MM-DD | ✅ |
| Extension | `werub-ai`(동기 AI), `werub-report`(판독 CRUD/서명/예비/템플릿), `shared` | ✅ 견고 |
| Mode | `werub-reading`(`@ohif/mode-basic` 확장 — SEG/SR/RT/PDF 핸들러 상속) + 패치된 `longitudinal` 이중화 | 🟡 |
| 표준 SEG/SR 렌더 | OHIF 핸들러 **존재**(F4) — 능력 보유, 워크플로우 미연결 | 🟢/❌ |
| AI 연동 | 전부 **동기** LLM 엔드포인트, `/inferences` 비동기 잡·`ws/ai_progress` 미사용 | ❌ |
| 배포 번들 | **"WeRU.B 7.0", 2026-05-19 빌드** — v10.0/v10.1 미반영 | 🔴 stale |
| MPR/MIP | 미설정 | ❌ |
| 진단 위생 | `onError` 핵심 에러 억제, WorkList 무인증 fetch | 🟠 |

핵심 발견 상세는 분석서 §0(F1~F9) 참조.

---

## 2. 개선 항목 (우선순위 — 분석 정정 반영)

### P0 — 전제 복구 + v10.1 루프 완성

**P0-A. 재빌드·배포 + 버전 동기화** ⭐ *(모든 개선의 전제)*
- **배경**: 배포 번들이 v7.0(2026-05-19)로 ~3주 stale. 소스의 v10.0 보안/UX 변경조차 미반영(F1, F8).
- **작업**: `build.sh` 재빌드 → `openpacs-werub` 이미지 재빌드·배포. 패치 `WERUB_VERSION`을 **v10.1**로, `BUILD_DATE` 갱신. (가능하면 버전을 빌드 인자/단일 소스로 분리해 수동관리 제거)
- **검증**: About 모달 v10.1 표시, v10.0 UX 변경 반영 확인.
- 가치: ★★★ / 난이도: 하 (빌드·배포 절차)

**P0-B. 표준 SEG/SR 루프 연결 + 실증** ⭐
- **배경**: OHIF 렌더 능력은 보유(F4)하나, AI 패널이 표준 추론 결과(SEG/SR)를 **생성/대기/로드/강조하지 않음**(F2). 현재는 워커가 저장한 뒤 스터디 재로드 시 추가 시리즈로만 등장.
- **작업**:
  - AI 패널에서 **표준 추론 잡(`POST /inferences`, v10.1 수리분) 트리거** → 완료 시 결과 SEG/SR을 **자동 로드**.
  - SEG: 영상 위 컬러 오버레이(투명도/토글), SR: 측정/소견을 측정 패널·근거영상 점프로 매핑.
  - 우측 패널에 "AI 결과(표준)" 섹션 — 동기 LLM 결과와 분리 표기.
- **선행**: 현행(재빌드 후) 뷰어에서 표준 SEG/SR이 **재로드만으로 표시되는지 1회 E2E 실증** → 연결 범위 확정.
- 가치: ★★★ / 난이도: 중 (연결·검증 중심, 신규 렌더링 개발 아님)

### P1 — 진단 위생 + 판독 강화

**P1-1. 진단 위생 정리** (분석 R1~R3)
- `onError` 억제 화이트리스트 **최소화**(`extensionDependencies`/`undefined` 무차별 억제 제거) → 실패 가시화(F3).
- **모드 이중화 정리**(F5): `werub-reading` vs 패치된 `longitudinal` 중 기본 진입 1개로 단일화.
- **WorkList 인증 수정**(F6): `/reports/status-batch` fetch에 Bearer 토큰 추가(v10.0 하 401 해소).
- 가치: ★★ / 난이도: 하

**P1-2. MPR/MIP 활성화** (pacs-plan v1.0 scope, F7)
- CT/MR 다평면 재구성(axial/coronal/sagittal) + MIP. Cornerstone3D 내장 → reading 모드 뷰포트/툴바/단축키 노출.
- 가치: ★★★ / 난이도: 중

**P1-3. 모달리티별 Hanging Protocol 확충**
- 흉부 CT(폐/종격동), 유방 4-view(MLO/CC 좌우), prior 자동 나란히, MR 시퀀스 정렬.
- 가치: ★★ / 난이도: 중

### P2 — UX·품질·안전

**P2-1. saveAsSR 표준 빌더 통합**(F9) — `/reports/structured` 자체 스키마 → v10.1 `dicom_ai_standard` 표준 SR 경로로 일원화.
**P2-2. 측정 → 구조화 SR 자동 연동** — measurement-tracking 값을 리포트/TID 1500 SR로.
**P2-3. 비표준 검증 경고 인뷰어 배지** — DICOM Issue(JPEG 밀도 불일치 등)를 뷰어 상단 경고로(사용자 강조 기능).
**P2-4. Key Image / Secondary Capture** — 핵심 슬라이스 마킹·저장.
**P2-5. 단축키·프리셋·i18n 보강.**

---

## 3. 권장 로드맵

| 단계 | 항목 | 근거 |
|---|---|---|
| **1차** | **P0-A 재빌드·배포** | 현 배포 v7.0 — 모든 개선의 전제 |
| **2차** | **P0-B 표준 SEG/SR 연결·실증** + P1-1 진단 위생 | v10.1 투자 회수, 가시성 확보 |
| **3차** | P1-2 MPR/MIP + P1-3 HP | scope 충족 + 판독 속도 |
| **4차** | P2-1~5 | 표준 통합·안전·UX 마감 |

## 4. 리스크 / 주의
- **빌드 필수**: 모든 뷰어 수정은 `build.sh` 재빌드 (번들 직접 패치 금지 — SW/캐시 미반영).
- **OHIF v3.12 고정**: SEG/SR/RT 확장 호환성 유지, 메이저 업글 금지.
- **`/viewer/`(기존 OHIF 컨테이너)는 별도** — `/werub-viewer/`만 대상.
- **에러 억제 완화 시 주의**: 실제 무해 에러까지 노출될 수 있어 단계적으로(로그→선별).
- 표준 SEG/SR은 **능력 보유 → "연결·검증"** 중심이라 1차+2차에서 빠른 성과 기대.

---

## 다음 단계
1. **P0-A 재빌드·배포** 즉시 착수 가능 (절차적).
2. 재빌드 후 **P0-B 실증**: 표준 추론 1회 실행 → 뷰어 재로드로 SEG/SR 표시 여부 확인 → 연결 작업 범위 확정.
3. 정식 PDCA: `/pdca plan werub-viewer-standard-ai-loop`.

---

## 진행 현황 (2026-06-06 업데이트)

> 상세 구현·검증 결과는 `docs/03-analysis/werub-viewer-analysis.md` §7 참조.

| 항목 | 상태 | 비고 |
|---|:---:|---|
| **P0-A** 재빌드·배포 | ✅ 완료 | v7.0→v10.1, 브라우저 확인 (commit e4c4e2f) |
| **P0-B** 표준 SR 루프 | ✅ 완료 | 데이터 E2E + AI 패널 카드 + **SR Text 뷰포트 렌더** (f3d2e52, 11b524b) |
| **F6** WorkList 인증 | ✅ 완료 | 401 해소 (f3d2e52) |
| **P1-1 F3** onError 완화 | ✅ 완료 | 실제 에러 콘솔 노출 (9cd9c92) |
| **P1-2 MPR/MIP** | ✅ **이미 가용** | Layout 버튼 상속 — 분석 F7 철회, 구현 불필요 |
| SR 뷰포트 크래시 | ✅ 해결 | Text 뷰포트 폴백 라우팅 (11b524b) |
| **P1-1 F5** 모드 이중화 | ✅ 완료 | 미사용 werub-reading 제거, longitudinal 단일화 (47d6846) |
| **P1-3** 모달리티 HP 확충 | ✅ **대부분 가용** | hpMammo(MG 4-view 자동매칭)/hpCompare/mnGrid 내장. 흉부CT 커스텀만 미작성 |
| **P2-1 F9** saveAsSR 표준 통합 | ✅ 완료 | build_text_sr — 표준 텍스트 SR(UTF-8) Orthanc 저장 (e1aed73) |
| **P2-2** 측정→SR 연동 | ⬜ 미착수 | 중간 |
| **P2-3** 비표준 검증 경고 배지 | ✅ 완료 | 검증 이슈 시 상단 배너(JPEG 밀도 등), config 런타임 주입 (78e13da, 9c0d70e). 토큰 유효 세션에서 표시 |
| **P2-4/5** Key Image·단축키 | ⬜ 미착수 | minor |
| **분할 모델 트랙(SEG)** | ⬜ 보류 | 현 모델 분류만 → 마스크 출력 모델 선행 |

### 운영 주의 (재확인)
- Orthanc가 공유 postgres에 상시 ~56 연결 사용. **max_connections 100→200 상향 완료(2026-06-06, ALTER SYSTEM + 재시작)** → 정상상태 ~94/200, 헤드룸 100+, HospitalRun 고갈 위험 해소. (shared_buffers 128MB 기본값은 추후 선택적 상향)
- 뷰어의 /pacs-api 호출(AI 패널·판독·검증배너)은 `pacs_token`(JWT, 1h 만료) 의존 → 만료 시 401. 장시간 세션은 재로그인 필요.

### 잔여 폴리시
- SR Text 뷰포트 `[IMAGE is not supported]` + 잔여 토스트 1건 → onError 완화로 콘솔 노출되므로 다음 진단 시 가드.

배포 커밋: e4c4e2f → f3d2e52 → 11b524b → 9cd9c92 (모두 origin 푸시).
