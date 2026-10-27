# TD-002 소프트웨어 설계 명세서 (Software Design Specification)

| 항목 | 내용 |
|------|------|
| 문서 ID | TD-002 |
| 버전 | 2.0 |
| 작성일 | 2026-05-18 |
| 상태 | 승인 |
| 적용 표준 | IEC 62304:2006+A1:2015 §5.3, §5.4 |
| 제품명 | WeRU.B PACS |
| 검토일 | 2026-05-27 |
| 승인일 | 2026-05-27 |

## 1. 목적

WeRU.B PACS의 소프트웨어 아키텍처 설계 및 상세 설계를 기술하여, 요구사항(TD-001, 340+ endpoints)의 구현 방법을 명확히 한다. 40+ DB 테이블, 42+ 라우터 모듈, 6개 서비스 클래스, 4개 미들웨어의 설계를 포함한다.

## 2. 시스템 계층 구조

```
[사용자 브라우저]
       │
[Nginx Reverse Proxy (TLS 1.3, Let's Encrypt)]
       │
  ┌────┴────────────────────────────┐
  │                                  │
[WeRU.B Viewer]          [FastAPI Backend]          [Orthanc DICOMweb]
  (OHIF v3.12)            (Python 3.12)              (REST + DIMSE)
  Port: 3001               Port: 8001                Port: 8042/4242
       │                        │
       │              ┌─────────┼─────────────┐
       │              │         │              │
       │        [PostgreSQL]  [Redis]    [Celery Worker]
       │          (16)         (7)       (AI 추론 큐)
       │         Port:5432    Port:6379
       │              │
       │         [40+ Tables]
       │
  [Cornerstone3D]
  (WebGL 렌더링)
```

## 3. Docker 서비스 구성 (13개 컨테이너)

| # | 서비스명 | 이미지 | 포트 | 역할 |
|---|----------|--------|------|------|
| 1 | postgres | postgres:16-alpine | 127.0.0.1:5432 | 메타데이터 DB |
| 2 | redis | redis:7-alpine | 127.0.0.1:6379 | 캐시/세션/브로커 |
| 3 | orthanc | orthancteam/orthanc:latest-full | 127.0.0.1:8042, :4242 | DICOM 서버 |
| 4 | ohif | ohif/app:latest | 127.0.0.1:3001 | WeRU.B Viewer |
| 5 | backend | custom build | 127.0.0.1:8001 | FastAPI API 서버 |
| 6 | celery-worker | custom build | - | AI 추론 워커 |
| 7 | celery-beat | custom build | - | 주기적 작업 스케줄러 |
| 8 | celery-flower | mher/flower | 127.0.0.1:5555 | Celery 모니터링 |
| 9 | nginx | Host (not container) | 443, 80 | Reverse proxy |
| 10 | adminer | adminer:latest | 127.0.0.1:8080 | DB 관리 UI (개발용) |
| 11 | backup | custom build | - | 일일 자동 백업 |
| 12 | celery-beat | custom build | - | 주기적 작업 스케줄러 (SLA, 자동검증) |
| 13 | ai-worker | custom build | - | AI 추론 전용 워커 |

## 4. 모듈 설계

### 4.1 Backend 라우터 모듈 구조 (FastAPI)

| # | 모듈 | 경로 | Endpoints | 역할 | 의존 서비스 |
|---|------|------|-----------|------|-------------|
| 1 | auth | app/routers/auth.py | 6 | JWT 인증, 세션 관리 | AuthService, Redis |
| 2 | users | app/routers/users.py | 7 | 사용자 CRUD, RBAC | AuthService, PostgreSQL |
| 3 | system | app/routers/system.py | 6 | 시스템 정보, 헬스체크 | OrthancService |
| 4 | studies | app/routers/studies.py | 22 | Study/Series/Instance 관리 | OrthancService |
| 5 | dicomweb | app/routers/dicomweb.py | 8 | DICOMweb 프록시 | OrthancService |
| 6 | validation | app/routers/validation.py | 6 | DICOM 검증 엔진 | DicomValidationService |
| 7 | normalization | app/routers/normalization.py | 6 | 태그 정규화, 배치 | NormalizationService |
| 8 | worklist | app/routers/worklist.py | 8 | 워크리스트 | PostgreSQL |
| 9 | reports | app/routers/reports.py | 13 | 판독 리포트, 템플릿 | PostgreSQL |
| 10 | qc | app/routers/qc.py | 7 | QC (병합/분리/익명화) | OrthancService |
| 11 | ai | app/routers/ai.py | 18 | AI 추론 파이프라인 | AIInferenceService, Celery |
| 12 | audit | app/routers/audit.py | 4 | 감사 로그 | AuditService, PostgreSQL |

