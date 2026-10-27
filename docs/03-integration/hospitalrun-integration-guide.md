# HospitalRun ↔ OpenPACS 연동 가이드

> **작성일**: 2026-05-12
> **OpenPACS 버전**: v3.2.0 (61 API endpoints)
> **대상**: HospitalRun 개발자

---

## 1. 개요

### 1.1 연동 아키텍처

```
┌─────────────────────┐         ┌─────────────────────────────────┐
│    HospitalRun      │         │         OpenPACS                │
│                     │         │                                 │
│  환자 차트           │ ──JWT──→│  /pacs-api/api/v1/...           │
│  검사 오더           │         │    ├── /orders          (오더)   │
│  영상 조회           │         │    ├── /patients/{mrn}  (조회)   │
│  판독 결과           │         │    ├── /patient-mappings(매핑)   │
│                     │         │    └── /notifications  (알림)   │
│  포트 3000/4000     │         │  포트 8000                      │
└─────────────────────┘         └─────────────────────────────────┘
        │                                    │
        │              ┌─────────────────────┤
        │              │                     │
        ▼              ▼                     ▼
  ┌──────────┐   ┌──────────┐         ┌──────────┐
  │ PostgreSQL│   │  OHIF    │         │ Orthanc  │
  │ (공유)    │   │ Viewer   │         │ DICOM    │
  │ 포트 5432 │   │ 포트 3001│         │ 포트 4242│
  └──────────┘   └──────────┘         └──────────┘
```

### 1.2 핵심 원칙

**HospitalRun MRN = DICOM PatientID**

- HospitalRun에서 환자에게 부여한 MRN(환자번호)이 DICOM 영상의 PatientID와 동일
- 검사 오더 시 MRN을 전달하면, 모달리티 장비 → PACS 수신까지 자동으로 연결됨
- 별도 매핑 테이블이 자동 관리됨 (MRN ↔ HospitalRun UUID ↔ DICOM PatientID)

---

## 2. 인증 (SSO)

### 2.1 JWT 토큰 공유

HospitalRun의 JWT 토큰으로 OpenPACS API를 직접 호출할 수 있습니다. 별도 로그인 불필요.

```typescript
// HospitalRun에서 발급한 토큰을 그대로 사용
const pacsResponse = await fetch('/pacs-api/api/v1/patients/HR-001/studies', {
  headers: {
    'Authorization': `Bearer ${hospitalRunToken}`,
  },
});
```

### 2.2 역할 매핑

| HospitalRun 역할 | OpenPACS 역할 | 권한 |
|:--|:--|:--|
| ADMIN | admin | 전체 관리 |
| DOCTOR | physician | 영상 조회, 리포트 조회 |
| RADIOLOGIST | radiologist | 판독, 리포트 작성, AI |
| TECHNICIAN | technologist | 업로드, 워크리스트, QC |
| NURSE | physician | 영상 조회 |

### 2.3 SSO 설정

OpenPACS docker-compose의 `HOSPITALRUN_AUTH_SECRET` 환경변수가 HospitalRun의 `AUTH_SECRET`과 동일해야 합니다.

```yaml
# OpenPACS docker-compose.yml
backend:
  environment:
    HOSPITALRUN_AUTH_SECRET: "HospitalRun의_AUTH_SECRET_값"
```

### 2.4 자동 사용자 생성

HospitalRun 토큰으로 최초 접근 시, OpenPACS에 사용자가 자동 생성됩니다.
- username: 이메일의 @ 앞부분
- role: HospitalRun 역할에 따라 자동 매핑
- department: "HospitalRun SSO"

---

## 3. 환자 ID 매핑

### 3.1 매핑 흐름

```
HospitalRun 오더 (MRN: HR-20260506-0328, UUID: abc-123)
    │
    ▼ POST /pacs-api/api/v1/orders
    │
OpenPACS 워크리스트 생성
    │  PatientID = HR-20260506-0328 (MRN)
    │  + 매핑 자동 생성 (MRN ↔ UUID ↔ DICOM PID)
    │
    ▼ MWL (Modality Worklist)
    │
모달리티 장비 → 환자 선택 → 촬영
    │  DICOM PatientID = HR-20260506-0328
    │
    ▼ C-STORE
    │
OpenPACS 영상 수신 (PatientID = HR-20260506-0328)
    │
    ▼ GET /patients/{mrn}/studies
    │
HospitalRun에서 MRN 또는 UUID로 영상 조회 가능
```

