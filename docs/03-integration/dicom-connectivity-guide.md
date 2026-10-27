# DICOM 모달리티 연결 가이드

> **대상**: 영상의학과 기사, IT 관리자

---

## 1. OpenPACS DICOM 서버 정보

| 항목 | 값 |
|------|-----|
| **IP** | 198.51.100.73 |
| **Port** | 4242 |
| **AE Title** | OPENPACS |
| **Protocol** | DICOM 3.0 (DIMSE) |
| **지원 서비스** | C-ECHO, C-STORE SCP, C-FIND SCP, C-MOVE SCP |

---

## 2. 모달리티 장비 설정

### 2.1 CT 장비 (예: Siemens, GE, Philips)
```
Remote DICOM Node:
  AE Title:  OPENPACS
  Host/IP:   198.51.100.73
  Port:      4242

Local AE Title: CT_ROOM1 (장비별 고유 이름)
```

### 2.2 MRI 장비
```
Remote DICOM Node:
  AE Title:  OPENPACS
  Host/IP:   198.51.100.73
  Port:      4242

Local AE Title: MR_ROOM1
```

### 2.3 CR/DR 장비
```
Remote DICOM Node:
  AE Title:  OPENPACS
  Host/IP:   198.51.100.73
  Port:      4242

Local AE Title: CR_ROOM1
```

---

## 3. 연결 테스트

### 3.1 장비에서 C-ECHO
대부분의 모달리티 장비에 "연결 테스트" 또는 "DICOM Ping" 기능이 있습니다.
OPENPACS로 C-ECHO를 보내서 "Success" 응답을 확인하세요.

### 3.2 서버에서 확인
```bash
# Orthanc Explorer에서 확인
https://his.example.org/pacs/ → (admin / ORTHANC_PASSWORD 로 정한 값)
→ Modalities 메뉴에서 장비 등록 및 C-ECHO 테스트

# API로 확인
curl -u admin:ORTHANC_PASSWORD 로 정한 값 -X POST \
  http://localhost:8042/modalities/{모달리티이름}/echo
```

---

## 4. 워크리스트 (MWL) 연동

### 4.1 장비 설정
```
Worklist Server:
  AE Title:  OPENPACS
  Host/IP:   198.51.100.73
  Port:      4242
```

### 4.2 워크플로우
1. HospitalRun에서 검사 오더 생성
2. OpenPACS 워크리스트에 자동 등록
3. 모달리티 장비에서 워크리스트 조회 (환자 목록 표시)
4. 환자 선택 → 촬영 → 자동으로 MRN이 DICOM PatientID에 입력됨
5. 촬영 완료 → C-STORE → OpenPACS 자동 수신

---

## 5. 지원 Transfer Syntax

| Transfer Syntax | 지원 |
|----------------|:----:|
| Explicit VR Little Endian | ✅ |
| Implicit VR Little Endian | ✅ |
| JPEG Baseline (Lossy) | ✅ |
| JPEG Lossless | ✅ |
| JPEG 2000 | ✅ (GDCM 플러그인) |
| JPEG-LS | ✅ |

---

## 6. 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| C-ECHO 실패 | 방화벽 | 서버 4242/tcp 포트 확인 |
| C-STORE 실패 | AE Title 불일치 | OPENPACS 정확히 입력 (대문자) |
| 영상 안 보임 | 네트워크 | IP/Port 확인, 라우팅 확인 |
| 한글 깨짐 | 문자셋 | Specific Character Set ISO_IR 192 (UTF-8) 확인 |
