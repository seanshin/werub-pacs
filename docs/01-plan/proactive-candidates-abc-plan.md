# 선제 후보 a·b·c 기획서 (2026-07-13)

> v13.20 DICOM 기술검토 후 식별된 **선제 착수 후보 3종**. 모두 **수요 게이트**(현 시점 필수는 아님)이나,
> 착수 시 설계·범위·노력·리스크를 사전 확정해 즉시 진입 가능하게 한다. 각 §의 **착수 트리거**가
> 충족될 때 진입 판정. 프로젝트 원칙(트렌드→코드대조·과투자 방지)상 트리거 전 선제 구현은 신중.

| 후보 | 한줄 | 노력 | 착수 트리거 |
|------|------|:---:|------|
| **A** 병리 WSI 주석 그리기 UI | G1(백엔드 create) 후속 — 뷰어 인터랙티브 마킹 | 중(2~4d, 뷰어 재빌드) | 병리의 수기 마킹 요구 |
| **B** Parametric Map 생성(Sup172) | AI 연속값(확률/히트맵) 표준 저장 | **중저(~2d, 렌더 지원 확인됨)** | AI가 확률맵 산출·재열람 필요 |
| **C** 트윈 전용 서비스계정 | /dicom-web 게이트 하 트윈 read-only 접근 | 소(운영 ~30m) | 트윈이 `/dicom-web` edge 경유 확정 |

## 검토 보완 — 코드·라이브러리 실증 (2026-07-13)
초안의 기술 가정을 코드/서버로 검증해 갱신. **핵심: B의 최대 리스크였던 "뷰어 렌더 미지원"은 거짓**.

| 항목 | 초안 가정 | 실증 결과 | 기획 영향 |
|---|---|---|---|
| B 뷰어 렌더 | "OHIF 지원 미확인, 리스크 최대" | ✅ **`@ohif/extension-cornerstone-dicom-pmap`가 pluginConfig+dist 번들에 포함, SOPClass `…30` 핸들러 렌더** | **B 리스크 대폭↓·viable↑**(producer만 게이트) |
| B highdicom | 미확인 | ✅ `highdicom.pm.ParametricMap(source_images, pixel_array, real_world_value_mappings, window_center/width, ...)` — G1 동형 | 백엔드 구현 명확 |
| A 드로잉 | "dmv ROI 드로잉 활용" | 🟡 **dmv 라이브러리에 `activateDrawInteraction`/`addROI`/`deactivateDrawInteraction` 존재(dist 확인)나 OHIF microscopy 뷰포트엔 미표면**(getNearbyROI 주석만) | A = **기존 라이브러리 능력 표면화**(밑바닥 구현 아님), 뷰포트 래퍼+툴바+저장 배선 |
| C SERVICE edge | 미확인 | ✅ **SERVICE 토큰 `/dicom-web/studies` 200**(edge 게이트 통과, researcher만 차단) + `/refresh` 존재 | C viable 확정, refresh 흐름 명시 |

---

## A. 병리 WSI 주석 그리기 UI (G1 후속)

### A-1. 배경·목적
- G1(v13.20)이 **백엔드 생성 API**(`POST /api/v1/pathology/{uid}/annotations`)와 **뷰어 표시**
  (`DicomMicroscopyANN` 핸들러)를 갖췄으나, **병리의가 뷰어에서 직접 그려 저장하는 UI가 부재**.
- 현재 producer는 "외부/AI가 geometry를 API로 전달". **병리의 인터랙티브 판독 마킹**이 필요하면 이 갭.
- 목적: microscopy 뷰어에서 ROI(폴리곤/포인트 등) 그리기 → 라벨 → 저장(POST) → 재표시. **create/display
  루프를 사용자 손끝까지 완결**.

### A-2. 범위
- **In**: microscopy 뷰포트 ROI 드로잉(폴리곤·포인트·사각·타원) + 라벨 입력 + 저장 연동 + 저장 후 표시.
- **Out(v2/수요)**: 측정(면적·개수) 자동계산·SR 연계, 세그멘테이션 비트맵 마스크, 실시간 협업, 주석 버전관리.

