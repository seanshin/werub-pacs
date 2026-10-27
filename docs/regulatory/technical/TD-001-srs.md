# TD-001 소프트웨어 요구사항 명세서 (Software Requirements Specification)

| 항목 | 내용 |
|------|------|
| 문서 ID | TD-001 |
| 버전 | 2.0 |
| 작성일 | 2026-05-18 |
| 상태 | 승인 |
| 적용 표준 | IEC 62304:2006+A1:2015 §5.2 |
| 제품명 | WeRU.B PACS |
| 총 API Endpoints | 340+ |
| 검토일 | 2026-05-27 |
| 승인일 | 2026-05-27 |

## 1. 목적

WeRU.B PACS 소프트웨어 의료기기의 기능적/비기능적 요구사항을 정의하고, 340+ API endpoints를 모듈별로 분류하여 추적성을 확보한다. 각 엔드포인트의 요청/응답 형식을 포함하여 구현과 검증의 기준으로 활용한다.

## 2. 시스템 개요

WeRU.B PACS는 DICOM 영상 저장, 조회, 표시 기능을 제공하는 웹 기반 PACS 소프트웨어로, DICOMweb 표준 프로토콜과 WeRU.B Viewer(OHIF v3.12 기반)를 통해 의료 영상을 관리한다. 13개 Docker 컨테이너, 40+ DB 테이블, 340+ API 엔드포인트로 구성된다. AI 모델 29개 (의료 13종, 범용 16종)를 연동하며, 6개 역할 (ADMIN, RADIOLOGIST, RESIDENT, PHYSICIAN, TECHNOLOGIST, RESEARCHER)로 접근을 제어한다.

## 3. 기능 요구사항 — API Endpoints (340+, 아래는 핵심 137개)

### 3.1 인증/권한 모듈 (Authentication & Authorization) — 6 endpoints

| ID | Method | Endpoint | 기능 | Request | Response |
|----|--------|----------|------|---------|----------|
| AUTH-001 | POST | /api/v1/auth/login | JWT 로그인 | `{username, password}` | `{access_token, refresh_token, token_type, expires_in}` |
| AUTH-002 | POST | /api/v1/auth/logout | 로그아웃 (토큰 무효화) | `{refresh_token}` | `{message: "logged out"}` |
| AUTH-003 | POST | /api/v1/auth/refresh | Access Token 갱신 | `{refresh_token}` | `{access_token, expires_in}` |
| AUTH-004 | GET | /api/v1/auth/me | 현재 사용자 정보 | Bearer Token | `{id, username, role, is_active}` |
| AUTH-005 | POST | /api/v1/auth/change-password | 비밀번호 변경 | `{current_password, new_password}` | `{message}` |
| AUTH-006 | POST | /api/v1/auth/reset-password | 비밀번호 초기화 (Admin) | `{user_id, new_password}` | `{message}` |

### 3.2 사용자 관리 모듈 (User Management) — 7 endpoints

| ID | Method | Endpoint | 기능 | Request/Response |
|----|--------|----------|------|------------------|
| USR-001 | GET | /api/v1/users | 사용자 목록 조회 | → `[{id, username, full_name, role, is_active}]` |
| USR-002 | POST | /api/v1/users | 사용자 생성 | `{username, password, full_name, role}` → `{id, username}` |
| USR-003 | GET | /api/v1/users/{id} | 사용자 상세 조회 | → `{id, username, full_name, role, created_at}` |
| USR-004 | PUT | /api/v1/users/{id} | 사용자 수정 | `{full_name, role, is_active}` → `{id, username}` |
| USR-005 | DELETE | /api/v1/users/{id} | 사용자 삭제 (비활성화) | → `{message}` |
| USR-006 | PUT | /api/v1/users/{id}/role | 역할 변경 | `{role}` → `{id, role}` |
| USR-007 | GET | /api/v1/users/{id}/activity | 사용자 활동 이력 | → `[{action, timestamp, resource}]` |

### 3.3 시스템 관리 모듈 (System) — 6 endpoints

| ID | Method | Endpoint | 기능 | Response |
|----|--------|----------|------|----------|
| SYS-001 | GET | /api/v1/system/info | Orthanc 시스템 정보 | `{version, dicom_aet, plugins}` |
| SYS-002 | GET | /api/v1/statistics | 저장소 통계 | `{studies, series, instances, patients, disk_size}` |
| SYS-003 | GET | /api/v1/health | 헬스체크 | `{status, orthanc, postgres, redis, uptime}` |
| SYS-004 | GET | /api/v1/system/modalities | 등록된 모달리티 목록 | `{modality: {aet, host, port}}` |
| SYS-005 | PUT | /api/v1/system/modalities/{name} | 모달리티 등록/수정 | `{aet, host, port}` |
| SYS-006 | DELETE | /api/v1/system/modalities/{name} | 모달리티 삭제 | `{message}` |

