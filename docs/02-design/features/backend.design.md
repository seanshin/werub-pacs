# Backend Design Document

## 개요

OpenPACS 백엔드는 FastAPI 기반의 REST API 서버로, DICOM 의료영상 데이터를 Orthanc를 통해 저장/관리하고, 판독/리포트/AI 분석 기능을 제공합니다.

**핵심 역할:**
- DICOM 데이터 검증 및 정규화
- DICOMweb 프로토콜 게이트웨이
- 사용자/권한 관리 (RBAC)
- 판독 리포트 생성 및 저장
- AI 추론 작업 큐 관리
- 감사 로그 기록
- 워크리스트 제공

---

## 아키텍처

### 레이어 구조

```
┌─────────────────────────────────────────┐
│  FastAPI 라우터 (api/)                  │
│  - auth, dicomweb, ai_assist, report   │
├─────────────────────────────────────────┤
│  서비스 계층 (services/)                │
│  - DICOM 검증 엔진                      │
│  - AI 워커 / 추론 (Celery)             │
│  - 리포트 생성                          │
├─────────────────────────────────────────┤
│  데이터 모델 (models/) + DB (PostgreSQL)│
│  - User, Study, Series, AuditLog       │
│  - Report, AIResult, Template          │
├─────────────────────────────────────────┤
│  외부 연동                              │
│  - Orthanc (DICOM 저장소)              │
│  - Redis (캐시/큐)                     │
│  - Celery (비동기 작업)                │
└─────────────────────────────────────────┘
```

### 핵심 컴포넌트

| 컴포넌트 | 담당 | 기술 |
|---------|------|------|
| **API 라우터** | HTTP 요청 처리 | FastAPI + Uvicorn |
| **ORM 모델** | DB 스키마 | SQLAlchemy async |
| **검증 엔진** | DICOM 표준 검증 | pydicom + 커스텀 규칙 |
| **AI 워커** | 추론 + 결과 저장 | Celery + ONNX/Ollama |
| **DICOMweb 게이트웨이** | Orthanc REST API 래핑 | httpx |
| **보안 계층** | 인증/권한 | JWT + 세션 + pgcrypto |
| **감사 로그** | 규정 준수 | PostgreSQL 로깅 |

---

## 데이터 모델

### 핵심 테이블 (PostgreSQL)

```
users
├─ id, username, email, password_hash
├─ role (admin/radiologist/physician/technologist/researcher)
└─ is_active, created_at, updated_at

studies [위임: Orthanc REST API 직접 쿼리]
├─ 로컬 ORM 모델 없음 — Orthanc가 권위 있는 데이터베이스
├─ 검증 상태 등 메타데이터는 validation_results 테이블에서 별도 관리
└─ 참고: validation_results.study_instance_uid 컬럼으로 연결

series [위임: Orthanc REST API 직접 쿼리]
├─ 로컬 ORM 모델 없음 — studies와 동일한 위임 패턴
└─ series 메타데이터는 Orthanc /series/{id} 응답에서 실시간 조회

reports
├─ id, study_id, radiologist_id, report_text
├─ finding, impression, status (draft/final)
└─ created_at, signed_at

ai_results
├─ id, series_id, model_id, model_version
├─ result_type (SEG/SR/SC), result_data (JSON)
└─ confidence, inference_time

audit_logs
├─ id, user_id, action, resource, timestamp
└─ details (JSON)

templates
├─ id, name, category, content
└─ is_active
```

### 검증 규칙 (validation 테이블)

```json
{
  "rule_id": "jpeg_density_check",
  "rule_name": "JPEG 밀도 vs Pixel Spacing 검증",
  "severity": "warning",
  "description": "JFIF Xdensity/Ydensity와 DICOM Pixel Spacing 교차 검증"
}
```

---

## API 설계

### 인증 엔드포인트