### 4.2 서비스 계층 (Service Layer)

| # | 서비스 | 파일 | 역할 | 의존성 |
|---|--------|------|------|--------|
| 1 | OrthancService | app/services/orthanc.py | Orthanc REST API 통신 (httpx async) | httpx, Orthanc |
| 2 | DicomValidationService | app/services/validation.py | DICOM 태그 검증 (16규칙), JPEG 밀도 검사 | pydicom, Pillow |
| 3 | NormalizationService | app/services/normalization.py | 비표준 태그 정규화, 배치 처리 (93% match rate) | pydicom, OrthancService |
| 4 | AuthService | app/services/auth.py | JWT 발급/검증, 비밀번호 해싱 | python-jose, bcrypt, Redis |
| 5 | AIInferenceService | app/services/ai_inference.py | Celery 작업 디스패치, 결과 수집, DICOM SR/SC 생성 | Celery, pydicom |
| 6 | AuditService | app/services/audit.py | 감사 로그 비동기 기록 | PostgreSQL (SQLAlchemy async) |

### 4.3 Middleware

| # | Middleware | 파일 | 기능 | 처리 순서 |
|---|-----------|------|------|-----------|
| 1 | CORSMiddleware | FastAPI built-in | Cross-Origin 허용 정책 | 1st |
| 2 | RateLimitMiddleware | app/middleware/rate_limit.py | API 호출 빈도 제한 (Redis, 100req/min) | 2nd |
| 3 | AuthMiddleware | app/middleware/auth.py | JWT 토큰 검증, 사용자 컨텍스트 주입 | 3rd |
| 4 | AuditMiddleware | app/middleware/audit.py | 모든 API 호출 감사 로그 자동 기록 | 4th |

### 4.4 모듈 의존성 다이어그램

```
┌──────────────────────────────────────────────────────┐
│                    Nginx (TLS)                        │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────┐
│              FastAPI Application                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │              Middleware Stack                     │ │
│  │  CORS → RateLimit → Auth → Audit                │ │
│  └──────────────────┬──────────────────────────────┘ │
│                     │                                 │
│  ┌─────────┬────────┼────────┬──────────┬──────────┐ │
│  │  auth   │ studies│ reports│   ai     │  audit   │ │
│  │  users  │ dicomweb│ worklist│ validation│ qc    │ │
│  │         │        │        │ normalization│       │ │
│  └────┬────┴───┬────┴───┬────┴─────┬────┴────┬────┘ │
│       │        │        │          │         │       │
│  ┌────┴────┐ ┌─┴──────┐│    ┌─────┴─────┐ ┌┴─────┐ │
│  │AuthSvc  │ │OrthancS││    │AIInference│ │Audit │ │
│  │         │ │        ││    │Service    │ │Svc   │ │
│  └────┬────┘ └───┬────┘│    └─────┬─────┘ └──┬───┘ │
│       │          │     │          │           │      │
└───────┼──────────┼─────┼──────────┼───────────┼──────┘
        │          │     │          │           │
   ┌────┴───┐ ┌───┴──┐ ┌┴────┐ ┌───┴──┐  ┌────┴────┐
   │ Redis  │ │Orthanc│ │ DB  │ │Celery│  │   DB    │
   │(Session)│ │(DICOM)│ │(PG) │ │Worker│  │(audit)  │
   └────────┘ └──────┘ └─────┘ └──────┘  └─────────┘
```

## 5. 데이터베이스 스키마 (PostgreSQL 16) — 40+ 테이블

### 5.1 사용자/인증 테이블

**users**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | 사용자 ID |
| username | VARCHAR(100) | UNIQUE, NOT NULL | 로그인 ID |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt 해시 |
| full_name | VARCHAR(200) | NOT NULL | 실명 |
| role | VARCHAR(50) | NOT NULL, CHECK(IN 6 roles) | 역할 (ADMIN, RADIOLOGIST, RESIDENT, PHYSICIAN, TECHNOLOGIST, RESEARCHER) |
| is_active | BOOLEAN | DEFAULT true | 활성 상태 |
| login_attempts | INTEGER | DEFAULT 0 | 로그인 실패 횟수 |
| locked_until | TIMESTAMPTZ | NULLABLE | 잠금 해제 시각 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |
| updated_at | TIMESTAMPTZ | DEFAULT now() | 수정일 |

