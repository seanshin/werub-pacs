# DICOM 영상 수집 허브 — API 연동 가이드

> **버전**: v9.2  
> **Base URL**: `https://his.example.org/pacs-api`  
> **작성일**: 2026-05-26  
> **총 API**: 21개 (업로드 12 + 외부 연동 9)

---

## 목차

1. [인증](#1-인증)
2. [관리자 파일 업로드](#2-관리자-파일-업로드)
3. [업로드 승인 큐](#3-업로드-승인-큐)
4. [환자 포털 (토큰 기반)](#4-환자-포털-토큰-기반)
5. [외부 PACS 연동](#5-외부-pacs-연동)
6. [에러 처리](#6-에러-처리)
7. [연동 시나리오별 예제](#7-연동-시나리오별-예제)

---

## 1. 인증

### 1.1 JWT 인증 (관리자/직원)

대부분의 API는 JWT Bearer Token이 필요합니다.

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "admin", "password": "****"}
```

```json
{
  "access_token": "CHANGE_ME",
  "refresh_token": "CHANGE_ME",
  "token_type": "bearer",
  "expires_in": 3600
}
```

이후 모든 요청에 헤더 추가:
```
Authorization: Bearer eyJhbGci...
```

### 1.2 토큰 인증 (환자 포털)

환자 포털 API는 JWT 대신 **1회성 업로드 토큰**을 사용합니다.

```
GET /api/v1/patient-upload/verify?token=CHANGE_ME
```

토큰은 관리자가 발급하며, 기본 24시간 유효합니다.

### 1.3 역할(Role) 요구사항

| 역할 | 설명 |
|------|------|
| `ADMIN` | 모든 API 접근 가능 |
| `TECHNOLOGIST` | 업로드, 승인 큐 |
| `RADIOLOGIST` | 업로드 (읽기) |
| *(public)* | 환자 포털 4개 API (토큰 인증) |

---

## 2. 관리자 파일 업로드

### 2.1 단일/다중 DICOM 파일 업로드

```http
POST /api/v1/upload/files
Content-Type: multipart/form-data
Authorization: Bearer {token}
```

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `auto_validate` | bool | `true` | DicomValidator 자동 실행 |
| `auto_normalize` | bool | `false` | DicomNormalizer 자동 수정 |
| `source` | string | `"admin"` | 출처 구분 (`admin`, `kiosk`, `research`) |

**Request Body:** `multipart/form-data`
- `files`: DICOM 파일 (복수)

**curl 예제:**
```bash
curl -X POST "https://his.example.org/pacs-api/api/v1/upload/files?auto_validate=true" \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@chest_001.dcm" \
  -F "files=@chest_002.dcm"
```

**Response (200):**
```json
{
  "ok": true,
  "uploaded": 2,
  "failed": 0,
  "total": 2,
  "results": [
    {
      "filename": "chest_001.dcm",
      "status": "uploaded",
      "orthanc_id": "a1b2c3d4-...",
      "validation": {
        "accepted": true,
        "max_severity": "warning",
        "counts": {"critical": 0, "error": 0, "warning": 1, "info": 2},
        "normalized": false
      }
    },
    {
      "filename": "chest_002.dcm",
      "status": "uploaded",
      "orthanc_id": "e5f6g7h8-...",
      "validation": null
    }
  ]
}
```

**결과 status 값:**

| status | 설명 |
|--------|------|
| `uploaded` | Orthanc 저장 성공 |
| `skipped` | DICOM이 아닌 파일 (magic byte 불일치) |
| `failed` | 업로드 실패 |

---

### 2.2 ZIP 파일 업로드

```http
POST /api/v1/upload/zip
Content-Type: multipart/form-data
Authorization: Bearer {token}
```

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `auto_validate` | bool | `true` | 검증 실행 |
| `source` | string | `"admin"` | 출처 |

**Request Body:** `multipart/form-data`
- `file`: ZIP 파일 (1개)

**curl 예제:**
```bash
curl -X POST "https://his.example.org/pacs-api/api/v1/upload/zip" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@patient_cd.zip"
```

**Response (200):**
```json
{
  "ok": true,
  "uploaded": 45,
  "skipped": 3,
  "failed": 0,
  "total_entries": 48
}
```

> **참고:** ZIP 내부에서 DICOM magic byte (`DICM` at offset 128)가 있는 파일만 업로드합니다. `__MACOSX` 디렉토리는 자동 제외됩니다.

---

## 3. 업로드 승인 큐

환자 포털/키오스크에서 올라온 파일은 직접 Orthanc에 저장되지 않고, **승인 큐**를 거칩니다.

### 3.1 승인 대기 목록 조회

```http
GET /api/v1/upload-queue?status=pending&page=1&page_size=20
Authorization: Bearer {token}
```

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `status` | string | `"pending"` | `pending`, `approved`, `rejected` |
| `page` | int | 1 | 페이지 번호 |
| `page_size` | int | 20 | 페이지 크기 (최대 100) |

**Response (200):**
```json
{
  "total": 3,
  "page": 1,
  "items": [
    {
      "id": "uuid-...",
      "source": "patient_portal",
      "source_detail": "token:abc123, patient:P001",
      "patient_id": "P001",
      "patient_name": "홍길동",
      "file_count": 5,
      "total_size_bytes": 15728640,
      "study_uids": ["1.2.840..."],
      "modalities": ["CT"],
      "validation_status": null,
      "status": "pending",
      "reject_reason": null,
      "created_at": "2026-05-26T10:00:00Z",
      "expires_at": "2026-05-29T10:00:00Z",
      "approved_at": null
    }
  ]
}
```

### 3.2 승인 (Orthanc에 저장)

```http
POST /api/v1/upload-queue/{queue_id}/approve
Authorization: Bearer {token}
```

**Response (200):**
```json
{
  "ok": true,
  "uploaded": 5,
  "queue_id": "uuid-..."
}
```

### 3.3 거부 (파일 삭제)

```http
POST /api/v1/upload-queue/{queue_id}/reject?reason=화질불량
Authorization: Bearer {token}
```

**Response (200):**
```json
{
  "ok": true,
  "queue_id": "uuid-..."
}
```

### 3.4 통계

```http
GET /api/v1/upload-queue/stats
Authorization: Bearer {token}
```

**Response (200):**
```json
{
  "by_status": {"pending": 3, "approved": 12, "rejected": 1},
  "pending_by_source": {"patient_portal": 2, "kiosk": 1}
}
```

---

## 4. 환자 포털 (토큰 기반)

> **인증 불필요** — 모든 API는 `token` 쿼리 파라미터로 인증합니다.  
> 외부 시스템(HIS, 접수 앱)에서 직접 호출 가능합니다.

### 4.1 토큰 발급 (관리자)

```http
POST /api/v1/patient-upload/token
Authorization: Bearer {admin_token}
Content-Type: application/json
```

**Request Body:**
```json
{
  "patient_id": "P001",
  "patient_name": "홍길동",
  "patient_birth_date": "19850315",
  "expires_hours": 24
}
```

**Response (200):**
```json
{
  "ok": true,
  "token": "Xa9bQ2kL...48자...",
  "url": "/patient-upload?token=CHANGE_ME",
  "expires_at": "2026-05-27T10:00:00Z"
}
```

> **활용:** 반환된 `url`을 환자에게 SMS/QR코드로 전달하거나, iframe으로 임베드합니다.
> ```
> https://his.example.org/pacs-admin/patient-upload?token=CHANGE_ME
> ```

### 4.2 발급 내역 조회 (관리자)

```http
GET /api/v1/patient-upload/tokens
Authorization: Bearer {admin_token}
```

**Response (200):**
```json
{
  "tokens": [
    {
      "id": "uuid-...",
      "token": "CHANGE_ME",
      "patient_id": "P001",
      "patient_name": "홍길동",
      "used": false,
      "consent_agreed": false,
      "expires_at": "2026-05-27T10:00:00Z",
      "created_at": "2026-05-26T10:00:00Z"
    }
  ]
}
```

### 4.3 토큰 검증 (Public)

```http
GET /api/v1/patient-upload/verify?token=CHANGE_ME
```

**Response — 유효:**
```json
{
  "valid": true,
  "patient_id": "P001",
  "patient_name": "홍길동",
  "consent_agreed": false
}
```

**Response — 만료/무효:**
```json
{
  "valid": false,
  "error": "Token expired"
}
```

| error 값 | 의미 |
|----------|------|
| `Invalid token` | 존재하지 않는 토큰 |
| `Token expired` | 만료됨 |
| `Token already used` | 이미 사용됨 (1회성) |

### 4.4 개인정보 동의 (Public)

```http
POST /api/v1/patient-upload/consent?token=CHANGE_ME
```

**Response (200):**
```json
{"ok": true}
```

> **필수 선행:** 동의 없이 파일 업로드 시 `"Privacy consent required"` 에러가 반환됩니다.

### 4.5 파일 업로드 (Public)

```http
POST /api/v1/patient-upload/files?token=CHANGE_ME
Content-Type: multipart/form-data
```

**Request Body:** `multipart/form-data`
- `files`: DICOM 파일, ZIP, 또는 JPEG/PNG (복수)

**지원 파일 형식:**

| 형식 | 처리 방식 |
|------|----------|
| `.dcm` / DICOM | 그대로 저장 |
| `.zip` | 내부 DICOM 파일 추출 |
| `.jpg` / `.jpeg` / `.png` | 이미지로 저장 (향후 DICOM SC 변환 예정) |
| 기타 | 무시 |

**Response (200):**
```json
{
  "ok": true,
  "files_saved": 5,
  "total_size": 15728640,
  "queue_id": "uuid-...",
  "message": "업로드 완료. 담당 의료진 승인 후 시스템에 등록됩니다."
}
```

> **중요:** 파일은 바로 Orthanc에 저장되지 않습니다.  
> 승인 큐(`upload_queue`)에 등록되며, 관리자가 `POST /upload-queue/{id}/approve`로 승인해야 합니다.

### 4.6 업로드 상태 확인 (Public)

```http
GET /api/v1/patient-upload/status?token=CHANGE_ME
```

**Response (200):**
```json
{
  "token_valid": false,
  "upload": {
    "status": "pending",
    "file_count": 5,
    "created_at": "2026-05-26T10:05:00Z"
  }
}
```

| upload.status | 의미 |
|---------------|------|
| `pending` | 관리자 승인 대기 중 |
| `approved` | 승인됨 — Orthanc에 저장 완료 |
| `rejected` | 거부됨 |
| `null` | 업로드 내역 없음 |

---

## 5. 외부 PACS 연동

### 5.1 피어/모달리티 목록

```http
GET /api/v1/remotes
Authorization: Bearer {token}
```

**Response (200):**
```json
{
  "remotes": [
    {
      "id": "uuid-...",
      "name": "서울대병원PACS",
      "remote_type": "modality",
      "url": null,
      "ae_title": "SNUH_PACS",
      "host": "192.168.1.50",
      "port": 4242,
      "enabled": true,
      "description": "서울대병원 영상의학과",
      "last_echo_at": "2026-05-26T09:00:00Z",
      "last_echo_status": "ok"
    }
  ]
}
```

### 5.2 피어/모달리티 등록

```http
POST /api/v1/remotes
Authorization: Bearer {token}
Content-Type: application/json
```

**Request Body:**

**DICOM Modality (DIMSE 프로토콜):**
```json
{
  "name": "2층 CT",
  "remote_type": "modality",
  "ae_title": "CT_2F",
  "host": "192.168.1.50",
  "port": 4242,
  "description": "2층 CT 장비"
}
```

**Orthanc Peer (HTTP REST):**
```json
{
  "name": "외부병원PACS",
  "remote_type": "peer",
  "url": "https://pacs.external.com/orthanc",
  "username": "openpacs",
  "password": "****",
  "description": "외부 병원 Orthanc 피어"
}
```

**Response (200):**
```json
{"ok": true, "id": "uuid-..."}
```

### 5.3 피어/모달리티 수정

```http
PUT /api/v1/remotes/{remote_id}
Authorization: Bearer {token}
Content-Type: application/json
```

Body 형식은 등록과 동일.

### 5.4 피어/모달리티 삭제

```http
DELETE /api/v1/remotes/{remote_id}
Authorization: Bearer {token}
```

### 5.5 연결 테스트 (C-ECHO)

```http
POST /api/v1/remotes/{remote_id}/echo
Authorization: Bearer {token}
```

**Response (200):**
```json
{
  "ok": true,
  "message": "C-ECHO OK"
}
```

| remote_type | 테스트 방식 |
|-------------|-----------|
| `modality` | DICOM C-ECHO |
| `peer` | HTTP GET /system |

### 5.6 영상 검색 (C-FIND)

```http
POST /api/v1/remotes/{remote_id}/query
Authorization: Bearer {token}
```

**Query Parameters:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `patient_name` | string | 환자명 (와일드카드 자동 적용) |
| `patient_id` | string | 환자번호 |
| `study_date` | string | 검사일 `YYYYMMDD` 또는 범위 `20260101-20260531` |
| `modality` | string | 모달리티 (`CT`, `MR`, `CR` 등) |

**curl 예제:**
```bash
curl -X POST "https://his.example.org/pacs-api/api/v1/remotes/{id}/query?patient_name=홍길동&modality=CT" \
  -H "Authorization: Bearer $TOKEN"
```

**Response (200):**
```json
{
  "results": [
    {
      "answer_id": "0",
      "query_id": "abc-123",
      "patient_name": "홍길동",
      "patient_id": "P001",
      "study_date": "20260520",
      "study_description": "Chest CT",
      "modality": "CT",
      "study_uid": "1.2.840..."
    }
  ],
  "total": 1,
  "query_id": "abc-123"
}
```

> **제한:** 최대 50건까지 반환됩니다.  
> `remote_type`이 `modality`인 경우만 지원합니다.

### 5.7 영상 가져오기 (C-MOVE)

```http
POST /api/v1/remotes/{remote_id}/retrieve?query_id=abc-123&answer_id=0
Authorization: Bearer {token}
```

**Query Parameters:**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `query_id` | string | ✅ | C-FIND 응답의 `query_id` |
| `answer_id` | string | ✅ | C-FIND 결과의 `answer_id` |

**Response (200):**
```json
{
  "ok": true,
  "transfer_id": "uuid-...",
  "status": "completed"
}
```

> C-MOVE 대상 AE Title은 `OPENPACS` (자체 서버)로 고정됩니다.

### 5.8 영상 전송 (C-STORE / Peer Send)

```http
POST /api/v1/remotes/{remote_id}/send?study_uid=1.2.840...
Authorization: Bearer {token}
```

**Query Parameters:**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `study_uid` | string | ✅ | 전송할 Study Instance UID |

**Response (200):**
```json
{
  "ok": true,
  "transfer_id": "uuid-..."
}
```

| remote_type | 전송 방식 |
|-------------|----------|
| `modality` | DICOM C-STORE |
| `peer` | Orthanc Peer Store (HTTP) |

### 5.9 전송/수신 이력

```http
GET /api/v1/remotes/transfer-history?page=1&page_size=20
Authorization: Bearer {token}
```

**Response (200):**
```json
{
  "total": 5,
  "history": [
    {
      "id": "uuid-...",
      "direction": "receive",
      "study_instance_uid": "1.2.840...",
      "patient_name": "홍길동",
      "modality": "CT",
      "status": "completed",
      "error_message": null,
      "started_at": "2026-05-26T10:00:00Z",
      "completed_at": "2026-05-26T10:01:30Z"
    }
  ]
}
```

| direction | 의미 |
|-----------|------|
| `send` | 외부로 전송 |
| `receive` | 외부에서 수신 |

| status | 의미 |
|--------|------|
| `pending` | 대기 중 |
| `in_progress` | 진행 중 |
| `completed` | 완료 |
| `failed` | 실패 (`error_message` 참조) |

---

## 6. 에러 처리

### 6.1 공통 에러 형식

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": {},
    "timestamp": "2026-05-26T10:00:00Z",
    "request_id": "uuid-..."
  }
}
```

### 6.2 주요 에러 코드

| HTTP | code | 의미 |
|------|------|------|
| 401 | `INVALID_CREDENTIALS` | 인증 실패 (JWT 만료/무효) |
| 403 | `FORBIDDEN` | 권한 부족 (역할 불일치) |
| 404 | - | `{"error": "...not found"}` |
| 422 | `VALIDATION_ERROR` | 요청 파라미터 오류 |
| 500 | `INTERNAL_ERROR` | 서버 오류 |

### 6.3 환자 포털 특수 에러

| error 문자열 | 원인 | 대응 |
|-------------|------|------|
| `Invalid or expired token` | 토큰 만료 또는 무효 | 새 토큰 발급 필요 |
| `Token already used` | 이미 사용된 1회성 토큰 | 새 토큰 발급 필요 |
| `Privacy consent required before upload` | 동의 미완료 | `POST /consent` 먼저 호출 |

---

## 7. 연동 시나리오별 예제

### 7.1 HIS에서 환자에게 업로드 링크 발급

```
1. HIS 서버 → POST /api/v1/patient-upload/token
   {"patient_id": "P001", "patient_name": "홍길동", "expires_hours": 24}
   
2. 응답의 url을 환자에게 SMS 전송:
   "https://his.example.org/pacs-admin/patient-upload?token=CHANGE_ME"

3. 환자 → 웹 브라우저에서 링크 접속
   → 동의 → 파일 업로드

4. 관리자 → /pacs-admin/upload-queue에서 승인
```

### 7.2 키오스크에서 CD 업로드

```
1. 키오스크 앱 → POST /api/v1/upload/files?source=kiosk
   (키오스크 전용 JWT 사용)
   
2. CD 파일들을 multipart로 업로드

3. 자동 검증 + Orthanc 저장 (관리자 업로드는 승인 불필요)
```

### 7.3 외부 PACS에서 영상 가져오기

```
1. POST /api/v1/remotes
   {"name":"외부병원","remote_type":"modality","ae_title":"EXT","host":"10.0.0.5","port":4242}

2. POST /api/v1/remotes/{id}/echo  ← 연결 확인

3. POST /api/v1/remotes/{id}/query?patient_id=P001  ← C-FIND

4. POST /api/v1/remotes/{id}/retrieve?query_id=xxx&answer_id=0  ← C-MOVE
```

### 7.4 연구용 배치 업로드

```
1. POST /api/v1/upload/zip?auto_validate=true&source=research
   (ZIP으로 묶어서 업로드)
   
2. 자동 검증 결과 확인

3. GET /api/v1/dicom-issues?days=1  ← 이슈 확인
```

---

## 부록: API 요약표

| # | Method | Endpoint | 인증 | 설명 |
|---|--------|----------|------|------|
| 1 | POST | `/api/v1/upload/files` | JWT | DICOM 파일 업로드 (직접 Orthanc) |
| 2 | POST | `/api/v1/upload/zip` | JWT | ZIP 업로드 |
| 3 | GET | `/api/v1/upload-queue` | ADMIN | 승인 큐 목록 |
| 4 | POST | `/api/v1/upload-queue/{id}/approve` | ADMIN | 승인 |
| 5 | POST | `/api/v1/upload-queue/{id}/reject` | ADMIN | 거부 |
| 6 | GET | `/api/v1/upload-queue/stats` | JWT | 큐 통계 |
| 7 | POST | `/api/v1/patient-upload/token` | ADMIN | 환자 토큰 발급 |
| 8 | GET | `/api/v1/patient-upload/tokens` | ADMIN | 토큰 목록 |
| 9 | GET | `/api/v1/patient-upload/verify` | *public* | 토큰 검증 |
| 10 | POST | `/api/v1/patient-upload/consent` | *public* | 동의 제출 |
| 11 | POST | `/api/v1/patient-upload/files` | *public* | 환자 파일 업로드 |
| 12 | GET | `/api/v1/patient-upload/status` | *public* | 상태 확인 |
| 13 | GET | `/api/v1/remotes` | ADMIN | 피어/모달리티 목록 |
| 14 | POST | `/api/v1/remotes` | ADMIN | 등록 |
| 15 | PUT | `/api/v1/remotes/{id}` | ADMIN | 수정 |
| 16 | DELETE | `/api/v1/remotes/{id}` | ADMIN | 삭제 |
| 17 | POST | `/api/v1/remotes/{id}/echo` | ADMIN | 연결 테스트 |
| 18 | POST | `/api/v1/remotes/{id}/query` | ADMIN | C-FIND 검색 |
| 19 | POST | `/api/v1/remotes/{id}/retrieve` | ADMIN | C-MOVE 가져오기 |
| 20 | POST | `/api/v1/remotes/{id}/send` | ADMIN | C-STORE 전송 |
| 21 | GET | `/api/v1/remotes/transfer-history` | ADMIN | 전송 이력 |
