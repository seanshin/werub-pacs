# DICOM Conformance Statement — OpenPACS / WeRU.B

**제품명**: WeRU.B PACS  
**버전**: v1.2 (개정 2026-06-06)  
**작성일**: 2026-05-18 / **개정**: 2026-06-06  
**DICOM 표준**: DICOM PS3 (2024b)  
**기반 소프트웨어**: Orthanc 1.12.11, WeRU.B Viewer (OHIF v3.12)

> **개정 이력 (2026-06-06)**: §2 SR을 88.11→88.33(Comprehensive SR) 정정·추가, §2.1 *수락(SCP) vs 생성(Origin)* 구분 신설 (AI 결과 SR = TID 1500, SEG 보류, KOS 미생성). 근거: `docs/03-analysis/dicom-standard-compliance-analysis.md`.

---

## 1. 시스템 개요

OpenPACS는 웹 기반 의료영상저장전송장치(PACS)로, DICOM 표준을 준수하여 의료 영상의 저장, 전송, 조회를 지원합니다.

| 구성요소 | 역할 | DICOM 역할 |
|---------|------|-----------|
| Orthanc Server | DICOM 서버 | SCP (C-STORE, C-FIND, C-MOVE, C-GET, C-ECHO) |
| WeRU.B Viewer | 웹 영상 뷰어 | DICOMweb Consumer (WADO-RS, QIDO-RS) |
| FastAPI Backend | API 서버 | DICOMweb Proxy |

### 네트워크 구성

| 항목 | 값 |
|------|-----|
| AE Title | `OPENPACS` |
| DICOM Port | 4242 |
| HTTP Port | 8042 (내부) |
| DICOMweb URL | `https://his.example.org/dicom-web/` |
| WADO-URI URL | `https://his.example.org/wado` |

---

## 2. 지원 SOP Class (Storage SCP)

### 영상 저장 (C-STORE SCP)

| SOP Class | UID | 지원 |
|-----------|-----|:----:|
| CT Image Storage | 1.2.840.10008.5.1.4.1.1.2 | ✅ |
| MR Image Storage | 1.2.840.10008.5.1.4.1.1.4 | ✅ |
| CR Image Storage | 1.2.840.10008.5.1.4.1.1.1 | ✅ |
| Digital X-Ray (DX) | 1.2.840.10008.5.1.4.1.1.1.1 | ✅ |
| US Image Storage | 1.2.840.10008.5.1.4.1.1.6.1 | ✅ |
| US Multi-frame | 1.2.840.10008.5.1.4.1.1.3.1 | ✅ |
| NM Image Storage | 1.2.840.10008.5.1.4.1.1.20 | ✅ |
| Secondary Capture (SC) | 1.2.840.10008.5.1.4.1.1.7 | ✅ |
| Digital Mammography (MG) | 1.2.840.10008.5.1.4.1.1.1.2 | ✅ |
| Enhanced CT | 1.2.840.10008.5.1.4.1.1.2.1 | ✅ |
| Enhanced MR | 1.2.840.10008.5.1.4.1.1.4.1 | ✅ |
| RT Dose | 1.2.840.10008.5.1.4.1.1.481.2 | ✅ |
| RT Structure Set | 1.2.840.10008.5.1.4.1.1.481.3 | ✅ |
| RT Plan | 1.2.840.10008.5.1.4.1.1.481.5 | ✅ |
| Segmentation (SEG) | 1.2.840.10008.5.1.4.1.1.66.4 | ✅ |
| Basic Text SR | 1.2.840.10008.5.1.4.1.1.88.11 | ✅ |
| Comprehensive SR | 1.2.840.10008.5.1.4.1.1.88.33 | ✅ |
| Key Object Selection | 1.2.840.10008.5.1.4.1.1.88.59 | ✅ |

> Orthanc는 모든 표준 SOP Class의 C-STORE를 **수락(Storage SCP)**합니다.
> 본 표는 *수락* 능력이며, 아래 §2.1은 본 시스템이 *생성*하는 객체를 구분합니다.

### 2.1 본 시스템이 생성하는 DICOM 객체 (Origin)