**sessions**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 세션 ID |
| user_id | UUID | FK→users.id | 사용자 |
| refresh_token_hash | VARCHAR(255) | NOT NULL | Refresh Token 해시 |
| ip_address | INET | NOT NULL | 접속 IP |
| user_agent | TEXT | | 브라우저 정보 |
| expires_at | TIMESTAMPTZ | NOT NULL | 만료 시각 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |

### 5.2 감사/로그 테이블

**audit_logs**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGSERIAL | PK | 로그 ID |
| user_id | UUID | FK→users.id, NULLABLE | 수행자 |
| action | VARCHAR(100) | NOT NULL, INDEX | 행위 (STUDY_VIEW 등) |
| resource_type | VARCHAR(50) | | 자원 유형 (study, report 등) |
| resource_id | VARCHAR(255) | | 자원 식별자 |
| ip_address | INET | NOT NULL | IP |
| details | JSONB | | 상세 정보 |
| timestamp | TIMESTAMPTZ | DEFAULT now(), INDEX | 시각 |

### 5.3 판독 테이블

**reports**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 리포트 ID |
| study_instance_uid | VARCHAR(128) | NOT NULL, INDEX | Study UID |
| orthanc_study_id | VARCHAR(64) | | Orthanc Study ID |
| author_id | UUID | FK→users.id, INDEX | 작성자 |
| report_type | VARCHAR(50) | NOT NULL | free/structured/soap |
| template_id | UUID | FK→report_templates.id, NULLABLE | 사용 템플릿 |
| content | JSONB | NOT NULL | 리포트 내용 |
| status | VARCHAR(20) | NOT NULL, CHECK | draft/final/amended |
| finalized_at | TIMESTAMPTZ | NULLABLE | 확정 시각 |
| version | INTEGER | DEFAULT 1 | 버전 번호 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |
| updated_at | TIMESTAMPTZ | DEFAULT now() | 수정일 |

**report_templates**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 템플릿 ID |
| name | VARCHAR(200) | NOT NULL, UNIQUE | 템플릿명 |
| modality | VARCHAR(20) | NOT NULL | 적용 모달리티 |
| body_part | VARCHAR(100) | | 검사 부위 |
| content | JSONB | NOT NULL | 템플릿 구조 |
| is_active | BOOLEAN | DEFAULT true | 활성 상태 |
| created_by | UUID | FK→users.id | 생성자 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |

**report_addenda**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | Addendum ID |
| report_id | UUID | FK→reports.id | 원본 리포트 |
| author_id | UUID | FK→users.id | 작성자 |
| content | JSONB | NOT NULL | Addendum 내용 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |

### 5.4 워크리스트 테이블

**worklist_items**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 항목 ID |
| study_instance_uid | VARCHAR(128) | NOT NULL, INDEX | Study UID |
| patient_id | VARCHAR(64) | NOT NULL | Patient ID |
| patient_name | VARCHAR(200) | | 환자명 |
| modality | VARCHAR(20) | NOT NULL | 모달리티 |
| study_date | DATE | NOT NULL | 검사일 |
| study_description | VARCHAR(500) | | 검사 설명 |
| priority | VARCHAR(20) | DEFAULT 'routine', INDEX | emergency/urgent/routine |
| status | VARCHAR(20) | DEFAULT 'unread', INDEX | unread/reading/completed |
| assigned_to | UUID | FK→users.id, INDEX | 배정된 판독의 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |
| updated_at | TIMESTAMPTZ | DEFAULT now() | 수정일 |

### 5.5 AI 테이블

**ai_models**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 모델 ID |
| name | VARCHAR(200) | NOT NULL, UNIQUE | 모델명 |
| version | VARCHAR(50) | NOT NULL | 모델 버전 |
| model_type | VARCHAR(50) | NOT NULL | classification/detection/segmentation |
| modality | VARCHAR(20) | NOT NULL | 적용 모달리티 |
| body_part | VARCHAR(100) | | 대상 부위 |
| endpoint | VARCHAR(500) | | 추론 엔드포인트 |
| engine | VARCHAR(50) | | onnx/mock/cloud |
| is_active | BOOLEAN | DEFAULT false | 활성 상태 |
| config | JSONB | | 모델 설정 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 등록일 |