### 3.2 매핑 테이블

| 필드 | 설명 | 예시 |
|------|------|------|
| `his_mrn` | HospitalRun MRN (= DICOM PatientID) | HR-20260506-0328 |
| `his_patient_id` | HospitalRun 내부 UUID | uuid-abc-123 |
| `his_patient_name` | 환자명 | 홍길동 |
| `dicom_patient_id` | DICOM PatientID | HR-20260506-0328 |

### 3.3 매핑 확인 API

```
GET /pacs-api/api/v1/patient-mappings/resolve/{any_id}
```

MRN, HospitalRun UUID, DICOM PatientID 중 아무거나 입력하면 전체 매핑 정보를 반환합니다.

```json
{
  "resolved": true,
  "his_mrn": "HR-20260506-0328",
  "his_patient_id": "uuid-abc-123",
  "his_patient_name": "홍길동",
  "dicom_patient_id": "HR-20260506-0328"
}
```

---

## 4. API 연동 상세

### 4.1 검사 오더 생성

HospitalRun에서 영상 검사를 오더하면 OpenPACS 워크리스트에 자동 등록됩니다.

```typescript
// apps/api/src/modules/orders/orders.service.ts

async createImagingOrder(order: CreateImagingOrderDto, patient: Patient) {
  // 1. OpenPACS에 오더 전송
  const pacsResponse = await fetch('/pacs-api/api/v1/orders', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.getServiceToken()}`,
    },
    body: JSON.stringify({
      patient_id: patient.mrn,               // HIS MRN → DICOM PatientID
      patient_name: `${patient.familyName}^${patient.givenName}`,
      patient_birth_date: patient.birthDate,  // YYYY-MM-DD
      patient_sex: patient.sex,               // M, F, O
      his_patient_uuid: patient.id,           // HospitalRun 내부 UUID
      modality: order.modality,               // CT, MR, CR, DX, US
      body_part: order.bodyPart,              // CHEST, HEAD, ABDOMEN, KNEE
      procedure_description: order.description,
      referring_physician: order.doctor.name,
      clinical_info: order.clinicalInfo,
      priority: order.isUrgent ? 'stat' : 'routine',
      hospitalrun_order_id: order.id,         // HospitalRun 오더 ID
    }),
  });

  const result = await pacsResponse.json();
  // result.accession_number: 접수번호 (상태 추적에 사용)
  // result.worklist_id: OpenPACS 워크리스트 ID

  return result;
}
```

**필수 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `patient_id` | string | HIS MRN (DICOM PatientID가 됨) |
| `patient_name` | string | 환자명 (한글 지원) |
| `modality` | string | CT, MR, CR, DX, US |

**선택 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `his_patient_uuid` | string | HospitalRun 환자 UUID |
| `body_part` | string | CHEST, HEAD, ABDOMEN, KNEE 등 |
| `priority` | string | stat, high, routine, low |
| `clinical_info` | string | 임상 정보 |
| `hospitalrun_order_id` | string | HospitalRun 오더 ID |

### 4.2 오더 상태 추적

```typescript
// 오더 상태 폴링
const status = await fetch(
  `/pacs-api/api/v1/orders/${accessionNumber}/status`,
  { headers: { 'Authorization': `Bearer ${token}` } }
);

// 응답 예시
{
  "accession_number": "ACC-20260509-001",
  "status": "completed",    // scheduled → in_progress → completed
  "patient_id": "HR-20260506-0328",
  "study_instance_uid": "1.2.3...",  // 영상 수신 후 채워짐
  "has_images": true
}
```

### 4.3 환자 영상 목록 조회

```typescript
// apps/web/components/pacs/PatientImagingTab.tsx