### 3.4 영상 관리 모듈 (Study/Series/Instance) — 22 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| IMG-001 | GET | /api/v1/studies | Study 목록 조회 (페이지네이션, 필터) |
| IMG-002 | GET | /api/v1/studies/{id} | Study 상세 조회 |
| IMG-003 | DELETE | /api/v1/studies/{id} | Study 삭제 |
| IMG-004 | GET | /api/v1/studies/{id}/series | Series 목록 조회 |
| IMG-005 | GET | /api/v1/studies/{id}/series/{series_id} | Series 상세 |
| IMG-006 | DELETE | /api/v1/studies/{id}/series/{series_id} | Series 삭제 |
| IMG-007 | GET | /api/v1/studies/{id}/series/{sid}/instances | Instance 목록 |
| IMG-008 | GET | /api/v1/instances/{id} | Instance 상세 |
| IMG-009 | DELETE | /api/v1/instances/{id} | Instance 삭제 |
| IMG-010 | GET | /api/v1/studies/{id}/metadata | Study 메타데이터 (DICOM 태그) |
| IMG-011 | PUT | /api/v1/studies/{id}/metadata | Study 메타데이터 수정 |
| IMG-012 | GET | /api/v1/patients | Patient 목록 조회 |
| IMG-013 | GET | /api/v1/patients/{id} | Patient 상세 |
| IMG-014 | GET | /api/v1/patients/{id}/studies | Patient별 Study 목록 |
| IMG-015 | POST | /api/v1/studies/{id}/send | Study를 외부 DICOM 노드로 전송 |
| IMG-016 | GET | /api/v1/studies/{id}/preview | Study 썸네일 미리보기 |
| IMG-017 | GET | /api/v1/studies/{id}/archive | Study DICOM ZIP 다운로드 |
| IMG-018 | POST | /api/v1/upload | DICOM 파일 업로드 |
| IMG-019 | GET | /api/v1/studies/search | 고급 검색 (다중 조건) |
| IMG-020 | GET | /api/v1/studies/{id}/statistics | Study 통계 (시리즈 수, 인스턴스 수) |
| IMG-021 | GET | /api/v1/studies/{id}/shared-tags | 공유 태그 조회 |
| IMG-022 | POST | /api/v1/studies/{id}/anonymize | Study 익명화 |

### 3.5 DICOMweb 모듈 — 8 endpoints

| ID | Method | Endpoint | 기능 | 표준 |
|----|--------|----------|------|------|
| DW-001 | GET | /dicom-web/studies | QIDO-RS Study 검색 | DICOM PS3.18 |
| DW-002 | GET | /dicom-web/studies/{uid}/series | QIDO-RS Series 검색 | DICOM PS3.18 |
| DW-003 | GET | /dicom-web/studies/{uid}/series/{uid}/instances | QIDO-RS Instance | DICOM PS3.18 |
| DW-004 | GET | /dicom-web/studies/{uid}/series/{uid}/instances/{uid} | WADO-RS 인스턴스 조회 | DICOM PS3.18 |
| DW-005 | GET | /dicom-web/studies/{uid}/metadata | WADO-RS 메타데이터 | DICOM PS3.18 |
| DW-006 | GET | /dicom-web/studies/{uid}/series/{uid}/instances/{uid}/rendered | 렌더링 이미지 | DICOM PS3.18 |
| DW-007 | POST | /dicom-web/studies | STOW-RS 영상 업로드 | DICOM PS3.18 |
| DW-008 | GET | /wado | WADO-URI 레거시 조회 | DICOM PS3.18 |