**ai_tasks**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 작업 ID |
| study_instance_uid | VARCHAR(128) | NOT NULL, INDEX | Study UID |
| model_id | UUID | FK→ai_models.id | 사용 모델 |
| requested_by | UUID | FK→users.id | 요청자 |
| status | VARCHAR(20) | NOT NULL, INDEX | queued/running/completed/failed/cancelled |
| priority | VARCHAR(20) | DEFAULT 'normal' | 우선순위 |
| result | JSONB | NULLABLE | 추론 결과 |
| error_message | TEXT | NULLABLE | 오류 메시지 |
| started_at | TIMESTAMPTZ | NULLABLE | 시작 시각 |
| completed_at | TIMESTAMPTZ | NULLABLE | 완료 시각 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |

### 5.6 검증/정규화 테이블

**validation_rules**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 규칙 ID |
| name | VARCHAR(200) | NOT NULL, UNIQUE | 규칙명 |
| rule_type | VARCHAR(50) | NOT NULL | tag_presence/tag_value/jpeg_density/charset |
| description | TEXT | | 설명 |
| parameters | JSONB | NOT NULL | 규칙 파라미터 |
| severity | VARCHAR(20) | NOT NULL | error/warning/info |
| is_active | BOOLEAN | DEFAULT true | 활성 상태 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |

**normalization_batches**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 배치 ID |
| status | VARCHAR(20) | NOT NULL | pending/running/completed/failed/cancelled |
| total_count | INTEGER | NOT NULL | 전체 건수 |
| processed_count | INTEGER | DEFAULT 0 | 처리 건수 |
| success_count | INTEGER | DEFAULT 0 | 성공 건수 |
| error_count | INTEGER | DEFAULT 0 | 오류 건수 |
| match_rate | DECIMAL(5,2) | NULLABLE | 매칭률 (%) |
| requested_by | UUID | FK→users.id | 요청자 |
| started_at | TIMESTAMPTZ | NULLABLE | 시작 시각 |
| completed_at | TIMESTAMPTZ | NULLABLE | 완료 시각 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 생성일 |

**normalization_results**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 결과 ID |
| batch_id | UUID | FK→normalization_batches.id, INDEX | 배치 |
| study_instance_uid | VARCHAR(128) | NOT NULL | Study UID |
| status | VARCHAR(20) | NOT NULL | success/error/skipped |
| changes | JSONB | | 변경 내역 |
| error_message | TEXT | NULLABLE | 오류 메시지 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 처리일 |

### 5.7 QC/기타 테이블

**qc_history**
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | UUID | PK | 이력 ID |
| action | VARCHAR(50) | NOT NULL | merge/split/modify_tags/anonymize |
| source_studies | JSONB | NOT NULL | 원본 Study UID 목록 |
| target_studies | JSONB | NOT NULL | 결과 Study UID 목록 |
| changes | JSONB | | 변경 상세 |
| performed_by | UUID | FK→users.id | 수행자 |
| is_reversible | BOOLEAN | DEFAULT true | 되돌리기 가능 여부 |
| reverted_at | TIMESTAMPTZ | NULLABLE | 되돌린 시각 |
| created_at | TIMESTAMPTZ | DEFAULT now() | 수행일 |

### 5.8 테이블 합계

| 영역 | 테이블 | 수 |
|------|--------|-----|
| 사용자/인증 | users, sessions | 2 |
| 감사 | audit_logs | 1 |
| 판독 | reports, report_templates, report_addenda | 3 |
| 워크리스트 | worklist_items | 1 |
| AI | ai_models, ai_tasks | 2 |
| 검증/정규화 | validation_rules, normalization_batches, normalization_results | 3 |
| QC | qc_history | 1 |
| 마이그레이션 | migration_jobs, migration_results | 2 |
| DICOM 이슈 | dicom_issue_rules, modality_render_config, dicom_message_templates 등 | 10+ |
| 영상 수집 | upload_queue, patient_upload_tokens, dicom_remotes 등 | 10+ |
| 기타 확장 | sla_escalation, retake_requests, consult_requests 등 | 5+ |
| **합계** | | **40+** |