async function loadPatientStudies(patientMrn: string) {
  const res = await fetch(`/pacs-api/api/v1/patients/${patientMrn}/studies`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });
  const data = await res.json();

  // data.total_studies: 전체 검사 수
  // data.unread_count: 미판독 수
  // data.studies[]: 검사 목록
  return data;
}
```

**응답 구조:**

```json
{
  "patient_id": "HR-20260506-0328",
  "patient_name": "홍길동",
  "total_studies": 3,
  "unread_count": 1,
  "studies": [
    {
      "study_instance_uid": "1.2.3.4.5...",
      "study_date": "20260509",
      "study_description": "Chest CT",
      "modalities": ["CT"],
      "series_count": 2,
      "instance_count": 133,
      "read_status": "final",         // unread, draft, preliminary, final
      "report": {
        "status": "final",
        "author": "김영상",
        "impression": "정상 흉부 소견",
        "signed_at": "2026-05-09T14:30:00Z"
      },
      "viewer_url": "/viewer/?StudyInstanceUIDs=1.2.3.4.5..."
    }
  ]
}
```

### 4.4 OHIF 뷰어 열기

```typescript
// 영상 클릭 시 OHIF 뷰어 새 탭으로 열기
function openViewer(studyInstanceUID: string) {
  window.open(`/viewer/?StudyInstanceUIDs=${studyInstanceUID}`, '_blank');
}

// 또는 듀얼 화면 판독 뷰 (판독의용)
function openReadingView(studyInstanceUID: string) {
  window.open(`/pacs-admin/reading/view?study=${studyInstanceUID}`, '_blank');
}
```

### 4.5 판독 리포트 조회

```typescript
// 환자의 모든 판독 리포트
const reports = await fetch(`/pacs-api/api/v1/patients/${mrn}/reports`, {
  headers: { 'Authorization': `Bearer ${token}` },
});

// 응답 예시
{
  "patient_id": "HR-20260506-0328",
  "total_reports": 2,
  "reports": [
    {
      "study_instance_uid": "1.2.3...",
      "study_date": "20260509",
      "modality": "CT",
      "status": "final",
      "findings": "양측 폐야 깨끗함...",
      "impression": "정상 흉부 소견",
      "author_name": "김영상",
      "signed_at": "2026-05-09T14:30:00+00:00",
      "viewer_url": "/viewer/?StudyInstanceUIDs=1.2.3..."
    }
  ]
}
```

### 4.6 알림 조회

```typescript
// PACS 알림 (판독 완료, 긴급 소견 등)
const notifications = await fetch('/pacs-api/api/v1/notifications?unread_only=true', {
  headers: { 'Authorization': `Bearer ${token}` },
});
```

---

## 5. 프론트엔드 구현 가이드

### 5.1 환자 차트 영상 탭

```
┌─────────────────────────────────────────────────────┐
│  환자: 홍길동 (M, 1980-03-15)  MRN: HR-20260506-0328│
├──────┬──────┬──────┬──────┬─────────────────────────┤
│ 기본 │ 진료 │ 처방 │ 영상 │                          │
├──────┴──────┴──────┴──────┴─────────────────────────┤
│                                                     │
│  영상 검사 목록                     [+ 검사 오더]     │
│  ┌─────────┬────────┬──────┬──────────┬──────┬────┐ │
│  │ 검사일   │ 모달리티│ 부위  │ 설명      │ 상태  │    │ │
│  ├─────────┼────────┼──────┼──────────┼──────┼────┤ │
│  │ 05-09   │ CT     │CHEST │ Chest CT │🟢완료│보기│ │
│  │ 05-08   │ CR     │CHEST │ Chest PA │🟡대기│보기│ │
│  └─────────┴────────┴──────┴──────────┴──────┴────┘ │
│                                                     │
│  최근 판독 리포트                                    │
│  ┌─────────────────────────────────────────────────┐│
│  │ 2026-05-09 Chest CT — 정상 흉부 소견              ││
│  │ 판독의: 김영상 | 서명: 05-09 14:30               ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

### 5.2 구현 파일 위치 (권장)

