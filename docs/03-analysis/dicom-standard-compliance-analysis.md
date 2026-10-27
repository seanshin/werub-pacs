# DICOM 표준 적합성 검토·분석

**작성일**: 2026-06-06
**대상**: WeRU.B PACS 전체 DICOM 처리 (저장·전송·생성·검증·정규화·익명화)
**근거**: 실제 코드 정독 + `docs/dicom-conformance-statement.md` 대조 + 운영 Orthanc 설정
**관련**: [[dicom_ai_standard_compliance]], v10.1 표준 SR 작업

---

## 0. 핵심 요약

DICOM 적합성을 **3개 층위**로 평가했다.

| 층위 | 적합성 | 평가 |
|---|:---:|---|
| **전송·저장** (Orthanc SCP/DICOMweb) | 🟢 강함 | 성숙한 Orthanc 1.12.11 + GDCM, 표준 SOP/전송구문/DICOMweb 광범위 지원 |
| **객체 생성** (앱이 만드는 SR/SEG) | 🟢 SR 표준화됨 / 🟡 SEG 미가동 | v10.1에서 TID 1500 SR + 텍스트 SR 표준 구현. SEG는 빌더 있으나 분할모델 없어 미생성 |
| **비표준 처리** (검증·정규화·익명화) | 🟢 강함 (차별점) | PS3.3/3.5 검증, JFIF 밀도 교정, PS3.15 익명화 |

**주요 발견**: 적합성 선언문과 실제 구현 사이 **3건의 불일치**(SR SOP Class, SEG/KOS 생성, TID 1500 미문서화)가 있으며, 선언문 갱신이 필요하다. 핵심 기능(비표준 DICOM 검증·정규화)은 표준 기반으로 견고하다.

---

## 1. 전송·저장 적합성 (Orthanc)

`docs/dicom-conformance-statement.md`가 문서화한 대로:
- **Storage SCP (C-STORE)**: CT/MR/CR/DX/US/NM/SC/MG/Enhanced/RT/SEG/SR/KOS 등 표준 SOP Class 수락. Orthanc는 모든 SOP Class C-STORE 수락.
- **Query/Retrieve**: Patient/Study Root C-FIND/C-MOVE/C-GET, C-ECHO.
- **Transfer Syntax**: 49종 (Implicit/Explicit VR, JPEG Baseline~2000, JPEG-LS, RLE, MPEG, HTJ2K).
- **DICOMweb**: QIDO-RS/WADO-RS/STOW-RS/WADO-URI.
- **문자집합**: ISO_IR 100/101/149/192(기본 UTF-8)/GB18030/JIS.

### 검증된 사실 (운영 설정)
- `orthanc.json: IngestTranscoding = "1.2.840.10008.1.2.1"` → **수신 객체를 Explicit VR LE로 전사**(저장 정규화). 비표준 Retired SOP/TS 호환성 확보.
- `DefaultEncoding = Utf8`, `DicomScuPreferredTransferSyntax = Explicit VR LE`.

→ **이 층위는 성숙·견고.** Orthanc가 표준 준수의 핵심을 담당.

---

## 2. 객체 생성 적합성 (앱이 만드는 DICOM)

### 2.1 AI 결과 SR — ✅ 표준 (v10.1)
- `dicom_ai_standard.build_ai_sr`: **Comprehensive SR (1.2.840.10008.5.1.4.1.1.88.33)** + **TID 1500 Measurement Report**. AI 알고리즘을 Device Observer(TID 1004), DCM 코드 신뢰도(Probability 122157), 근거영상 Evidence Sequence.
- `build_text_sr`: 자유 텍스트 판독을 Comprehensive SR(88.33) TEXT 컨텐츠로, UTF-8(ISO_IR 192) 한글 보존.
- 로컬 개념(Severity 등)은 **사설 코딩스킴 `99OPENPACS`**(PS3.16 적합) — DCM 코드 날조 회피.
- **운영 검증 완료**: 생성→Orthanc 저장→DICOMweb 조회→뷰어 렌더 E2E.

### 2.2 SEG — 🟡 빌더 표준, 생성 미가동
- `build_ai_seg`: 표준 Segmentation(66.4), highdicom 기반. 그러나 **현재 활성 모델이 전부 분류(classification) → 마스크 미출력 → SEG 0개 생성.** 분할 모델 도입 시 가동.