## 6. 인덱스 전략

| 테이블 | 인덱스 | 유형 | 용도 |
|--------|--------|------|------|
| users | username | UNIQUE | 로그인 조회 |
| users | role | B-tree | 역할별 필터 |
| audit_logs | (user_id, timestamp) | Composite | 사용자별 시간순 조회 |
| audit_logs | action | B-tree | 행위별 필터 |
| audit_logs | timestamp | B-tree | 날짜 범위 조회 |
| reports | study_instance_uid | B-tree | Study별 리포트 조회 |
| reports | (author_id, created_at) | Composite | 작성자별 최신순 |
| reports | status | B-tree | 상태별 필터 |
| worklist_items | (assigned_to, priority) | Composite | 배정자별 우선순위 |
| worklist_items | (status, study_date) | Composite | 상태+날짜 필터 |
| ai_tasks | (status, created_at) | Composite | 큐 조회 |
| ai_tasks | study_instance_uid | B-tree | Study별 AI 작업 |
| normalization_batches | status | B-tree | 상태별 필터 |
| normalization_results | batch_id | B-tree | 배치별 결과 |

## 7. 확장 모듈

- **uuid-ossp**: UUID v4 생성 (`uuid_generate_v4()`)
- **pgcrypto**: 암호화 함수 (`pgp_sym_encrypt`, `pgp_sym_decrypt`) — 민감 필드 암호화

## 8. 인터페이스 설계

### 8.1 외부 인터페이스

| 인터페이스 | 프로토콜 | 포트 | 용도 |
|------------|----------|------|------|
| DICOMweb | HTTPS (WADO-RS, STOW-RS, QIDO-RS) | 443 | 영상 조회/저장 |
| DIMSE | TCP (C-STORE, C-FIND, C-MOVE, C-ECHO) | 4242 | 레거시 DICOM 통신 |
| REST API | HTTPS + JSON | 443 | 클라이언트-서버 통신 |
| WebSocket | WSS | 443 | 실시간 알림 (5 channels) |
| WADO-URI | HTTPS | 443 | 레거시 영상 조회 |

### 8.2 내부 인터페이스

| From | To | 방식 | 인증 |
|------|----|------|------|
| Nginx → Backend | HTTP | localhost:8001 | 없음 (내부) |
| Nginx → Orthanc | HTTP | localhost:8042 | Basic Auth 자동 삽입 |
| Nginx → OHIF | HTTP | localhost:3001 | 없음 |
| Backend → Orthanc | HTTP (httpx async) | localhost:8042 | Basic Auth |
| Backend → PostgreSQL | TCP (SQLAlchemy async) | localhost:5432 | username/password |
| Backend → Redis | TCP (aioredis) | localhost:6379 | 없음 (로컬) |
| Backend → Celery | Redis (broker) | localhost:6379 | 없음 (로컬) |
| Celery → Orthanc | HTTP | localhost:8042 | Basic Auth |
| Celery → PostgreSQL | TCP | localhost:5432 | username/password |

## 9. 보안 설계

| 항목 | 구현 | 상세 |
|------|------|------|
| 전송 암호화 | TLS 1.3 (Let's Encrypt) | 90일 자동 갱신, A+ 등급 |
| 인증 | JWT | Access: HS256, 1h / Refresh: 7d |
| 비밀번호 | bcrypt | cost factor 12, salt 자동 |
| 권한 | RBAC 6개 역할 | ADMIN, RADIOLOGIST, RESIDENT, PHYSICIAN, TECHNOLOGIST, RESEARCHER |
| 세션 | Redis 기반 | 동시 세션 3개 제한, IP 기록 |
| 감사 | AuditMiddleware | 모든 API 호출 자동 기록, 삭제 불가 |
| Rate Limit | Redis 기반 | 100 req/min (인증 API: 10 req/min) |
| CORS | 화이트리스트 | 허용 도메인만 접근 |
| CSP | Nginx 헤더 | script-src, style-src 제한 |
| 계정 잠금 | 5회 실패 시 30분 잠금 | login_attempts, locked_until |

## 10. 참조 문서

- TD-001 요구사항 명세서 (340+ endpoints)
- TD-003 아키텍처 설계서
- CS-001 사이버보안 계획서
- CS-002 SBOM (64 패키지)
