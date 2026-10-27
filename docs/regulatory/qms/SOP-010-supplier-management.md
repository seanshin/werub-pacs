# SOP-010 공급업체관리 절차서 (Supplier Management — SOUP Control)

| 항목 | 내용 |
|------|------|
| 문서 ID | SOP-010 |
| 버전 | 2.0 |
| 작성일 | 2026-05-18 |
| 상태 | 승인 |
| 적용 표준 | ISO 13485:2016 §7.4, IEC 62304:2006+A1:2015 §5.3.3, §8.1.2 |
| 제품명 | WeRU.B PACS |

## 1. 목적

WeRU.B PACS에 사용되는 SOUP(Software of Unknown Provenance) 구성요소 및 외부 공급업체를 평가, 선정, 모니터링하기 위한 절차를 규정한다.

## 2. 적용 범위

- 제품에 포함되는 모든 SOUP 컴포넌트 (오픈소스, 상용 라이브러리)
- 클라우드 인프라 공급업체 (Linode/Akamai)
- 도메인/인증서 공급업체 (Let's Encrypt)
- 외주 서비스 (침투 테스트, 보안 감사 등)

## 3. 용어 정의

| 용어 | 정의 |
|------|------|
| SOUP | Software of Unknown Provenance — 자체 개발하지 않은 소프트웨어 구성요소 |
| SBOM | Software Bill of Materials — 소프트웨어 구성요소 목록 (CS-002) |
| 핵심 SOUP | 제품 기능에 직접 영향을 미치는 SOUP (Class B 이상) |
| 보조 SOUP | 개발/테스트에만 사용되는 도구 |

## 4. SOUP 분류 및 위험 등급

### 4.1 핵심 SOUP 목록 (제품 기능 직접 영향)

| SOUP | 버전 | 용도 | 라이선스 | 위험 등급 | 대체 가능성 |
|------|------|------|----------|-----------|-------------|
| Orthanc | 1.12.11 | DICOM 서버 (DIMSE + DICOMweb) | GPLv3 | High | DCM4CHEE (복잡) |
| OHIF Viewer | v3.12 | DICOM 웹 뷰어 (Cornerstone3D) | MIT | High | 없음 (커스텀 필요) |
| FastAPI | 0.111.x | Backend REST API 프레임워크 | MIT | High | Django/Flask |
| PostgreSQL | 16 | 메타데이터/사용자/감사 DB | PostgreSQL License | High | MySQL (기능 부족) |
| Redis | 7 | 캐시, 세션, Celery 브로커 | BSD-3 | Medium | Memcached (기능 부족) |
| Celery | 5.4.x | AI 추론 비동기 작업 큐 | BSD-3 | Medium | RQ, Dramatiq |
| pydicom | 3.0.2 | DICOM 파일 파싱/조작 | MIT | High | GDCM Python |
| SQLAlchemy | 2.0.x | ORM, DB 마이그레이션 | MIT | Medium | Tortoise ORM |
| httpx | 0.27.x | Orthanc 비동기 HTTP 통신 | BSD-3 | Medium | aiohttp |
| python-jose | 3.5.0 | JWT 토큰 생성/검증 | MIT | High | PyJWT |
| bcrypt | 4.1.x | 비밀번호 해싱 | Apache-2.0 | High | argon2 |
| Pillow | 10.x | 이미지 처리 (JPEG 밀도 검증) | HPND | Medium | OpenCV |
| Nginx | 1.24 | Reverse proxy, TLS termination | BSD-2 | High | Caddy, Traefik |

### 4.2 보조 SOUP (개발/테스트)

| SOUP | 용도 | 비고 |
|------|------|------|
| pytest | 단위/통합 테스트 | 제품에 미포함 |
| Locust | 부하 테스트 | 제품에 미포함 |
| Docker Engine | 컨테이너 런타임 | 배포 환경 |
| Docker Compose | 서비스 오케스트레이션 | 배포 환경 |

## 5. SOUP 평가 기준

### 5.1 초기 평가 항목

| 평가 항목 | 기준 | 배점 |
|-----------|------|------|
| 기능 적합성 | 요구사항 충족도 | 30 |
| 성숙도 | GitHub stars, 릴리스 빈도, 커뮤니티 규모 | 20 |
| 보안 이력 | CVE 건수, 패치 대응 시간 | 20 |
| 라이선스 호환 | 의료기기 배포 허용 여부 | 15 |
| 기술 지원 | 문서 품질, 이슈 대응 속도 | 15 |

### 5.2 합격 기준
- 총점 70점 이상: 채택 가능
- 총점 50~69점: 조건부 채택 (보완 조치 필요)
- 총점 49점 이하: 채택 불가

### 5.3 평가 결과 (2026-05 현재)

| SOUP | 기능 | 성숙도 | 보안 | 라이선스 | 지원 | 합계 | 판정 |
|------|------|--------|------|----------|------|------|------|
| Orthanc | 30 | 18 | 17 | 12 | 13 | 90 | 채택 |
| OHIF Viewer | 28 | 19 | 18 | 15 | 14 | 94 | 채택 |
| FastAPI | 30 | 20 | 19 | 15 | 15 | 99 | 채택 |
| PostgreSQL | 30 | 20 | 20 | 15 | 15 | 100 | 채택 |
| pydicom | 28 | 17 | 16 | 15 | 12 | 88 | 채택 |
| python-jose | 25 | 14 | 13 | 15 | 10 | 77 | 채택 |
| Redis | 28 | 20 | 19 | 15 | 14 | 96 | 채택 |

## 6. SOUP 모니터링 절차

### 6.1 정기 모니터링 (월 1회)

1. SBOM(CS-002)에 등록된 전 SOUP의 최신 버전을 확인한다.
2. 보안 취약점 스캔을 수행한다:
   - `pip audit` (Python 패키지)
   - Dependabot alerts (GitHub)
   - Snyk 스캔
3. 새로운 CVE가 발견된 경우:
   - Critical/High: 48시간 내 패치 검토 (SOP-007 변경관리)
   - Medium: 30일 내 패치 검토
   - Low: 차기 릴리스에 포함

### 6.2 주요 업데이트 대응

SOUP 메이저 버전 업데이트(예: OHIF 3.x → 4.x) 시:
1. 변경 영향 분석 수행 (SOP-007)
2. 호환성 테스트 (기존 Extension, API 인터페이스)
3. 위험 분석 업데이트 (RM-002)
4. V&V 재수행 (TD-005)

### 6.3 SOUP 폐기/대체

SOUP을 제거하거나 대체할 경우:
1. 대체 SOUP 초기 평가 수행 (§5.1)
2. 마이그레이션 계획 수립
3. 회귀 테스트 전량 수행
4. SBOM 업데이트

## 7. 인프라 공급업체 관리

| 공급업체 | 서비스 | 평가 항목 | 계약 현황 |
|----------|--------|-----------|-----------|
| Linode (Akamai) | VPS (8core/16GB) | SLA 99.9%, 데이터센터 위치, 보안 인증 | 월 과금 |
| Let's Encrypt | TLS 인증서 | 자동 갱신 안정성, 무료 | 무료 서비스 |
| GitHub | 소스코드/문서 저장소 | SLA, 보안, 접근 통제 | Pro 플랜 |

인프라 공급업체는 연 1회 서비스 수준을 평가하고, 장애 발생 시 대체 방안을 검토한다.

## 8. 기록 관리

| 기록 | 보관 기간 | 위치 |
|------|-----------|------|
| SOUP 초기 평가서 | 제품 수명 + 2년 | `docs/regulatory/records/supplier/` |
| 월간 모니터링 결과 | 3년 | `docs/regulatory/records/supplier/` |
| 취약점 패치 이력 | 제품 수명 + 2년 | Git commit history |
| SBOM | 각 릴리스마다 | CS-002 |

## 9. 참조 문서

- ISO 13485:2016 §7.4 구매
- IEC 62304:2006+A1:2015 §5.3.3 SOUP 식별, §8.1.2 SOUP 모니터링
- CS-002 SBOM
- SOP-007 변경관리 절차서
- RM-002 위험 분석서
