# 환자 포털 API 가이드

**Base URL**: `https://his.example.org/pacs-api`
**인증**: Bearer Token (JWT)
**Swagger**: `https://his.example.org/pacs-api/docs`
**태그**: `환자 포털`, `주치의 포털`

---

## 인증

### 로그인
```
POST /api/v1/auth/login
Content-Type: application/json

{ "username": "dr.kim", "password": "CHANGE_ME" }

→ { "access_token": "CHANGE_ME", "token_type": "bearer" }
```

### 토큰 검증
```
GET /api/v1/my-patients/verify-access
Authorization: Bearer {token}

→ { "valid": true, "username": "dr.kim", "role": "radiologist" }
```

이후 모든 요청에 `Authorization: Bearer {token}` 헤더 필요.

---

## 주치의 포털 API (`/api/v1/my-patients`)

### 1. 내 환자 영상 목록

```
GET /api/v1/my-patients?status={unread|completed|all}&search={검색어}&page=1&page_size=20
```

| 파라미터 | 필수 | 설명 |
|----------|:----:|------|
| status | - | `unread` (미판독), `completed` (완료), 생략 시 전체 |
| search | - | 환자명 또는 환자번호 |
| page | - | 페이지 번호 (기본 1) |
| page_size | - | 페이지 크기 (기본 20, 최대 100) |

**응답**:
```json
{
  "studies": [
    {
      "study_instance_uid": "1.2.3...",
      "patient_id": "P001",
      "patient_name": "홍길동",
      "modality": "CT",
      "study_description": "Chest CT",
      "study_date": "20260519",
      "accession_number": "ACC001",
      "read_status": "completed",
      "report_id": "uuid-xxx",
      "findings": "우상엽에 5mm 결절 관찰",
      "impression": "폐 결절 — 6개월 후 추적 CT 권장",
      "urgency": "normal",
      "signed_at": "2026-05-19T11:33:16",
      "viewer_url": "/werub-viewer/viewer?StudyInstanceUIDs=1.2.3...",
      "report_url": "/pacs-admin/reading/view?study=1.2.3..."
    }
  ],
  "page": 1,
  "page_size": 20,
  "username": "dr.kim"
}
```

### 2. 리포트 바로보기 (JSON)

```
GET /api/v1/my-patients/report/{study_uid}
```

**응답**:
```json
{
  "id": "uuid-xxx",
  "study_instance_uid": "1.2.3...",
  "patient_id": "P001",
  "findings": "우상엽에 5mm 결절 관찰...",
  "impression": "폐 결절 — 6개월 후 추적 CT 권장",
  "recommendation": "",
  "urgency": "normal",
  "status": "final",
  "author_name": "김판독",
  "signed_at": "2026-05-19T11:33:16",
  "signed_by_name": "김판독",
  "created_at": "2026-05-19T10:00:00"
}
```

### 3. 리포트 PDF 다운로드

```
GET /api/v1/my-patients/report/{study_uid}/pdf
```

**응답**: `text/html` (인쇄 가능한 판독 리포트)
- 브라우저에서 바로 인쇄 또는 PDF 저장 가능
- `Content-Disposition: inline; filename=report_xxx.html`

### 4. 영상 썸네일 URL

```
GET /api/v1/my-patients/study/{study_uid}/thumbnail
```

**응답**:
```json
{
  "study_uid": "1.2.3...",
  "thumbnail_url": "/dicom-web/studies/1.2.3.../thumbnail",
  "viewer_url": "/werub-viewer/viewer?StudyInstanceUIDs=1.2.3..."
}
```

### 5. 판독 완료 알림

```
GET /api/v1/my-patients/notifications?unread_only=true
```

**응답**:
```json
{
  "notifications": [
    {
      "id": "uuid-xxx",
      "title": "판독 완료",
      "message": "홍길동(P001)의 Chest CT 판독이 완료되었습니다",
      "is_read": false,
      "created_at": "2026-05-19T12:00:00",
      "metadata": { "study_uid": "1.2.3..." }
    }
  ]
}
```

---

## 환자 API (`/api/v1/patients`)

### 6. 환자별 검사 목록

```
GET /api/v1/patients/{patient_id}/studies?limit=50
```

**응답**: Orthanc에서 해당 환자의 전체 검사 목록 (DICOMweb 기반)
```json
{
  "patient_id": "P001",
  "patient_name": "홍길동",
  "total_studies": 5,
  "studies": [
    {
      "study_instance_uid": "1.2.3...",
      "study_date": "2026-05-19",
      "modality": "CT",
      "description": "Chest CT",
      "instances": 133,
      "read_status": "completed",
      "report_summary": "폐 결절 — 추적 관찰",
      "viewer_url": "/werub-viewer/viewer?StudyInstanceUIDs=1.2.3..."
    }
  ]
}
```

### 7. 환자 검색 (초성 지원)

```
GET /api/v1/patients/search?name={검색어}&limit=20
```

| 검색 예시 | 매칭 |
|----------|------|
| `name=홍길동` | 완전/부분 일치 |
| `name=ㅎㄱㄷ` | 초성 매칭 → 홍길동 |
| `name=ㄱ` | 김, 강, 고 등 ㄱ으로 시작하는 환자 |

### 8. 환자별 리포트 목록

```
GET /api/v1/patients/{patient_id}/reports
```

**응답**:
```json
{
  "patient_id": "P001",
  "total_reports": 3,
  "reports": [
    {
      "id": "uuid-xxx",
      "study_instance_uid": "1.2.3...",
      "study_date": "2026-05-19",
      "modality": "CT",
      "status": "final",
      "impression": "폐 결절 — 추적 관찰",
      "signed_by_name": "김판독",
      "signed_at": "2026-05-19T11:33:16"
    }
  ]
}
```

---

## 영상 뷰어 연동

포털에서 영상을 보려면 viewer_url을 iframe 또는 새 창으로 열면 됩니다:

```html
<!-- iframe -->
<iframe src="https://his.example.org/werub-viewer/viewer?StudyInstanceUIDs=1.2.3..." />

<!-- 새 창 -->
<a href="https://his.example.org/werub-viewer/viewer?StudyInstanceUIDs=1.2.3..." target="_blank">
  영상 보기
</a>
```

---

## 에러 코드

| HTTP | 의미 |
|:----:|------|
| 200 | 성공 |
| 401 | 인증 실패 (토큰 만료/무효) |
| 404 | 리포트/환자 없음 |
| 422 | 파라미터 오류 |

---

## 판독 상태

| 값 | 의미 |
|:--:|------|
| `unread` | 미판독 |
| `draft` | 작성 중 |
| `completed` / `final` | 판독 완료 |

---

*Swagger UI: https://his.example.org/pacs-api/docs → "환자 포털" / "주치의 포털" 태그*