### A-3. 설계·아키텍처
```
[병리의] microscopy 뷰포트에서 ROI 그리기(dicom-microscopy-viewer OpenLayers 드로잉)
  → geometry(total pixel matrix px 좌표) + 라벨/graphic_type
  → POST /api/v1/pathology/{studyUID}/annotations (Bearer pacs_token)   [P1 게이트 하]
  → 백엔드 build_bulk_annotations(highdicom) → ANN(SOPClass …91.1) Orthanc 저장
  → 뷰어 재로드 → DicomMicroscopyANN 핸들러 표시(루프 확인)
```
- **뷰어**: `dicom-microscopy-viewer`는 이미 ROI 드로잉/조회 API 보유(코드에 `getNearbyROI`·`roiAnnotation`
  흔적). microscopy 확장/werub-ai에 **툴바 그리기 버튼 + 저장 핸들러** 추가.
- **좌표계**: **SCOORD(2D 픽셀)** — 백엔드 `build_bulk_annotations`의 `AnnotationCoordinateTypeValues.SCOORD`와
  일치. dmv ROI 좌표(이미지 px)를 그대로 전달.
- **인증**: 저장 POST는 P1 게이트 하 — 뷰어의 `userAuthenticationService.getAuthorizationHeader`(v13.19)로
  이미 Bearer 주입되므로 `/pacs-api` POST에도 재사용.

### A-4. 구현 단계
1. microscopy 뷰포트에 dmv ROI 드로잉 활성화 + 툴바(graphic type 선택).
2. 그린 ROI → geometry 추출 + 라벨 다이얼로그(werub-ai UI 패턴).
3. 저장 핸들러 → `POST /pathology/{uid}/annotations`(AiService fetch 패턴 재사용).
4. 저장 후 재로드 표시 확인 + (선택)편집/삭제.
5. **뷰어 재빌드**(`build.sh` NX_SKIP_NX_CACHE) + dist docker cp + grep 검증.

### A-5. 검증
병리의 그리기→저장→ANN SOPClass …91.1 생성(백엔드 로그)→재로드 시 뷰포트 표시. Playwright(microscopy
모드 렌더 후 드로잉 시뮬레이션은 제한적 → 저장 API 연동은 종단, 드로잉은 수동/스샷).

### A-6. 리스크·함정
- **드로잉은 밑바닥 구현 아님**(실증) — dmv 라이브러리에 `activateDrawInteraction`/`addROI`/
  `deactivateDrawInteraction`가 **빌드된 번들에 존재**. 단 OHIF microscopy **뷰포트 래퍼가 이를
  툴바/UI로 미표면**(getNearbyROI 주석만) → **표면화 배선**이 핵심 작업(드로잉 엔진 자체는 준비됨).
- ★**뷰어 재빌드**(Nx 캐시·SW 캐시 → `[[werub_build_nx_cache_trap]]` — NX_SKIP+rm-rf, 빌드후 grep).
- dmv ROI **좌표계 정합**(이미지 px vs slide mm) — SCOORD(px)로 통일. dmv ROI가 반환하는 좌표계
  실측 확인 필요(SCOORD3D면 변환).
- microscopy 뷰포트 커스터마이징 OHIF 제약(microscopy는 OpenLayers, cornerstone과 별개 뷰포트) —
  툴바/커맨드 등록이 cornerstone 툴그룹과 다른 경로.
- 기존 ANN **편집/삭제**(재저장 시 새 SOP 생성 vs 갱신) 정책 설계 필요.
- **노력**: 중, ~2~4일(드로잉 엔진은 준비 → 표면화 배선 + 저장 연동 + 재빌드 반복이 대부분).

### A-7. 착수 트리거
병리의가 **수기 판독 마킹**을 뷰어에서 직접 하려는 요구. producer가 **AI/외부 시스템**이면(geometry를
API로 push) 이 UI 불요 — G1 백엔드로 충분.

---

## B. Parametric Map 생성 (DICOM Sup 172, G3)

### B-1. 배경·목적
- AI **연속값 출력**(픽셀별 확률·히트맵·SUV·재구성 파라미터)은 이산 SEG/SR로 표현 부적합.
  DICOM **Parametric Map**(SOPClass `1.2.840.10008.5.1.4.1.1.30`)이 float/double 픽셀 표준 IOD.
- 목적: AI가 산출한 확률맵 등을 표준 DICOM으로 저장·재열람. highdicom `pm` 모듈 지원(G1과 동형 패턴).

### B-2. 범위
- **In**: 백엔드 생성 — 참조 이미지(원 CT/MR/WSI) + float 픽셀 배열 + RealWorldValueMapping(단위·범위)
  → ParametricMap → Orthanc 저장. `POST /api/v1/ai/parametric-map` 또는 추론결과 연계.