```
POST /api/v1/auth/login      # 로그인
POST /api/v1/auth/logout     # 로그아웃 (토큰 블랙리스트)
POST /api/v1/auth/refresh    # 토큰 갱신
GET  /api/v1/auth/me         # 현재 사용자 정보
POST /api/v1/auth/register   # 사용자 등록 (Admin 전용)
POST /api/v1/auth/setup      # 초기 Admin 생성 (사용자 없을 때만)
```

### DICOM 워크리스트

```
GET  /api/v1/worklist?date=YYYY-MM-DD&modality=CT
GET  /api/v1/worklist/{study_id}
POST /api/v1/studies/{study_id}/validate
```

### 판독 리포트

```
POST /api/v1/studies/{study_id}/reports
GET  /api/v1/studies/{study_id}/reports/{report_id}
PATCH /api/v1/reports/{report_id} (draft→final)
GET  /api/v1/reports?radiologist_id={id}&date_from={date}
```

### AI 추론

```
POST /api/v1/studies/{study_id}/ai/infer
  {
    "model_id": "lung-nodule-detection",
    "series_id": "{id}",
    "priority": "high"
  }
GET  /api/v1/ai/tasks/{task_id}
GET  /api/v1/ai/results/{result_id}
```

### 감사 로그

```
GET  /api/v1/audit?user_id={id}&from={date}&to={date}
GET  /api/v1/audit/{log_id}
```

### DICOMweb 게이트웨이

```
GET  /dicom-web/studies
GET  /dicom-web/studies/{study_id}/series
GET  /dicom-web/studies/{study_id}/series/{series_id}/instances
```

---

## 인증 & 권한 설계

### JWT 토큰 구조

```json
{
  "sub": "user_id",
  "username": "radiologist_001",
  "role": "doctor",
  "permissions": ["read_study", "create_report", "request_ai"],
  "exp": 1622548800,
  "iat": 1622545200
}
```

### RBAC (Role-Based Access Control)

| 역할 | 설명 | 권한 |
|------|------|------|
| **admin** | 시스템 관리자 | 모든 작업, 사용자 관리, 감사 로그 조회 |
| **radiologist** | 영상의학과 의사 | 판독, 리포트 작성, AI 요청, 리포트 서명 |
| **physician** | 임상의 | 리포트 조회, 승인 |
| **technologist** | 방사선 기술사 | 워크리스트 조회, 검증 결과 확인 |
| **researcher** | 연구원 | 데이터 내보내기, 통계 조회 |

**주의:** Design 문서의 `doctor`/`tech`는 개념적 역할이며, 실제 구현에서는 임상 현장의 실제 역할(`radiologist`, `physician`, `technologist`, `researcher`)로 세분화됨.

### 보안 메커니즘

- **pgcrypto 암호화**: UUID 생성 시 사용. 민감 정보는 컬럼 암호화 미구현.
- **HTTPS:** Let's Encrypt TLS 1.3
- **JWT 토큰 검증**: Access (60min) + Refresh (7d) 토큰 지원. 토큰 블랙리스트(Redis) 구현.
- **RBAC 데코레이터**: `RequireRole(Role.ADMIN)` 의존성 주입 방식.
- **세션 관리**: JWT stateless. Redis는 토큰 블랙리스트 + Celery broker용.
- **CSRF 방지**: 미구현 — API-only 백엔드는 Bearer 토큰 사용하므로 CSRF 취약점 없음 (GET 요청만 취약).
- **Break-the-Glass**: 미구현 — 향후 의료 컴플라이언스 요구 시 Phase 3에서 구현.
- **Password Hashing**: PBKDF2-HMAC-SHA256, 사용자별 salt.

---

## 비동기 작업 (Celery + Redis)

### AI 추론 파이프라인