### 2.3 익명화 — ✅ 표준 프로파일
- `anonymize.py`: **DICOM Sup 142 (Basic Application Level Confidentiality Profile, 현 PS3.15)** 기반. Orthanc 내장 익명화 + PHI 태그 치환, salt 기반 일관 해시 ID. study_date/modality/body_part 선택 보존.

---

## 3. 비표준 DICOM 처리 (차별 기능) — ✅ 강함

### 3.1 검증엔진 (`dicom_validator.py`)
표준 요구사항 기반 22규칙:
- **PS3.5**: UID 형식(≤64자, 유효문자), VR 적합성(DATE/IS), 문자집합.
- **PS3.3**: 필수태그(Type 1) MISSING/EMPTY, 권장태그(Type 2).
- **전송구문** 검사, **PARSE_FAILURE**.
- **JPEG_DENSITY_MISMATCH** ⭐ — JFIF Xdensity/Ydensity vs DICOM Pixel Spacing 교차검증 (사용자 강조: 측정값 오류 직결).

### 3.2 정규화 (`dicom_normalizer.py`)
- **JFIF 밀도 → Pixel Spacing 교정**: JPEG 픽셀데이터의 JFIF 헤더(density_unit/Xdensity/Ydensity) 파싱 → `PixelSpacing = 25.4/DPI`(DPI) 또는 `10/density`(dots/cm) 계산. PS3.3 C.7.6.3.1.1 Pixel Spacing 의미 보존.
- Photometric/Charset 정규화.

→ **이 층위가 프로젝트의 표준 차별점.** 실무 유입 비표준 영상(밀도 조작 등)을 표준 의미로 교정.

---

## 4. 적합성 선언문 ↔ 구현 불일치 (갱신 필요)

| # | 선언문 | 실제 | 조치 |
|---|---|---|---|
| **D1** | SR = **88.11 (Basic Text SR)** (line 54) | 앱은 **88.33 (Comprehensive SR) + TID 1500** 생성 | 선언문에 88.33 추가 + TID 1500/관찰자/근거영상 명시 |
| **D2** | SEG (66.4) ✅ | Orthanc 저장은 수락하나 **앱은 SEG 미생성**(분할모델 부재) | "저장 수락 ✅ / 생성 보류(분할모델 선행)" 구분 표기 |
| **D3** | Key Object Selection (88.59) ✅ | 저장 수락하나 **앱은 KOS 미생성**(Key Image 기능 미구현) | 동일 — 저장/생성 구분 |

> 선언문은 **Storage SCP(수락) 관점**이라 D2/D3는 기술적으로 틀리지 않으나(Orthanc가 수락), "생성 능력"과 혼동 소지. SaMD 규제 제출 시 **수락 vs 생성**을 명확히 구분해야 함.

---

## 5. 갭 / 규제(MFDS) 고려사항

- **DICOM TLS (DIMSE over TLS) 미지원**(선언문 line 154) — 파일럿은 LAN C-STORE 평문이 관행이나, 보안상 향후 TLS 권장. ([[deploy_topology_20260605]] 네트워크와 연계)
- **TID 1500 SR의 IHE AIR(AI Results) 정합성** — 현재 SR은 IHE AIR 프로파일 방향과 일치(TID 1500 + Device Observer + 근거영상). **SEG 가동 시 AIR 완성도↑**. SaMD AI 결과의 표준 인코딩 근거로 활용 가능.
- **PS3.2 정식 적합성 선언문** — 현 문서는 간이형(요약표). 정식 제출 시 AE/Association/SOP별 동작·확장협상 등 상세 섹션 보강 필요.
- **Storage Commitment / MWL / MPPS 미지원**(선언문 line 155-157) — API로 대체. 워크플로우 표준 연동이 필요한 기관엔 갭.
- **익명화 PS3.15 프로파일 옵션** — 현재 Basic 프로파일. 픽셀 내 번인(Burned-in Annotation) 제거, UID 재매핑 일관성 등 추가 옵션 검토 가능.

---

## 6. 결론·권장