- **Out(별도/수요)**: 뷰어 파라메트릭맵 컬러맵 렌더(OHIF 지원 조사 필요), 다중프레임 대용량 스트리밍.

### B-3. 설계·아키텍처
```
[AI worker/추론 결과] float 확률맵 배열 + 참조 이미지 UID
  → services/parametric_map.build(...)  [highdicom.pm.ParametricMap]
  → Orthanc 저장(참조 이미지 geometry 계승, RealWorldValueMapping)
  → 뷰어: cornerstone-dicom-pmap 핸들러(SOPClass …30) 컬러맵 렌더 ✅(빌드 포함 확인)
```
- `services/parametric_map.py` — `highdicom.pm.ParametricMap` 래퍼. G1 `microscopy_annotation` 동형.
  **실증 시그니처**: `ParametricMap(source_images, pixel_array(np.float), series/sop UID·number,
  manufacturer·model·versions·serial, contains_recognizable_visual_features(bool),
  real_world_value_mappings, window_center, window_width, ...)`.
- **RealWorldValueMapping**(`highdicom.pm.content`): 저장값→물리량(확률 0~1·SUV 등)+단위 코드. 필수.
  window_center/width = 표시 범위.

### B-4. 구현 단계
1. `highdicom.pm.ParametricMap` API 확인(서버 introspection, G1처럼).
2. 서비스 작성(참조 이미지 로드 + float 픽셀 + RWVM).
3. API/추론 연계(producer가 배열 전달).
4. 생성·Orthanc 저장 검증(SOPClass …30, float 픽셀).
5. **뷰어 렌더 지원 조사**(§B-6) — 표시 안 되면 백엔드 저장만 우선.

### B-5. 검증
합성 확률맵(원 CT geometry + float 0~1 + RWVM) → ParametricMap SOPClass …30 생성·Orthanc 저장 →
**뷰어 렌더 확인**(cornerstone-dicom-pmap 핸들러가 컬러맵 표시, 빌드 포함 확인됨 — 런타임 실증만).

### B-6. 리스크·함정
- ~~뷰어 렌더 불확실~~ ✅ **해소** — `@ohif/extension-cornerstone-dicom-pmap`가 pluginConfig+dist
  번들에 포함, SOPClass `…30` 핸들러(`adaptersPMAP.Cornerstone3D.ParametricMap`)로 컬러맵 렌더.
  잔여는 **실 pmap 1건 런타임 렌더 확인**뿐(초안의 "조사 필수"→"확인만").
- ★**producer 부재(유일 실질 게이트)** — 현 PACS AI는 SEG/SR, 트윈은 메시. 확률맵 산출 producer가
  없으면 순수 인프라 선제 = 과투자. **트리거는 producer 확정.**
- 대용량 float(메모리) — G1의 stop_before_pixels 불가(픽셀 필수) → 스풀/청크 고려(대형 볼륨 시).
- RealWorldValueMapping·window 파라미터 정합(단위·범위 오설정 시 표시 왜곡).
- **노력**: **중저, 백엔드 ~2일**(G1 동형, 렌더 지원 확인됨) + 런타임 렌더 확인.

### B-7. 착수 트리거
AI가 **연속값 출력(확률/히트맵)을 표준 저장·재열람**해야 할 때. 현 producer 부재 → **수요 게이트**
(예: 트윈이 병변 확률맵 산출, 또는 PACS 스크리닝 AI가 히트맵 출력 결정 시).

---

## C. 트윈 전용 서비스계정 사전 발급

### C-1. 배경·목적
- 트윈(AI 아바타)이 Orthanc를 DICOMweb으로 소비. **`/dicom-web` edge 경유 시 P1 토큰 게이트로 Bearer
  필요**(v13.19). svc-lis(병리 전용) 공유는 부적절 → **트윈 전용 read-only 계정**.
- 목적: 트윈이 자체 토큰으로 QIDO/WADO 접근. 최소권한(SERVICE, GET만).

### C-2. 범위
- **In**: `svc-twin` SERVICE 계정 생성 + 자격증명 안전 전달 + (트윈이 별 호스트면) nginx IP allowlist.
- **Out**: 트윈이 **Orthanc 직접**(`127.0.0.1:8042` Basic) 접근이면 **불요**(P1 게이트는 nginx만).