```
apps/web/
├── app/patients/[id]/
│   └── imaging/             # 영상 탭 페이지
│       └── page.tsx
├── components/pacs/
│   ├── PatientStudyList.tsx  # 영상 목록 컴포넌트
│   ├── StudyRow.tsx          # 개별 검사 행
│   ├── ReportSummary.tsx     # 판독 리포트 요약
│   └── OrderDialog.tsx       # 검사 오더 다이얼로그
└── lib/
    └── pacs-client.ts        # OpenPACS API 클라이언트
```

### 5.3 API 클라이언트

```typescript
// apps/web/lib/pacs-client.ts

const PACS_API = '/pacs-api/api/v1';

export class PacsClient {
  constructor(private token: string) {}

  private async fetch<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${PACS_API}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.token}`,
        ...options?.headers,
      },
    });
    if (!res.ok) throw new Error(`PACS API error: ${res.status}`);
    return res.json();
  }

  // 환자 영상 목록
  getPatientStudies(mrn: string) {
    return this.fetch(`/patients/${mrn}/studies`);
  }

  // 환자 판독 리포트
  getPatientReports(mrn: string) {
    return this.fetch(`/patients/${mrn}/reports`);
  }

  // 검사 오더 생성
  createOrder(order: ImagingOrder) {
    return this.fetch('/orders', { method: 'POST', body: JSON.stringify(order) });
  }

  // 오더 상태 확인
  getOrderStatus(accessionNumber: string) {
    return this.fetch(`/orders/${accessionNumber}/status`);
  }

  // 알림 조회
  getNotifications(unreadOnly = false) {
    return this.fetch(`/notifications?unread_only=${unreadOnly}`);
  }

  // ID 매핑 확인
  resolvePatientId(id: string) {
    return this.fetch(`/patient-mappings/resolve/${id}`);
  }
}
```

---

## 6. URL 정리

| 용도 | URL | 인증 |
|------|-----|:----:|
| PACS API (Swagger) | https://his.example.org/pacs-api/docs | - |
| PACS API (ReDoc) | https://his.example.org/pacs-api/redoc | - |
| Admin Portal | https://his.example.org/pacs-admin | JWT |
| OHIF Viewer | https://his.example.org/viewer/ | - |
| OHIF 특정 Study | /viewer/?StudyInstanceUIDs={uid} | - |
| 듀얼 판독 뷰 | /pacs-admin/reading/view?study={uid} | JWT |
| Orthanc Explorer | https://his.example.org/pacs/ | Basic |
| DICOM 수신 | 198.51.100.73:4242 (AET: OPENPACS) | AE Title |
| Grafana 모니터링 | https://his.example.org/grafana/ | admin |

---

## 7. 주의사항

### 7.1 건드리지 말 것
- PostgreSQL `hospitalrun` DB — OpenPACS는 `openpacs` DB만 사용
- Docker Compose의 `postgres`, `redis` 서비스
- Nginx의 `/api/`, `/` 경로 (HospitalRun 전용)

### 7.2 포트 할당

| 포트 | 서비스 | 소유 |
|------|--------|------|
| 3000 | HospitalRun Web | HospitalRun |
| 4000 | HospitalRun API | HospitalRun |
| 5432 | PostgreSQL | 공유 |
| 6379 | Redis | 공유 |
| 3001 | OHIF Viewer | OpenPACS |
| 3002 | Admin Portal | OpenPACS |
| 3003 | Grafana | OpenPACS |
| 4242 | DICOM 수신 | OpenPACS |
| 8000 | FastAPI Backend | OpenPACS |
| 8042 | Orthanc HTTP | OpenPACS |
| 9090 | Prometheus | OpenPACS |
| 9100 | Node Exporter | OpenPACS |

### 7.3 테스트 계정

| 시스템 | 계정 | 비밀번호 | 역할 |
|--------|------|---------|------|
| OpenPACS Admin | admin | CHANGE_ME | 관리자 |
| OpenPACS Admin | dr.kim | CHANGE_ME | 영상의학과 |
| Orthanc | admin | ORTHANC_PASSWORD 로 정한 값 | PACS 관리 |
| Grafana | admin | OpenPACS2026! | 모니터링 |