```
1. 사용자가 POST /api/v1/studies/{study_id}/ai/infer 요청
2. 백엔드: task 생성, Redis 큐에 등록, task_id 반환
3. Celery Worker: DICOM 다운로드 → 전처리
4. 추론 엔진 선택:
   - ONNX Runtime (로컬 GPU/CPU)
   - Ollama API (로컬 LLM)
   - 클라우드 API 폴백
5. 결과: DICOM SR/SEG 형식으로 저장
6. 데이터베이스: ai_results 기록
7. 클라이언트: GET /api/v1/ai/tasks/{task_id} 폴링 또는 WebSocket
```

### 작업 상태 (Task Status)

- `pending`: Redis 큐 대기
- `started`: Worker 처리 중
- `progress`: 진행도 업데이트
- `success`: 완료
- `failure`: 실패 + 에러 로그
- `timeout`: 타임아웃 (기본 3600초)

---

## DICOM 검증 엔진

### 검증 규칙 우선순위

```
1. [CRITICAL] 필수 태그 존재 여부 (PatientID, StudyDate 등)
2. [CRITICAL] DICOM 파일 형식 검증
3. [HIGH] JPEG 밀도 vs Pixel Spacing 교차 검증 ⚠️
4. [MEDIUM] 태그 값 범위 검증
5. [LOW] 추천 메타데이터 존재 여부
```

### 특별 규칙: JPEG 밀도 검증

```
문제: 실무 영상에서 JPEG 압축 시 
     JFIF Xdensity/Ydensity ≠ DICOM Pixel Spacing
     → 측정값 오류 발생

해결:
  if is_jpeg_compressed():
    jfif_dpi = get_jfif_density()
    pixel_spacing = get_dicom_pixel_spacing()
    if abs(jfif_dpi - pixel_spacing) > tolerance:
      warnings.append("jpeg_density_mismatch")
```

---

## 에러 처리

### 에러 응답 형식 (표준화됨)

모든 에러 응답은 다음 구조를 따릅니다:

```json
{
  "error": {
    "code": "DICOM_VALIDATION_ERROR",
    "message": "DICOM 파일 형식이 유효하지 않습니다",
    "details": {
      "missing_tags": ["PatientID"],
      "warnings": ["jpeg_density_mismatch"]
    },
    "timestamp": "2026-05-13T10:30:00Z"
  }
}
```

**구현 방식:**
- 기본 예외: `AppException` 서브클래스 (DicomValidationError, NotFoundError, AuthenticationError 등)
- HTTPException 호환: `main.py`의 예외 핸들러가 HTTPException도 표준 형식으로 변환
- 모든 엔드포인트의 에러는 위 형식을 따름

### HTTP 상태 코드

| 코드 | 시나리오 |
|------|---------|
| 200 | 성공 |
| 201 | 리소스 생성 성공 |
| 400 | 요청 형식 오류 |
| 401 | 인증 필요 |
| 403 | 권한 없음 |
| 404 | 리소스 없음 |
| 409 | 데이터 충돌 (중복 등) |
| 422 | 검증 실패 (DICOM 오류) |
| 500 | 서버 오류 |
| 502 | Orthanc 저장 실패 |
| 503 | 서비스 불가능 (Orthanc 다운 등) |

---

## 성능 최적화

### 캐싱 전략 (Redis)

- **워크리스트:** 5분 캐시
- **사용자 권한:** 세션 생명 주기 동안
- **Orthanc 메타데이터:** 1시간 캐시
- **AI 모델 메타데이터:** 24시간 캐시

### 데이터베이스 인덱싱

```sql
CREATE INDEX idx_studies_patient_id ON studies(patient_id);
CREATE INDEX idx_studies_study_date ON studies(study_date DESC);
CREATE INDEX idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX idx_reports_radiologist ON reports(radiologist_id, created_at);
```

### 쿼리 최적화

- SQLAlchemy eager loading (N+1 방지)
- Pagination: limit=50 기본값
- 비동기 I/O: asyncpg + aiofiles

---

## 통합 포인트

### Orthanc 연동