### C-3. 설계·구현 (실증 반영)
- `create_service_account.py --username svc-twin --email twin@example.org`(스크립트 기존재, 코드 신규 없음).
- **접근 경로(실증)**: SERVICE 토큰이 **edge `/dicom-web/studies` 200 통과 확인**(P1 `_authcheck`는
  researcher만 차단, SERVICE 수용). 즉 svc-twin이 QIDO(`/rs/*`, StudyReadRoles에 SERVICE 포함)+
  WADO 프레임(`/dicom-web`) 모두 read-only 접근 가능.
- **토큰 갱신 흐름**: login `POST /api/v1/auth/login` → access(60분)+refresh(7일). 만료 시
  **`POST /api/v1/auth/refresh` {refresh_token}**(엔드포인트 실재) → 새 access. 트윈 커넥터에 refresh 구현 권장.
- **쓰기 차단**: H1 `_enforce_service_readonly`로 SERVICE는 비-GET 403(read-only 강제).
- 트윈이 별 호스트면 nginx allowlist에 egress 추가(현 게이트는 토큰이라 IP 불요, 심층방어 선택).

### C-4. 검증
svc-twin 로그인 → QIDO-RS 200 · `/dicom-web` 200(프레임) · 쓰기 EP **403** · refresh로 access 갱신.
(svc-lis로 SERVICE edge 200·쓰기 403 이미 실증 — svc-twin 동일 role.)

### C-5. 리스크
- 트윈 접근경로 미확인 — **Orthanc 직접이면 이 작업 불요**(먼저 확인). `/dicom-web` edge면 필수.
- 토큰 만료(access 60분) → 트윈이 refresh 또는 재로그인 구현.
- **노력**: 소, 운영 ~30분(계정 생성 + 전달).

### C-6. 착수 트리거
트윈이 **`/dicom-web` edge 경유** 확정. (Orthanc 직접 접근이면 skip.)

---

## 실증 상세 (executable-level, 2026-07-13)

### B — 타당성 스파이크 ✅ PASS (설계→실증)
서버 backend 컨테이너에서 실제 생성·저장 성공:
- 소스: 기존 CT(enhanced multi-frame, `NumberOfFrames=2`, 512×512).
- `pixel_array` = **(2, 512, 512) float32**(중앙 0.85), `RealWorldValueMapping(lut_label='PROB',
  unit=Code('1','UCUM','no units'), value_range=(0.0,1.0), slope=1, intercept=0)`, window 0.5/1.0.
- 결과: `ParametricMap.SOPClassUID = 1.2.840.10008.5.1.4.1.1.30` → Orthanc **Success**(Modality OT).
- ★**gotcha(실증)**: `pixel_array` **첫 차원 = 소스 이미지 plane/frame 수**(단일슬라이스=1,
  enhanced multi-frame=`NumberOfFrames`, 다중 소스=len). 불일치 시 `ValueError: Number of plane
  positions ... does not match`. → 서비스는 소스 프레임수 검사·정합 필수.

**서비스 스켈레톤** `services/parametric_map.py`:
```python
def build_parametric_map(source_images, pixel_array, *, lut_label, lut_explanation,
                         unit_code, value_range, window_center, window_width,
                         series_number=301, content_description=None):
    # pixel_array.shape[0] == 소스 plane/frame 수와 일치해야 함(검사)
    rwvm = RealWorldValueMapping(lut_label, lut_explanation, Code(*unit_code),
                                 value_range, slope=1, intercept=0)
    return ParametricMap(source_images=source_images, pixel_array=pixel_array,
        series_instance_uid=hd.UID(), series_number=series_number, sop_instance_uid=hd.UID(),
        instance_number=1, manufacturer="OpenPACS", manufacturer_model_name="WeRU.B PACS",
        software_versions="v13.x", device_serial_number="OPENPACS",
        contains_recognizable_visual_features=False, real_world_value_mappings=[rwvm],
        window_center=window_center, window_width=window_width, content_description=content_description)
```
**Producer 훅**: `services/ai_worker.py`(추론 결과 저장 지점, SEG/SR 생성 `dicom_ai_standard.py` 옆).
in-process 호출(HTTP 아님) — AI가 float 확률맵 산출 시 build→Orthanc STOW. (외부 producer면 API 추가.)
**검증**: 위 스파이크 스크립트 재사용(생성·저장 PASS) + 뷰어에서 study 열어 pmap 컬러맵 렌더 확인.

