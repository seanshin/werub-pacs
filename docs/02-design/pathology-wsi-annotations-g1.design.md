# 병리 WSI 벌크 주석 (DICOM Sup 222) 설계 — G1

| 항목 | 내용 |
|------|------|
| 표준 | DICOM Supplement 222 — Microscopy Bulk Simple Annotations (WG-26) |
| SOPClass | `1.2.840.10008.5.1.4.1.1.91.1` (Modality `ANN`) |
| 도입 | v13.20 (DICOM 기술검토 G1) |
| 배경 | 생성 경로 신설(v13.20) + 뷰어 표시 경로 정합(v13.21) |

## 1. 목적·범위
- **목적**: WSI(VL Whole Slide Microscopy, SM) 스터디에 대한 주석(폴리곤/포인트 등)을 표준 DICOM
  ANN 객체로 **생성·저장**. 계산병리 AI 출력(슬라이드당 대량 주석)·병리의 수기 마킹 저장·교환.
- **In**: geometry(주석 좌표) 수신 → highdicom로 ANN 생성 → Orthanc 저장. 뷰어 표시(기존 핸들러).
- **Out(수요 게이트)**: 뷰어 인터랙티브 주석 그리기 UI, measurements/SR 연계, 세그멘테이션 마스크
  (POLYGON 등 5종 graphic type만 우선), 비동기 대량주석 스트리밍.

## 2. 아키텍처
```
[producer: 병리의 수기 · 계산병리 AI]
    → POST /api/v1/pathology/{study_uid}/annotations  {groups:[{label,graphic_type,coordinates,...}]}
        [PathologyWriteRoles: ADMIN/RAD/PHYSICIAN, allow_btg=False]
    → _find_sm_instance: study의 SM 시리즈 첫 인스턴스(Orthanc /tools/find)
    → 소스 WSI 인스턴스 메타 로드(pydicom, stop_before_pixels)
    → build_bulk_annotations(highdicom.ann): AnnotationGroup[] → MicroscopyBulkSimpleAnnotations
    → Orthanc POST /instances (SOPClass …91.1, 같은 study)
[consumer: 뷰어] microscopy 모드 → DicomMicroscopyANNSopClassHandler(sopClassUids …91.1) 표시
```

## 3. 구현
- **`services/microscopy_annotation.build_bulk_annotations(source_image, groups, ...)`**
  - `source_image`: SM WSI pydicom Dataset(참조·공간정보 원천). Modality!=SM 이면 거부.
  - `groups[i]`: `{label, graphic_type(POLYGON/POINT/POLYLINE/ELLIPSE/RECTANGLE),
    coordinates([[[col,row],...],...]), algorithm_type(MANUAL/AUTOMATIC/SEMIAUTOMATIC),
    category/type(SNOMED Code, 선택)}`.
  - `annotation_coordinate_type=SCOORD`(2D 픽셀좌표). 기본 category=Anatomical Structure/type=Tissue.
  - **비표준 WSI 방어**: highdicom가 소스에서 환자/검사 속성 복사 시 일부 존재 요구 →
    PatientBirthDate·Sex·StudyID·AccessionNumber 등 누락 시 빈값 주입(크래시 방지).
- **`api/pathology_annotation`**: `POST /{study_uid}/annotations` → 응답 `{sop_instance_uid,
  series_instance_uid, sop_class_uid, groups, orthanc}`. `PathologyWriteRoles`.