```
백엔드 → Orthanc REST API (127.0.0.1:8042)
  - Study/Series/Instance 메타데이터 조회
  - DICOM 파일 다운로드
  - DICOM 저장 (C-STORE 또는 REST POST)
  - 통계 조회
```

### 프론트엔드 통합

```
Admin UI / Worklist UI → 백엔드 API
  - JWT 토큰 포함 요청
  - DICOMweb 직접 호출 (토큰 헤더 자동 추가)
```

---

## 배포 고려사항

### 환경 변수

```bash
DATABASE_URL=postgresql://openpacs:CHANGE_ME@localhost:5432/openpacs
ORTHANC_URL=http://127.0.0.1:8042
ORTHANC_USER=admin
ORTHANC_PASSWORD=ORTHANC_PASSWORD 로 정한 값
REDIS_URL=redis://127.0.0.1:6379/0
JWT_SECRET_KEY=<generated-secret>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
```

### 헬스체크

```
GET /api/v1/health
  → { "status": "healthy", "db": "ok", "orthanc": "ok" }
```

---

## 마이그레이션 전략

### Alembic 버전 관리

```bash
alembic revision --autogenerate -m "add reports table"
alembic upgrade head
```

### 데이터 마이그레이션

- Phase 7에서 레거시 PACS → Orthanc 마이그레이션

---

## 테스트 전략

### 테스트 카테고리

1. **단위 테스트 (pytest)**
   - 검증 엔진 규칙
   - 토큰 생성/검증
   - 쿼리 빌더

2. **통합 테스트**
   - Orthanc 연동
   - Database CRUD
   - AI 작업 큐

3. **E2E 테스트**
   - 로그인 → 워크리스트 조회 → 판독 → 리포트 저장
   - 판독 후 AI 요청 → 결과 조회

4. **보안 테스트**
   - RBAC 검증
   - CSRF 방지
   - SQL injection 방지

---

## 알려진 제약사항

1. **Orthanc 헬스체크**: 기본 인증 문제로 "unhealthy"로 표시되지만 실제 서비스는 정상
2. **DICOM 비표준 문제**: 실무 데이터는 표준을 완벽히 준수하지 않음 → 검증 규칙 확장 필요
3. **GPU 없음**: ONNX Runtime은 CPU 모드, 무거운 추론은 클라우드 폴백

---

## 참고 문서

- [AI 워커 설계](../../docs/04-ai/) - Celery + 추론 엔진
- [기술 스택](../../docs/07-plan/) - FastAPI, PostgreSQL, Orthanc

---

## 주의사항: Design vs Implementation

이 문서는 설계 의도를 나타내며, 실제 구현과 다음 항목에서 의도적으로 다릅니다:

### 의도적 차이 (설계 결정)

1. **studies/series 모델**
   - 설계: 로컬 PostgreSQL 테이블 정의
   - 구현: Orthanc REST API 직접 쿼리
   - 이유: Orthanc이 DICOM 데이터의 권위 있는 소스이므로, 로컬 중복 데이터 금지

2. **RBAC 역할**
   - 설계: admin, doctor, tech, guest
   - 구현: admin, radiologist, physician, technologist, researcher
   - 이유: 실제 의료 현장의 역할 정의 반영

3. **API 엔드포인트 패턴**
   - 설계: 중첩 경로 (`POST /studies/{id}/reports`)
   - 구현: 평면 경로 (`POST /reports`, study_instance_uid in body)
   - 이유: REST 단순화 + 유연성

4. **CSRF 방지**
   - 설계: CSRF 토큰 관리
   - 구현: 미구현
   - 이유: API-only 백엔드는 Bearer 토큰 사용하므로 CSRF 불가능

### 미리계획된 미구현 항목 (향후 Phase)

- Break-the-Glass 긴급 접근: Phase 3 (의료법 컴플라이언스 강화)
- Redis 4단계 캐싱: Phase 3 (성능 최적화)
- 다중 기관 지원: v2.0 (스코프 제한)