### A — 통합 지점 (실증)
- **dmv viewer 인스턴스**: `DicomMicroscopyViewport.tsx:140 const viewer = new microscopyViewer(options)`
  — **로컬 const**라 커맨드에서 접근하려면 **service/ref로 노출** 필요(현재 미노출이 A의 실작업 핵심).
  노출 후 `viewer.activateDrawInteraction({geometryType})` / `viewer.addROI` / `viewer.deactivateDrawInteraction`
  (라이브러리 API 실재, dist 확인).
- **커맨드 등록**: `werub-ai/getCommandsModule.ts`의 `definitions:{ werubComparePrior:{...} }` 옆에
  `werubDrawAnnotation`(드로잉 활성)·`werubSaveAnnotation`(POST) 추가 + 툴바 버튼.
- **드로잉→저장**: `activateDrawInteraction` → onDrawEnd에서 ROI 좌표(px) 수집 → 라벨 다이얼로그 →
  `POST /api/v1/pathology/{studyUID}/annotations`(G1 API, `{groups:[{label,graphic_type,coordinates,...}]}`,
  Bearer는 `userAuthenticationService`가 주입). 저장 후 재로드 표시.
- **단계**: (1)뷰포트가 viewer 인스턴스 노출(service/ref) →(2)툴바+커맨드 →(3)드로잉 활성+onDrawEnd 수집
  →(4)저장 POST →(5)재빌드(NX_SKIP+dist docker cp+grep).

### C — 턴키 절차 (실증)
- **계정 생성**(1회):
  ```
  docker compose exec -T -e SVC_PASSWORD='<강한값>' backend \
    python -m app.scripts.create_service_account --username svc-twin --email twin@example.org
  ```
- **엔드포인트 계약**(트윈 커넥터):
  - 로그인: `POST /pacs-api/api/v1/auth/login {username,password}` → `{access_token, refresh_token, expires_in}`
  - 갱신: `POST /pacs-api/api/v1/auth/refresh {refresh_token}` → `{access_token,...}`(access 60분 만료 시)
  - QIDO: `GET /pacs-api/api/v1/dicomweb/rs/studies?PatientID=…`(Bearer) — 표준 태그키
  - WADO 프레임: `GET /dicom-web/studies/{uid}/series/{s}/instances/{i}/frames/{f}`(Bearer)
- **검증(실증)**: svc-lis로 이미 확인 — SERVICE 토큰 edge `/dicom-web` **200**·쓰기 EP **403**. svc-twin 동일 role.
  트윈이 Orthanc 직접(127.0.0.1:8042 Basic)이면 이 전부 불요.

## 오픈소스 레퍼런스 + 기술 보강 (2026-07-13)