## 4. 설계 결정
- **highdicom 재사용** — 이미 0.27.0 의존(SR/SEG). 라이브러리 교체·신규 의존 없음.
- **create 신설 + 인터랙티브 그리기→저장(v13.22)** — 뷰어 표시 핸들러·드로잉 도구(polygon/point/freehand 등)는
  OHIF microscopy 모드 기존재. v13.22에서 **드로잉→ANN 저장 브리지**를 `MicroscopyPanel`에 추가("DICOM 주석
  저장(ANN)" 버튼) — 드로잉된 ROI의 `scoord3d`(슬라이드 3D 좌표)를 백엔드로 POST.
- **RBAC** — 병리 판독 write는 임상역할(ADMIN/RAD/PHYSICIAN, RESIDENT 승격). RESEARCHER/SERVICE/TECH
  제외(M3/H1 정책과 일관). allow_btg=False(쓰기).
- **SCOORD(2D) + SCOORD3D(3D, v13.22)** — AI/외부 producer는 2D 픽셀좌표(total pixel matrix). **뷰어 드로잉
  producer는 3D**(슬라이드 mm, ROI의 네이티브 `scoord3d`) — `coordinate_type` 파라미터로 선택. 3D는 source
  WSI의 FrameOfReferenceUID 요구, highdicom가 동일평면(coplanar) 주석을 2D+`CommonZCoordinateValue`로 최적화
  저장(dicom-microscopy-viewer 지원 형식). POLYGON 닫힘점(첫==끝)은 백엔드가 방어적 제거.

## 5. 검증
**생성(create)** — 라이브: radiologist 생성(POLYGON+POINT 2그룹)→ANN SOPClass …91.1·Modality=ANN·
AnnotationGroupSequence=2, WSI study에 SM+ANN 2시리즈. RESEARCHER POST 403. WADO-RS 시리즈 메타데이터에
그룹 2개·좌표(PointCoordinatesData OF, 인라인) 정상 응답 — **검증 완료**.

**표시(display) — v13.21 정합**: v13.20 시점에는 표시가 실제로 동작하지 않았음(정정). 라이브 실측으로 두 결함 확인·수정:
- **① ANN 오버레이 디스플레이셋 미인식/미로드** — `DicomMicroscopyViewport.tsx`가 `displaySets[0]`이 오버레이일
  때만 `load()`를 호출 → ANN이 뷰포트에 명시 추가되지 않으면 표시 안 됨(microscopy 모드는 좌측 패널 닫힘).
  콘솔 `No instances in {ANN displaySet}` 경고 발생. → **수정**: WSI(SM) 열 때 같은 study의 오버레이
  디스플레이셋을 열거해 자동 `load()`. 실측 결과 ANN이 검사 패널에 시리즈로 인식되고(`ANN S:201`),
  `No instances in` 경고 소멸, `loadAnnotation`이 종단 실행(ANN 시리즈 metadata fetch·`addAnnotationGroups`
  호출·인라인 좌표 사용, 에러 0).
- **② `bulkDataURI: enabled:false`** — 좌표가 벌크데이터로 저장된 대용량 주석 조회 차단. → `enabled:true`.
  (단, 소용량 주석은 Orthanc가 좌표를 인라인 반환하므로 이 경우엔 무관.)

**미완(실 WSI 게이트)**: 위 두 수정 후에도 합성 최소 WSI(단일 256px 타일)에서는 폴리곤/포인트가 **화면에
그려지지 않음**. 원인은 주석 코드가 아니라 합성 WSI의 **퇴화한 뷰어 기하** — dicom-microscopy-viewer(0.48.17)
OpenLayers 뷰가 줌 불가(20회 wheel 무반응)·프레임 카운터 `NaN`·`WSIViewport.setCamera`의 `setResolution`
undefined 에러. dicom-microscopy-viewer는 POLYGON 주석을 **고배율에서만** 로드하는데(줌 게이트) 뷰 자체가
줌되지 않아 게이트가 영영 미충족. **다중해상도 실 WSI(병리 스캐너 출력)로 최종 렌더 확인이 남은 게이트.**
create 경로·디스플레이셋 인식·loadAnnotation 종단 실행은 정합 완료.

## 6. 인터랙티브 그리기→저장 (v13.22)
```
[병리의] microscopy 모드 우패널 → 드로잉 도구(폴리곤/포인트/freehand, OHIF 기존재)로 마킹
    → "DICOM 주석 저장(ANN)" 버튼 → microscopyService.getAnnotationsForStudy → ROI별 scoord3d
    → POST /api/v1/pathology/{study}/annotations {coordinate_type:"3D", groups:[{label,graphic_type,coordinates}]}
    → highdicom ANN(3D, coplanar 최적화) → Orthanc → (재열람 시) DicomMicroscopyANN 표시
```
- **뷰어**: `MicroscopyPanel.tsx`에 `saveAsAnn` + 버튼(`data-cy=save-microscopy-ann`). ROI 1개 = 주석 그룹 1개
  (라벨+geometry). `pacs_token`으로 인증 POST. 성공/실패 토스트(`uiNotificationService`).
- **검증**: 백엔드 2D+3D create IT 8/8(`scripts/server/it-pathology-ann.sh` — coordType 3D·FoR·CommonZ·닫힘점
  제거). 뷰어 버튼은 microscopy 모드 우패널에 표시 확인(라이브). ★**드로잉 자체의 종단 저장은 실 WSI 게이트**
  (합성 WSI는 뷰어 기하 퇴화로 드로잉/줌 불가 — §5 표시 게이트와 동일 원인).

## 7. 잔여/후속 (수요 게이트)
- 실 WSI로 드로잉→저장→표시 종단 확인(LIS 병리 슬라이드 유입 시).
- Measurements(면적·개수) 연계, 세그멘테이션 마스크(bitmap) 주석.
- 계산병리 AI 모델 도입 시 대량주석 성능(스트리밍/청크).

## 참조
- [Sup 222](https://www.dicomstandard.org/docs/librariesprovider2/dicomdocuments/sup222_pc_wsiannotations88f52878-287c-4356-b3bb-72dbbb1dad89.pdf) · `docs/dicom-tech-review-2026.md` · `docs/releases/v13.20.md` · `docs/releases/v13.21.md` · `docs/releases/v13.22.md`