### 3.6 검증/정규화 모듈 (Validation & Normalization) — 12 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| VAL-001 | POST | /api/v1/validation/dicom | DICOM 표준 검증 (16 규칙) |
| VAL-002 | POST | /api/v1/validation/jpeg-density | JPEG 밀도(Xdensity/Ydensity) vs Pixel Spacing 교차 검증 |
| VAL-003 | GET | /api/v1/validation/rules | 검증 규칙 목록 조회 |
| VAL-004 | POST | /api/v1/validation/rules | 검증 규칙 추가 |
| VAL-005 | PUT | /api/v1/validation/rules/{id} | 검증 규칙 수정 |
| VAL-006 | DELETE | /api/v1/validation/rules/{id} | 검증 규칙 삭제 |
| NRM-001 | POST | /api/v1/normalization/batch | 배치 정규화 실행 |
| NRM-002 | GET | /api/v1/normalization/batches | 배치 목록 조회 |
| NRM-003 | GET | /api/v1/normalization/batches/{id} | 배치 상세/진행률 |
| NRM-004 | POST | /api/v1/normalization/batches/{id}/cancel | 배치 취소 |
| NRM-005 | GET | /api/v1/normalization/batches/{id}/results | 배치 결과 조회 |
| NRM-006 | GET | /api/v1/normalization/statistics | 정규화 통계 (match rate 등) |

### 3.7 워크리스트 모듈 (Worklist) — 8 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| WL-001 | GET | /api/v1/worklist | 워크리스트 조회 (필터, 페이지네이션) |
| WL-002 | POST | /api/v1/worklist | 워크리스트 항목 생성 |
| WL-003 | GET | /api/v1/worklist/{id} | 워크리스트 항목 상세 |
| WL-004 | PUT | /api/v1/worklist/{id} | 워크리스트 항목 수정 |
| WL-005 | DELETE | /api/v1/worklist/{id} | 워크리스트 항목 삭제 |
| WL-006 | PUT | /api/v1/worklist/{id}/assign | 판독의 배정 |
| WL-007 | PUT | /api/v1/worklist/{id}/priority | 우선순위 변경 |
| WL-008 | PUT | /api/v1/worklist/{id}/status | 상태 변경 (미판독/판독중/완료) |

### 3.8 판독 리포트 모듈 (Reports) — 13 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| RPT-001 | GET | /api/v1/reports | 리포트 목록 조회 |
| RPT-002 | POST | /api/v1/reports | 리포트 생성 |
| RPT-003 | GET | /api/v1/reports/{id} | 리포트 상세 |
| RPT-004 | PUT | /api/v1/reports/{id} | 리포트 수정 |
| RPT-005 | DELETE | /api/v1/reports/{id} | 리포트 삭제 (Draft만) |
| RPT-006 | PUT | /api/v1/reports/{id}/finalize | 리포트 최종 확정 |
| RPT-007 | GET | /api/v1/reports/{id}/versions | 리포트 버전 이력 |
| RPT-008 | POST | /api/v1/reports/{id}/addendum | Addendum 추가 |
| RPT-009 | GET | /api/v1/reports/templates | 리포트 템플릿 목록 (20개) |
| RPT-010 | POST | /api/v1/reports/templates | 템플릿 생성 |
| RPT-011 | PUT | /api/v1/reports/templates/{id} | 템플릿 수정 |
| RPT-012 | DELETE | /api/v1/reports/templates/{id} | 템플릿 삭제 |
| RPT-013 | GET | /api/v1/reports/study/{study_uid} | Study별 리포트 조회 |

### 3.9 QC 모듈 (Quality Control) — 7 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| QC-001 | POST | /api/v1/qc/merge | Study 병합 |
| QC-002 | POST | /api/v1/qc/split | Study 분리 |
| QC-003 | POST | /api/v1/qc/modify-tags | DICOM 태그 수정 |
| QC-004 | POST | /api/v1/qc/anonymize | 익명화 (개인정보 제거) |
| QC-005 | GET | /api/v1/qc/history | QC 작업 이력 |
| QC-006 | GET | /api/v1/qc/history/{id} | QC 작업 상세 |
| QC-007 | POST | /api/v1/qc/undo/{id} | QC 작업 되돌리기 |

### 3.10 감사 로그 모듈 (Audit) — 4 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| AUD-001 | GET | /api/v1/audit-log | 감사 로그 조회 (필터, 페이지네이션) |
| AUD-002 | GET | /api/v1/audit-log/{id} | 감사 로그 상세 |
| AUD-003 | GET | /api/v1/audit-log/export | 감사 로그 내보내기 (CSV/JSON) |
| AUD-004 | GET | /api/v1/audit-log/statistics | 감사 로그 통계 |