| 객체 | SOP Class | 표준 | 생성 |
|------|-----------|------|:----:|
| **AI 결과 SR** | Comprehensive SR (88.33) | **TID 1500 Measurement Report** — AI 알고리즘을 Device Observer(TID 1004), DCM 코드 신뢰도(Probability 122157), 근거영상 Evidence Sequence | ✅ |
| **판독 텍스트 SR** | Comprehensive SR (88.33) | TEXT 컨텐츠, UTF-8(ISO_IR 192) 한글 | ✅ |
| **익명화 객체** | (원본 SOP 유지) | DICOM Sup 142 / PS3.15 Basic Confidentiality Profile | ✅ |
| **AI 분할 SEG** | Segmentation (66.4) | highdicom 표준 빌더 구현 | ⏸ **보류** (분할 모델 도입 선행 — 현 모델은 분류형) |
| **Key Object Selection** | KOS (88.59) | highdicom — 핵심영상 마킹("Of Interest" 113000), KO 모달리티 | ✅ (POST /api/v1/reports/key-images) |
| **MWL / MPPS / Storage Commitment** | (DIMSE 워크플로) | pynetdicom SCP — C-FIND / N-CREATE·N-SET / N-ACTION·N-EVENT-REPORT | ✅ (AE OPENPACS-MWL:4243) |

> **수락(SCP) ≠ 생성(Origin)**: SEG는 Orthanc가 C-STORE로 *수락·저장*하나 분할 모델 부재로 *생성*은 보류. KOS는 2026-06-06부터 *생성* 지원. 로컬 개념은 사설 코딩스킴 `99OPENPACS`(PS3.16 적합)로 인코딩합니다.

### Query/Retrieve (C-FIND/C-MOVE/C-GET SCP)

| SOP Class | UID | 지원 |
|-----------|-----|:----:|
| Patient Root Q/R Find | 1.2.840.10008.5.1.4.1.2.1.1 | ✅ |
| Patient Root Q/R Move | 1.2.840.10008.5.1.4.1.2.1.2 | ✅ |
| Patient Root Q/R Get | 1.2.840.10008.5.1.4.1.2.1.3 | ✅ |
| Study Root Q/R Find | 1.2.840.10008.5.1.4.1.2.2.1 | ✅ |
| Study Root Q/R Move | 1.2.840.10008.5.1.4.1.2.2.2 | ✅ |
| Study Root Q/R Get | 1.2.840.10008.5.1.4.1.2.2.3 | ✅ |
| Verification (C-ECHO) | 1.2.840.10008.1.1 | ✅ |

---

## 3. 지원 Transfer Syntax

| Transfer Syntax | UID | 설명 |
|-----------------|-----|------|
| Implicit VR Little Endian | 1.2.840.10008.1.2 | DICOM 기본 |
| Explicit VR Little Endian | 1.2.840.10008.1.2.1 | 권장 기본 |
| Explicit VR Big Endian | 1.2.840.10008.1.2.2 | 레거시 |
| Deflated Explicit VR LE | 1.2.840.10008.1.2.1.99 | 압축 |
| JPEG Baseline (Process 1) | 1.2.840.10008.1.2.4.50 | 손실 JPEG |
| JPEG Extended (Process 2&4) | 1.2.840.10008.1.2.4.51 | 확장 JPEG |
| JPEG Lossless (Process 14) | 1.2.840.10008.1.2.4.57 | 무손실 JPEG |
| JPEG Lossless SV1 | 1.2.840.10008.1.2.4.70 | 무손실 JPEG (권장) |
| JPEG-LS Lossless | 1.2.840.10008.1.2.4.80 | 무손실 |
| JPEG-LS Lossy | 1.2.840.10008.1.2.4.81 | 준무손실 |
| JPEG 2000 Lossless | 1.2.840.10008.1.2.4.90 | 무손실 J2K |
| JPEG 2000 | 1.2.840.10008.1.2.4.91 | 손실 J2K |
| MPEG2 | 1.2.840.10008.1.2.4.100 | 동영상 |
| MPEG4 AVC/H.264 | 1.2.840.10008.1.2.4.101~108 | 동영상 |
| RLE Lossless | 1.2.840.10008.1.2.5 | 무손실 |
| HTJ2K Lossless | 1.2.840.10008.1.2.4.201 | 차세대 무손실 |
| HTJ2K | 1.2.840.10008.1.2.4.202~203 | 차세대 |

