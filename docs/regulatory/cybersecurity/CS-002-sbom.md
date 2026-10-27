# CS-002 소프트웨어 자재 명세서 (SBOM — Software Bill of Materials)

| 항목 | 내용 |
|------|------|
| 문서 ID | CS-002 |
| 버전 | 1.0 |
| 작성일 | 2026-05-18 |
| 상태 | 승인 |
| 검토일 | 2026-05-27 |
| 승인일 | 2026-05-27 |
| 적용 표준 | 식약처 의료기기 사이버보안 가이드라인, NTIA SBOM |
| 제품명 | WeRU.B PACS |
| 총 패키지 수 | 64개 |

## 1. 목적

WeRU.B PACS에 포함된 모든 소프트웨어 구성요소(SOUP)를 식별하고, 버전, 라이선스, 보안 상태를 문서화하여 취약점 관리 및 규제 요건을 충족한다.

## 2. SBOM 형식

- 형식: SPDX 2.3 호환
- 생성 도구: pip-audit, npm audit
- 갱신 주기: 월간 (또는 릴리스 시)

## 3. 핵심 구성요소 (Tier 1 — 직접 의존성)

### 3.1 Backend (Python 3.12) — 32 packages

| # | 패키지 | 버전 | 라이선스 | 용도 | 보안 상태 |
|---|--------|------|----------|------|-----------|
| 1 | fastapi | 0.115.x | MIT | REST API 프레임워크 | OK |
| 2 | uvicorn | 0.30.x | BSD-3 | ASGI 서버 | OK |
| 3 | sqlalchemy | 2.0.x | MIT | ORM / DB 접근 | OK |
| 4 | asyncpg | 0.29.x | Apache-2.0 | PostgreSQL async driver | OK |
| 5 | pydicom | 3.0.2 | MIT | DICOM 파싱 | **PATCHED** |
| 6 | python-jose | 3.5.0 | MIT | JWT 처리 | **PATCHED** |
| 7 | python-multipart | 0.0.29 | Apache-2.0 | Form/File 업로드 | **PATCHED** |
| 8 | httpx | 0.27.x | BSD-3 | HTTP 클라이언트 (Orthanc 통신) | OK |
| 9 | passlib[bcrypt] | 1.7.4 | BSD-3 | 비밀번호 해싱 | OK |
| 10 | celery | 5.4.x | BSD-3 | 비동기 작업 큐 | OK |
| 11 | redis | 5.0.x | MIT | Redis 클라이언트 | OK |
| 12 | pydantic | 2.7.x | MIT | 데이터 검증 | OK |
| 13 | alembic | 1.13.x | MIT | DB 마이그레이션 | OK |
| 14 | python-dotenv | 1.0.x | BSD-3 | 환경변수 관리 | OK |
| 15 | websockets | 12.x | BSD-3 | WebSocket 지원 | OK |
| 16 | pillow | 10.x | HPND | 이미지 처리 | OK |
| 17 | numpy | 1.26.x | BSD-3 | 수치 연산 (AI) | OK |
| 18 | onnxruntime | 1.18.x | MIT | AI 추론 엔진 | OK |
| 19-32 | (기타 14개) | - | MIT/BSD | 유틸리티, 로깅, 테스트 | OK |

### 3.2 Frontend / Viewer — 18 packages

| # | 패키지 | 버전 | 라이선스 | 용도 | 보안 상태 |
|---|--------|------|----------|------|-----------|
| 1 | @ohif/app | 3.12.x | MIT | DICOM 웹 뷰어 | OK |
| 2 | cornerstone3d | 1.x | MIT | 영상 렌더링 엔진 | OK |
| 3 | react | 18.x | MIT | UI 프레임워크 | OK |
| 4 | next | 14.x | MIT | Admin 앱 프레임워크 | OK |
| 5-18 | (기타 14개) | - | MIT/BSD | UI 컴포넌트, 상태관리 | OK |

### 3.3 Infrastructure — 14 packages

| # | 구성요소 | 버전 | 라이선스 | 용도 | 보안 상태 |
|---|----------|------|----------|------|-----------|
| 1 | Orthanc | 1.12.11 | GPLv3 | DICOM 서버 | OK |
| 2 | PostgreSQL | 16 | PostgreSQL | 관계형 DB | OK |
| 3 | Redis | 7 | BSD-3 | 캐시/브로커 | OK |
| 4 | Nginx | 1.24 | BSD-2 | 리버스 프록시 | OK |
| 5 | Docker Engine | 24.x | Apache-2.0 | 컨테이너 런타임 | OK |
| 6 | GDCM | 3.0.x | BSD-3 | DICOM 코덱 | OK |
| 7-14 | (기타 8개) | - | 다양 | 플러그인, 도구 | OK |

## 4. 패치된 취약점 상세

### 4.1 pydicom 3.0.2 (CVE-2024-XXXXX)
- **취약점**: 악의적 DICOM 파일 파싱 시 메모리 오버플로우
- **영향**: 서비스 거부 (DoS) 가능
- **조치**: 3.0.2로 업그레이드 (2026-04)
- **검증**: 악성 DICOM 샘플 테스트 통과

### 4.2 python-jose 3.5.0 (CVE-2024-XXXXX)
- **취약점**: 특정 조건에서 JWT 서명 검증 우회
- **영향**: 인증 우회 가능
- **조치**: 3.5.0으로 업그레이드 (2026-04)
- **검증**: JWT 변조 테스트 시 정상 거부 확인

### 4.3 python-multipart 0.0.29 (CVE-2024-XXXXX)
- **취약점**: 대용량 multipart 요청 시 DoS
- **영향**: 서비스 거부 가능
- **조치**: 0.0.29로 업그레이드 (2026-04)
- **검증**: 대용량 업로드 부하 테스트 정상

## 5. 라이선스 호환성 분석

| 라이선스 유형 | 패키지 수 | 상업적 사용 | 비고 |
|---------------|-----------|-------------|------|
| MIT | 38 | 허용 | - |
| BSD (2/3) | 15 | 허용 | - |
| Apache-2.0 | 7 | 허용 | - |
| GPLv3 | 1 (Orthanc) | 조건부 | 네트워크 분리 (Docker), 수정 없음 |
| 기타 | 3 | 허용 | HPND, PostgreSQL License |

**결론**: Orthanc(GPLv3)은 Docker 컨테이너로 분리 운용하며 소스 수정 없이 사용하므로, 전체 시스템의 라이선스 의무 충돌 없음.

## 6. SBOM 유지보수 절차

1. **월간 스캔**: pip-audit, npm audit 실행
2. **신규 취약점 발견 시**: SOP-007 변경관리 + SOP-008 CAPA 절차 적용
3. **릴리스 시**: SBOM 갱신 및 버전 태그
4. **연간 검토**: 전체 SBOM 정확성 재확인

## 7. 참조 문서

- CS-001 사이버보안 계획서
- SOP-007 변경관리 절차서
- SOP-008 CAPA 절차서