### 3.11 AI 모듈 (AI Inference) — 18 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| AI-001 | POST | /api/v1/ai/inference | AI 추론 요청 |
| AI-002 | GET | /api/v1/ai/inference/{task_id} | 추론 상태/결과 조회 |
| AI-003 | POST | /api/v1/ai/inference/{task_id}/cancel | 추론 취소 |
| AI-004 | GET | /api/v1/ai/models | AI 모델 목록 |
| AI-005 | POST | /api/v1/ai/models | AI 모델 등록 |
| AI-006 | GET | /api/v1/ai/models/{id} | 모델 상세 |
| AI-007 | PUT | /api/v1/ai/models/{id} | 모델 수정 |
| AI-008 | DELETE | /api/v1/ai/models/{id} | 모델 삭제 |
| AI-009 | PUT | /api/v1/ai/models/{id}/activate | 모델 활성화/비활성화 |
| AI-010 | GET | /api/v1/ai/dashboard | AI 대시보드 (통계) |
| AI-011 | GET | /api/v1/ai/dashboard/performance | 모델별 성능 통계 |
| AI-012 | GET | /api/v1/ai/queue | 추론 큐 상태 |
| AI-013 | GET | /api/v1/ai/results | 추론 결과 목록 |
| AI-014 | GET | /api/v1/ai/results/{id} | 추론 결과 상세 |
| AI-015 | POST | /api/v1/ai/soap | SOAP 자동 생성 |
| AI-016 | POST | /api/v1/ai/differential-diagnosis | 감별진단 제안 |
| AI-017 | POST | /api/v1/ai/comparative-reading | 비교판독 지원 |
| AI-018 | GET | /api/v1/ai/results/{id}/dicom | AI 결과 DICOM 형식 조회 (SR/SC/SEG) |

### 3.12 배치 처리 모듈 (Batch) — 6 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| BAT-001 | POST | /api/v1/batch/validation | 배치 검증 실행 |
| BAT-002 | POST | /api/v1/batch/normalization | 배치 정규화 실행 |
| BAT-003 | GET | /api/v1/batch/jobs | 배치 작업 목록 |
| BAT-004 | GET | /api/v1/batch/jobs/{id} | 배치 작업 상세 |
| BAT-005 | POST | /api/v1/batch/jobs/{id}/cancel | 배치 작업 취소 |
| BAT-006 | GET | /api/v1/batch/jobs/{id}/results | 배치 작업 결과 |

### 3.13 마이그레이션 모듈 (Migration) — 5 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| MIG-001 | POST | /api/v1/migration/import | 외부 PACS 데이터 가져오기 |
| MIG-002 | GET | /api/v1/migration/status | 마이그레이션 상태 |
| MIG-003 | POST | /api/v1/cd-import/upload | CD/DVD DICOM 업로드 |
| MIG-004 | GET | /api/v1/cd-import/preview | CD 내용 미리보기 |
| MIG-005 | POST | /api/v1/cd-import/confirm | CD 가져오기 확정 |

### 3.14 HospitalRun 연동 모듈 — 5 endpoints

| ID | Method | Endpoint | 기능 |
|----|--------|----------|------|
| HR-001 | GET | /api/v1/hospitalrun/patients | HospitalRun 환자 목록 동기화 |
| HR-002 | GET | /api/v1/hospitalrun/patients/{id} | HospitalRun 환자 상세 |
| HR-003 | POST | /api/v1/hospitalrun/link | PACS Study ↔ HospitalRun 환자 연결 |
| HR-004 | GET | /api/v1/hospitalrun/orders | 오더 목록 조회 |
| HR-005 | PUT | /api/v1/hospitalrun/orders/{id}/status | 오더 상태 업데이트 |

### 3.15 WebSocket 이벤트 — 5 endpoints

| ID | Protocol | Endpoint | 이벤트 |
|----|----------|----------|--------|
| WS-001 | WSS | /ws/notifications | 실시간 알림 (새 Study, AI 완료 등) |
| WS-002 | WSS | /ws/study-updates | Study 상태 변경 알림 |
| WS-003 | WSS | /ws/ai-progress | AI 추론 진행률 |
| WS-004 | WSS | /ws/worklist-updates | 워크리스트 변경 알림 |
| WS-005 | WSS | /ws/system-alerts | 시스템 경고 (디스크, 서비스 장애) |

### 3.16 엔드포인트 합계

| 모듈 | Endpoints |
|------|-----------|
| 인증 (Auth) | 6 |
| 사용자 (Users) | 7 |
| 시스템 (System) | 6 |
| 영상 관리 (Studies/Series/Instance) | 22 |
| DICOMweb | 8 |
| 검증/정규화 (Validation/Normalization) | 12 |
| 워크리스트 (Worklist) | 8 |
| 판독 리포트 (Reports) | 13 |
| QC | 7 |
| 감사 로그 (Audit) | 4 |
| AI | 18 |
| 배치 (Batch) | 6 |
| 마이그레이션/CD Import | 5 |
| HospitalRun 연동 | 5 |
| WebSocket | 5 |
| **합계** | **132 REST + 5 WebSocket = 137** |