> 총 49개 Transfer Syntax 지원 (Orthanc 1.12.11 + GDCM)

---

## 4. DICOMweb 지원

| 서비스 | 경로 | 지원 |
|--------|------|:----:|
| QIDO-RS (검색) | `/dicom-web/studies` | ✅ |
| WADO-RS (조회) | `/dicom-web/studies/{uid}` | ✅ |
| STOW-RS (저장) | `/dicom-web/studies` (POST) | ✅ |
| WADO-URI (레거시) | `/wado?requestType=WADO&...` | ✅ |

### DICOMweb 쿼리 파라미터

| 파라미터 | 지원 |
|---------|:----:|
| StudyInstanceUID | ✅ |
| PatientName | ✅ (와일드카드) |
| PatientID | ✅ |
| StudyDate | ✅ |
| ModalitiesInStudy | ✅ |
| AccessionNumber | ✅ |
| limit, offset | ✅ |

---

## 5. 문자 집합 지원

| Character Set | 설명 | 지원 |
|--------------|------|:----:|
| ISO_IR 100 | Latin1 (서유럽) | ✅ |
| ISO_IR 101 | Latin2 (동유럽) | ✅ |
| ISO_IR 149 | KS X 1001 (한국어) | ✅ |
| ISO_IR 192 | UTF-8 (유니코드) | ✅ (기본) |
| GB18030 | 중국어 간체 | ✅ |
| ISO 2022 IR 87 | JIS X 0208 (일본어) | ✅ |

> Orthanc 기본 인코딩: UTF-8 (`ORTHANC__DEFAULT_ENCODING: Utf8`)

---

## 6. 보안