**전반적으로 DICOM 표준 적합성은 양호**하다. 전송·저장은 Orthanc로 견고하고, 비표준 처리(검증·정규화)는 표준 기반으로 잘 구현됐으며, v10.1에서 AI SR 생성이 TID 1500 표준으로 정합화됐다.

### 권장 (우선순위)
1. ✅ **적합성 선언문 갱신 완료** (2026-06-06) — `dicom-conformance-statement.md` v1.2: SR 88.33/TID 1500 반영, §2.1 수락(SCP) vs 생성(Origin) 구분 신설.
2. **분할 모델 도입 → SEG 가동** — IHE AIR 완성, 표준 SEG 생성 실증.
3. ✅ **정식 PS3.2 §4 상세화 완료** (2026-06-06) — 선언문 부록 A: Implementation Model / AE Specification(Association 정책·접근제어) / Network Interfaces / Configuration / Security Profiles.
4. ✅ **갭 로드맵화 완료** (2026-06-06) — §7 참조.

> 즉시 가치: **#1(선언문 갱신)** — 코드는 이미 88.33/TID 1500을 생성하므로, 문서만 실제에 맞추면 규제 정합성이 올라간다.

---

## 7. 표준 갭 로드맵 (미지원 항목 우선순위)

현재 미지원 DICOM 표준 기능을 **임상·규제 가치 vs 노력**으로 우선순위화. "트리거"는 해당 기능이 실제로 필요해지는 시점.

| 갭 | 가치 | 노력 | 트리거 (언제 필요) | 접근 |
|---|:---:|:---:|---|---|
| **SEG 생성** (66.4) | ★★★ | 중 | 분할 AI 모델 도입 시 | 빌더(`build_ai_seg`) 이미 존재 → 마스크 출력 모델만 연결. IHE AIR 완성 |
| **MWL SCP** (Modality Worklist) | ★★★ | 중 | 모달리티가 PACS에서 워크리스트 조회 필요 시(촬영실 자동 환자정보) | 현재 HIS 연동 API로 대체. Orthanc worklist 플러그인 또는 dcm4che 검토 |
| **Key Object Selection 생성** (88.59) | ★★ | 하 | 판독의 핵심영상 마킹(Key Image) 기능 요구 시 | 뷰어 P2-4 연계. KOS 빌더 추가 |
| **DICOM TLS** (DIMSE over TLS) | ★★ | 중 | 외부기관·인터넷 경유 DIMSE 필요 시 (LAN 내부는 낮음) | Orthanc TLS 설정 + 인증서. 현재 LAN/SSH터널 대체 |
| **Storage Commitment** (N-EVENT-REPORT SCP) | ★★ | 중 | 모달리티가 저장 확약 요구 시(전송 신뢰성 보증) | Orthanc는 SCP 미지원 → 플러그인/dcm4che 검토 |
| **MPPS** (Performed Procedure Step) | ★ | 중 | RIS 워크플로우 통합(촬영 상태 추적) 필요 시 | API 워크플로우로 부분 대체 중 |
| **UPS** (Unified Procedure Step) | ★ | 상 | 차세대 워크플로우(UPS-RS) 요구 시 | 장기 |
| **DICOM Print** (Film) | — | — | 필름 출력 요구 시(현재 대부분 obsolete) | 보류 |
| **익명화 고급 옵션** | ★ | 하 | 픽셀 번인 제거·UID 재매핑 일관성 요구 시 | PS3.15 추가 프로파일 옵션화 |

### 권장 진행 순서
1. **SEG 생성** (분할 모델 확보 시) — 빌더 준비됨, IHE AIR/SaMD 가치 높음.
2. **MWL SCP** (촬영실 워크플로우 표준화 필요 시) — 임상 운영 가치 높음.
3. **KOS 생성** (Key Image 기능과 함께) — 저노력.
4. **DICOM TLS / Storage Commitment** (외부 연동·신뢰성 요구 시).
5. MPPS/UPS/Print — 기관 요구 발생 시.

> 대부분은 **트리거 기반**(실제 필요 시점 도래) 항목으로, 현 단일기관 파일럿 범위에선 API/대체수단으로 충분. SEG만 AI 표준화(IHE AIR) 완성을 위해 우선 가치가 높다.
