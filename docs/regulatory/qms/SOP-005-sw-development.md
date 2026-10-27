# SOP-005 소프트웨어 개발 절차서 (Software Development Procedure)

| 항목 | 내용 |
|------|------|
| 문서 ID | SOP-005 |
| 버전 | 1.0 |
| 작성일 | 2026-05-18 |
| 상태 | 승인 |
| 검토일 | 2026-05-27 |
| 승인일 | 2026-05-27 |
| 적용 표준 | IEC 62304:2006+A1:2015 (Class B) |
| 제품명 | WeRU.B PACS |
| 등급 | 2등급 의료기기 |

## 1. 목적

IEC 62304에 따라 WeRU.B PACS 소프트웨어 의료기기의 개발 생명주기 프로세스를 정의한다. Class B 소프트웨어에 요구되는 활동, 산출물, 추적성을 규정한다.

## 2. 소프트웨어 안전 등급 분류

| 구성요소 | 안전 등급 | 근거 |
|----------|-----------|------|
| WeRU.B Viewer (영상 표시) | Class B | 오류 시 진단 지연 가능, 생명 위협은 낮음 |
| Orthanc DICOM Server | Class B | 데이터 손실 시 진단 불가 |
| FastAPI Backend | Class B | 인증/권한 오류 시 데이터 노출 위험 |
| AI 추론 엔진 | Class B | 보조 도구로 최종 진단은 의사가 수행 |

## 3. 소프트웨어 개발 프로세스

### 3.1 소프트웨어 개발 계획 (§5.1)
- 개발 모델: Agile + Phase Gate (8 Phases)
- 형상관리: Git (GitHub), 브랜치 전략 (main + feature branches)
- 코딩 표준: Python PEP 8, TypeScript ESLint
- 빌드 환경: Docker Compose (13 services)

### 3.2 소프트웨어 요구사항 분석 (§5.2)
- 기능 요구사항: 340+ API endpoints (TD-001 참조)
- 성능 요구사항: p95 < 200ms, 동시 100 사용자
- 보안 요구사항: TLS 1.3, JWT, RBAC — 6개 역할 (ADMIN, RADIOLOGIST, RESIDENT, PHYSICIAN, TECHNOLOGIST, RESEARCHER)
- DICOM 적합성: DICOM 3.0, DICOMweb WADO-RS/STOW-RS/QIDO-RS

### 3.3 소프트웨어 아키텍처 설계 (§5.3)
- 마이크로서비스 아키텍처 (Docker 컨테이너)
- 구성요소 간 인터페이스 정의 (TD-003 참조)
- SOUP 식별 및 관리 (§8)

### 3.4 소프트웨어 상세 설계 (§5.4)
- 모듈별 상세 설계 (TD-002 참조)
- DB 스키마 설계 (PostgreSQL 16)
- API 인터페이스 명세 (OpenAPI 3.0)

### 3.5 소프트웨어 단위 구현 및 검증 (§5.5)
- 단위 테스트: pytest (150 test cases)
- 코드 리뷰: PR 기반 리뷰 필수
- 정적 분석: mypy, ruff

### 3.6 소프트웨어 통합 및 통합 테스트 (§5.6)
- E2E 테스트: 31개 테스트 로컬 통과
- API 통합 테스트: httpx AsyncClient
- DICOM 프로토콜 테스트: C-STORE, C-FIND, C-MOVE

### 3.7 소프트웨어 시스템 테스트 (§5.7)
- 부하 테스트: Locust (p95 = 142ms)
- 보안 테스트: 취약점 스캔, 침투 테스트
- 호환성 테스트: Chrome, Firefox, Safari, Edge

## 4. SOUP (Software of Unknown Provenance) 관리

| SOUP | 버전 | 용도 | 위험 등급 |
|------|------|------|-----------|
| Orthanc | 1.12.11 | DICOM 서버 | High |
| OHIF Viewer | v3.12 | 웹 뷰어 프레임워크 | High |
| FastAPI | 0.115+ | REST API 프레임워크 | Medium |
| pydicom | 3.0.2 | DICOM 파싱 | High |
| PostgreSQL | 16 | 데이터베이스 | Medium |
| Redis | 7 | 캐시/큐 | Low |

### SOUP 관리 활동
- 버전 고정 (requirements.txt, package-lock.json)
- 보안 취약점 모니터링 (Dependabot, Snyk)
- 업데이트 시 회귀 테스트 수행

## 5. 소프트웨어 유지보수 (§6)

- 문제 보고 접수 및 분류
- 영향 분석 수행 (SOP-007 변경관리 참조)
- 수정 구현 및 검증
- 릴리스 노트 작성

## 6. 추적성 매트릭스

요구사항 → 설계 → 구현 → 테스트 간 양방향 추적성을 유지한다.

| 추적 관계 | 도구 |
|-----------|------|
| 요구사항 ↔ 설계 | TD-001 ↔ TD-002 상호참조 |
| 설계 ↔ 코드 | 모듈명 매핑 (app/routers/) |
| 요구사항 ↔ 테스트 | 테스트 ID 매핑 (tests/) |

## 7. 참조 문서

- SOP-003 설계관리 절차서
- TD-001 요구사항 명세서
- TD-002 설계 명세서
- TD-003 아키텍처 설계서
- TD-005 V&V 보고서