| 항목 | 지원 |
|------|:----:|
| DICOM TLS (DIMSE) | ❌ (향후) |
| DICOMweb HTTPS | ✅ (TLS 1.3, Let's Encrypt) |
| DICOMweb 인증 | ✅ (Basic Auth via Nginx) |
| JWT 인증 (API) | ✅ |
| RBAC 역할 기반 접근 | ✅ (5개 역할) |
| 감사 로그 | ✅ |

---

## 7. 제한사항

| 항목 | 상태 |
|------|------|
| DICOM TLS (DIMSE over TLS) | 미지원 (SSH 터널로 대체) |
| Storage Commitment (N-EVENT-REPORT) | 미지원 |
| Modality Worklist (MWL SCP) | 미지원 (API로 대체) |
| MPPS (Modality Performed Procedure Step) | 미지원 |
| UPS (Unified Procedure Step) | 미지원 |
| DICOM Print | 미지원 |

---

## 8. 연동 검증 완료 뷰어

| 뷰어 | 연결 방식 | 상태 |
|------|----------|:----:|
| WeRU.B Viewer (웹) | DICOMweb (WADO-RS, QIDO-RS) | ✅ |
| OHIF Viewer (웹) | DICOMweb (WADO-RS, QIDO-RS) | ✅ |
| Horos (macOS) | DICOM C-FIND/C-MOVE (SSH 터널) | ✅ |

---

## 부록 A. 정식 PS3.2 상세 적합성 (Networking)

> 본 부록은 DICOM PS3.2 §4(Networking) 구조에 따른 상세 명세이다. DIMSE 동작은 Orthanc 1.12.11(`docker/orthanc/orthanc.json`) 기준이며, 명시되지 않은 항목은 Orthanc 기본값을 따른다.

### A.1 Implementation Model

**A.1.1 Application Data Flow**
```
[원격 모달리티/PACS] --C-STORE/C-FIND/C-MOVE/C-ECHO--> (DICOM 4242) [WeRU.B PACS AE: OPENPACS]
                                                                          |
[웹 뷰어/HIS] --QIDO/WADO/STOW-RS (HTTPS)--> (Nginx 443 → 8042) ----------+--> [PostgreSQL Index]
                                                                          +--> [파일 스토리지]
```

**A.1.2 Functional Definition of AE — `OPENPACS`**
단일 응용엔티티 `OPENPACS`가 다음 역할을 수행한다:
- **Storage SCP** — C-STORE 수신·저장 (수신 시 Explicit VR LE로 전사).
- **Query/Retrieve SCP** — Study/Patient Root C-FIND/C-MOVE/C-GET.
- **Storage SCU / Q-R SCU** — 등록 피어로 C-STORE 송신, C-MOVE/C-FIND.
- **Verification SCP/SCU** — C-ECHO.

**A.1.3 Sequencing** — 동기. Storage SCP는 수신 즉시 인덱싱; `StableAge=10s` 후 Study를 Stable로 표기(검증/AI 트리거).

### A.2 AE Specification — `OPENPACS`

**A.2.1 Association Establishment Policies**
| 항목 | 값 |
|------|-----|
| Application Context Name | 1.2.840.10008.3.1.1.1 |
| Maximum PDU Length (수신) | 16384 (Orthanc 기본, `MaximumPduLength`로 조정) |
| Max 동시 Association | `DicomThreadsCount = 4` |
| 비동기 작업(Async Operations) | 미지원 (동기) |
| Called AE Title 검증 | **미검사** (`DicomCheckCalledAet=false`) — 임의 Called AET 수락 |
| Implementation Class UID | Orthanc 할당 |

**A.2.2 Association Acceptance Policies (SCP)**
- **수락 SOP Class**: §2 표의 모든 Storage SOP Class + Q/R + Verification. Orthanc는 표준 Storage SOP Class를 광범위 수락.
- **Transfer Syntax 협상**: §3의 49종 제안 수락; 저장은 `IngestTranscoding=Explicit VR LE`로 전사. SCU 송신 선호 구문 = Explicit VR LE.
- **접근 제어 (Real-World Activity별)**:
  | 활동 | 정책 |
  |------|------|
  | C-ECHO (Verification) | **항상 허용** (`DicomAlwaysAllowEcho=true`) |
  | C-STORE | 등록 모달리티(`DicomModalities`)만 (`DicomAlwaysAllowStore=false`) |
  | C-FIND / C-MOVE / C-GET | 등록 모달리티만 (각 `false`) |
  → 파일럿 시 송신 장비를 `DicomModalities`에 등록해야 함 (`docs/cstore-pilot-readiness.md`).

**A.2.3 Association Initiation Policies (SCU)**
- 등록 피어로 C-STORE(`/peers`, `/modalities/{aet}/store`), C-FIND/C-MOVE 개시. 자격증명은 암호화 저장(`app/core/crypto.py`).

### A.3 Network Interfaces
- **DIMSE**: TCP 4242 (127.0.0.1 바인딩 — 파일럿 시 장비 IP에 한해 노출).
- **DICOMweb/REST**: TCP 8042 (Nginx 443 TLS 1.3 프록시, Basic Auth 주입).
- **물리 매체**: TCP/IP over Ethernet.

### A.4 Configuration
| 파라미터 | 값 | 출처 |
|----------|-----|------|
| AE Title | `OPENPACS` | `DicomAet` |
| DICOM Port | 4242 | `DicomPort` |
| HTTP Port | 8042 | `HttpPort` |
| 동시 Association | 4 | `DicomThreadsCount` |
| Ingest 전사 | Explicit VR LE | `IngestTranscoding` |
| 기본 인코딩 | UTF-8 | `DefaultEncoding=Utf8` |
| 최대 저장 용량 | 무제한 | `MaximumStorageSize=0` |

### A.5 Security Profiles
- **DIMSE**: DICOM TLS 미지원 (LAN/SSH 터널). 접근 제어 = AE 화이트리스트.
- **DICOMweb**: TLS 1.3 + Nginx Basic Auth + 앱 JWT/RBAC.
- **De-identification**: PS3.15 Basic Application Level Confidentiality Profile (§2.1).

---

*본 문서는 DICOM PS3.2 (Conformance) 형식에 따라 작성되었으며, 부록 A는 §4(Networking) 상세 명세이다.*  
*Based on Orthanc 1.12.11 — https://www.orthanc-server.com · 분석 근거: docs/03-analysis/dicom-standard-compliance-analysis.md*