### A — Slim(IDC) = 정본 레퍼런스 + ★좌표계 정정
- **[Slim](https://github.com/ImagingDataCommons/slim)**(ImagingDataCommons) — 오픈소스 DICOM WSI
  뷰어+**주석 도구**로, **werub와 동일한 `dicom-microscopy-viewer` 라이브러리 사용**. `SlideViewer.tsx`가
  드로잉→저장의 직접 참조. A는 Slim의 접근을 이식하면 리스크 최소.
- ★**좌표계 정정(중요)**: dmv ROI 좌표는 **SCOORD3D(3D 슬라이드 좌표계, mm, 피라미드 전 해상도 독립)** —
  초안·G1의 "SCOORD 2D 픽셀" 가정과 **다름**. Slim은 저장 시 **이미지 2D px → 3D 슬라이드 mm를 affine
  변환행렬(DICOM PS3.3 Ch C 방정식)로 매핑**. → A는 dmv가 주는 SCOORD3D를 그대로 쓰거나 변환 필요.
- **저장 방식 선택**(Slim 근거):
  - **개별 병리의 ROI + 측정** → **DICOM Comprehensive 3D SR(TID 1500 Measurement Report + TID 1400
    Planar ROI)**. werub에 `DicomMicroscopySRSopClassHandler`(Comprehensive3DSR) 표시 핸들러 **기존재**.
    → **인터랙티브 드로잉은 SR이 정본**(Slim 방식).
  - **대량 알고리즘 주석(슬라이드당 수백만)** → Microscopy Bulk Annotations(ANN, G1). AI 대량 출력용.
- ★**G1 렌더 검증 결과(2026-07-14, 실증) — 렌더 안 됨**: G1으로 생성한 ANN(SOPClass …91.1, POLYGON)을
  실제 microscopy 뷰어에서 확인 → **WSI는 렌더되나 주석 폴리곤 미표시**. 콘솔 경고
  `"No instances in {ANN display set}"`. **즉 v13.20의 "create/display 루프 완결"은 과장 — 생성은
  되나 표시가 안 됨.**
  - **원인 후보**: ① 뷰어 config **`bulkDataURI.enabled: false`**(werub-app-config:380) — ANN은 좌표를
    **bulk data**로 저장, `loadAnnotation`이 DICOMweb client로 재조회하는데 bulkdata 비활성이면 로드 실패.
    ② ANN 오버레이 디스플레이셋에 인스턴스 미연결(metadata store 등록/소스 연계).
  - **해소안**: (a) `bulkDataURI.enabled: true`로 켜고 재빌드 후 재검증(전 dataSource 영향 → 프레임 로딩
    회귀 확인 필요) + 디스플레이셋 연계 디버깅, **또는** (b) ★**인터랙티브 경로는 SR(TID1500)로 설계**
    (Slim 방식, werub SR 핸들러 기존재 — bulkdata 불요, 렌더 검증된 경로).
  - ★**함정(실증)**: ANN POLYGON은 **첫/끝 좌표가 동일하면 안 됨**(highdicom 검증, SR과 반대). G1 API 사용
    시 열린 폴리곤 전달.

### B — dcmqi / MONAI Deploy / highdicom
- **[dcmqi](https://github.com/QIICR/dcmqi)**(QIICR/NCI IDC) — 연구포맷(ITK)↔DICOM SEG/**Parametric
  Map**/SR 변환 C++ 정본 + **JSON 메타데이터 스키마**(RWVM·단위·범위 구조 참조). highdicom = Python 등가
  (본 기획 스파이크가 사용).
- **[MONAI Deploy App SDK](https://docs.monai.io/projects/monai-deploy-app-sdk/)** — AI 추론→DICOM
  파이프라인 정본. DICOM writer(SEG/SR/STL, highdicom 기반)·`MonaiSegInferenceOperator`·DICOM store
  커넥터. **B의 producer(ai_worker) 참조** — 단, MONAI writer도 SEG/SR/STL 중심이고 **PM writer는 드묾**
  → B의 "producer 게이트"(확률맵 산출 AI 부재)가 생태계에서도 확인됨.
- **함의**: B 백엔드(highdicom PM)는 이미 스파이크로 실증. dcmqi 스키마·MONAI 파이프라인이 producer 설계 참조.

### C — 표준 DICOMweb 인증(추가 조사 불요)
- OAuth2/Bearer는 표준. 트윈은 dicomweb-client(Python)·OrthancClient 등으로 Bearer 헤더 첨부.
  ([dicomweb-client](https://github.com/ImagingDataCommons/dicomweb-client) — IDC의 표준 Python 클라이언트,
  헤더 주입 지원). 신규 조사 불요.

## 종합 판정 (실증 반영)
- **C**: 노력 최소·트리거 명확. SERVICE edge 200·refresh 실증 → 트윈 접근경로가 edge면 **즉시(운영 ~30m)**.
  Orthanc 직접이면 skip. **셋 중 진입 장벽 최저.**
- **B**: ~~렌더 불확실이 최대 리스크~~ → **렌더 지원 확인 + 타당성 스파이크 PASS(highdicom→Orthanc
  SOPClass …30 저장 실증)로 기술 리스크 최소화**. 백엔드 G1 동형(~2일), 렌더 cornerstone-dicom-pmap
  기존재. **유일 게이트 = producer(확률맵 산출 AI) 확정**뿐. producer만 생기면 빠르게 완성.
- **A**: 드로잉 엔진(dmv)은 준비 → **표면화 배선 + 저장 연동 + 재빌드**. 뷰어 재빌드가 주 리스크. G1
  백엔드 준비돼 UI 계층만. 병리 인터랙티브 마킹 요구 시.
- **정정 요지**: B의 기술 불확실성이 초안보다 크게 낮음(렌더 지원됨). **기술 준비도: B ≈ C > A**(A만
  뷰어 재빌드 부담). 단 **수요(트리거)는 여전히 셋 다 미도달** — 트리거 전 선제 구현은 과투자.
- 트리거 도달 시 본 기획서로 즉시 진입. 진입 순서 권장: **C(트리거 시 즉시) → B(producer 확정 시) → A(마킹 요구 시)**.