## 4. 주요 API Request/Response 상세

### 4.1 AUTH-001 로그인

```
POST /api/v1/auth/login
Content-Type: application/json

Request:
{
  "username": "dr.kim",
  "password": "CHANGE_ME"
}

Response (200 OK):
{
  "access_token": "CHANGE_ME",
  "refresh_token": "CHANGE_ME",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "a1b2c3d4-...",
    "username": "dr.kim",
    "full_name": "김영상",
    "role": "radiologist"
  }
}

Response (401 Unauthorized):
{"detail": "Invalid credentials"}
```

### 4.2 IMG-001 Study 목록 조회

```
GET /api/v1/studies?page=1&limit=20&modality=CT&date_from=2026-05-01
Authorization: Bearer <token>

Response (200 OK):
{
  "total": 150,
  "page": 1,
  "limit": 20,
  "studies": [
    {
      "orthanc_id": "abc123...",
      "study_instance_uid": "1.2.840...",
      "patient_name": "홍길동",
      "patient_id": "P001234",
      "study_date": "2026-05-18",
      "modality": "CT",
      "study_description": "CHEST CT",
      "series_count": 3,
      "instance_count": 450
    }
  ]
}
```

### 4.3 AI-001 AI 추론 요청

```
POST /api/v1/ai/inference
Authorization: Bearer <token>
Content-Type: application/json

Request:
{
  "study_instance_uid": "1.2.840...",
  "model_id": "chest-ct-nodule-v1",
  "priority": "normal",
  "parameters": {"threshold": 0.7}
}

Response (202 Accepted):
{
  "task_id": "task-uuid-...",
  "status": "queued",
  "estimated_time": 30
}
```

## 5. 비기능 요구사항

| ID | 분류 | 요구사항 | 기준 | 검증 방법 |
|----|------|----------|------|-----------|
| NFR-001 | 성능 | API 응답시간 | p95 < 200ms | 부하 테스트 (TD-004) |
| NFR-002 | 성능 | 동시 사용자 | 50명 이상 | 부하 테스트 (TD-004) |
| NFR-003 | 성능 | 영상 로딩 | CT 300 slice < 3s | 렌더링 테스트 (TD-004) |
| NFR-004 | 보안 | 전송 암호화 | TLS 1.3 | SSL Labs 테스트 |
| NFR-005 | 보안 | 인증 | JWT (Access 1h, Refresh 7d) | 기능 테스트 |
| NFR-006 | 보안 | 비밀번호 | bcrypt cost factor 12 | 코드 검증 |
| NFR-007 | 보안 | 권한 관리 | RBAC 6개 역할 (ADMIN, RADIOLOGIST, RESIDENT, PHYSICIAN, TECHNOLOGIST, RESEARCHER) | 권한 매트릭스 테스트 |
| NFR-008 | 보안 | 감사 추적 | 모든 데이터 접근 기록 | 감사 로그 검증 |
| NFR-009 | 가용성 | 서비스 가동률 | 99.5% | 모니터링 |
| NFR-010 | 가용성 | 장애 복구 | Docker auto-restart | 장애 테스트 |
| NFR-011 | 호환성 | 브라우저 | Chrome 120+, Firefox 120+, Safari 17+, Edge 120+ | 호환성 테스트 |
| NFR-012 | 데이터 | 보존 기간 | 의료법 5년 | 정책 검증 |
| NFR-013 | 데이터 | 백업 | 일일 자동, WAL 연속 | 복구 테스트 |
| NFR-014 | 표준 | DICOM 적합성 | PS3.4, PS3.7, PS3.18 | DIMSE/DICOMweb 테스트 |

## 6. 추적성 매트릭스

각 기능 요구사항(340+ endpoints)은 다음과 연결된다:
- 설계 항목 (TD-002 모듈/서비스)
- 구현 코드 (app/routers/*.py)
- 테스트 케이스 (TD-005 V&V 보고서)
- 위험 항목 (RM-002 FMEA)

## 7. 참조 문서

- TD-002 설계 명세서
- TD-003 아키텍처 설계서
- TD-004 성능시험 보고서
- TD-005 V&V 보고서
- RM-001 위험관리 계획서
- CS-001 사이버보안 계획서
