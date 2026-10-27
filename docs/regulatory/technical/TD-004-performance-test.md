# TD-004 성능시험 보고서 (Performance Test Report)

| 항목 | 내용 |
|------|------|
| 문서 ID | TD-004 |
| 버전 | 2.0 |
| 작성일 | 2026-05-18 |
| 상태 | 승인 |
| 적용 표준 | IEC 62304:2006+A1:2015 §5.6, 식약처 성능시험 가이드라인 |
| 제품명 | WeRU.B PACS |
| 시험 환경 | Linode VPS 8core / 16GB RAM / Ubuntu 22.04 |
| 검토일 | 2026-05-27 |
| 승인일 | 2026-05-27 |

## 1. 목적

WeRU.B PACS의 성능 요구사항(TD-001 NFR-001~002) 충족 여부를 객관적으로 검증하기 위한 부하 테스트, DICOM 적합성 시험, 모달리티별 렌더링 시험, 동시 사용자 시험, 24시간 안정성 시험의 결과를 기록한다.

## 2. 시험 환경

### 2.1 서버 사양

| 항목 | 사양 |
|------|------|
| CPU | AMD EPYC 8-core (Linode Dedicated 16GB) |
| RAM | 16 GB |
| Storage | 320 GB NVMe SSD |
| OS | Ubuntu 22.04 LTS |
| Docker | Engine 24.x + Compose v2 |
| 네트워크 | 1 Gbps (Linode Tokyo 2 DC) |

### 2.2 소프트웨어 구성

| 컴포넌트 | 버전 | Docker Container |
|----------|------|------------------|
| Orthanc | 1.12.11 | orthanc |
| PostgreSQL | 16-alpine | postgres |
| Redis | 7-alpine | redis |
| FastAPI Backend | v9.5 | backend |
| OHIF Viewer | v3.12 (WeRU.B Viewer) | ohif |
| Celery Worker | v9.5 | celery-worker |
| Nginx | 1.24 | Host |

### 2.3 테스트 도구

| 도구 | 버전 | 용도 |
|------|------|------|
| Locust | 2.x | HTTP 부하 테스트 |
| pytest + httpx | 8.x + 0.27.x | API 기능 테스트 |
| dcm4che tools | 5.31 | DICOM DIMSE 적합성 테스트 |
| Chrome DevTools | 125 | 프론트엔드 렌더링 측정 |

### 2.4 테스트 데이터

| 모달리티 | Study 수 | Series 수 | Instance 수 | 평균 크기 |
|----------|----------|-----------|-------------|-----------|
| CT | 30 | 90 | 9,000 | 512 KB |
| MR | 25 | 100 | 5,000 | 256 KB |
| CR/DX | 20 | 20 | 40 | 10 MB |
| US | 15 | 30 | 150 | 1 MB |
| MG | 10 | 20 | 40 | 50 MB |
| **합계** | **100** | **260** | **14,230** | - |

## 3. 부하 테스트 (Load Test)

### 3.1 테스트 시나리오

| 시나리오 ID | 시나리오 | 동시 사용자 | 지속 시간 | Ramp-up |
|-------------|----------|-------------|-----------|---------|
| LT-001 | Study 목록 조회 | 50 | 10분 | 30초 |
| LT-002 | Study 상세 조회 | 50 | 10분 | 30초 |
| LT-003 | DICOM 검증 (VAL-001) | 30 | 10분 | 30초 |
| LT-004 | AI 추론 요청 | 10 | 10분 | 30초 |
| LT-005 | 판독 리포트 생성 | 30 | 10분 | 30초 |
| LT-006 | 워크리스트 조회 | 50 | 10분 | 30초 |
| LT-007 | DICOMweb QIDO-RS | 50 | 10분 | 30초 |
| LT-008 | 혼합 시나리오 (실제 워크플로우) | 50 | 30분 | 60초 |

### 3.2 결과

| 시나리오 | 요청 수 | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | 에러율 | TPS |
|----------|---------|----------|----------|----------|----------|--------|-----|
| LT-001 Study 목록 | 15,000 | 45 | 142 | 210 | 380 | 0.00% | 25.0 |
| LT-002 Study 상세 | 14,500 | 38 | 125 | 195 | 320 | 0.00% | 24.2 |
| LT-003 DICOM 검증 | 8,400 | 85 | 180 | 250 | 420 | 0.00% | 14.0 |
| LT-004 AI 추론 | 1,800 | 120 | 350 | 500 | 850 | 0.00% | 3.0 |
| LT-005 리포트 생성 | 7,200 | 52 | 165 | 230 | 350 | 0.00% | 12.0 |
| LT-006 워크리스트 | 14,200 | 40 | 135 | 200 | 310 | 0.00% | 23.7 |
| LT-007 QIDO-RS | 12,800 | 55 | 168 | 240 | 400 | 0.00% | 21.3 |
| LT-008 혼합 | 42,000 | 58 | 175 | 265 | 520 | 0.00% | 23.3 |

**판정**: 전 시나리오 p95 < 200ms 목표 달성 (AI 추론 제외, 비동기 처리). 에러율 0%. **PASS**

### 3.3 리소스 사용량 (LT-008 혼합 시나리오)

| 리소스 | 평균 | 최대 | 기준 |
|--------|------|------|------|
| CPU 사용률 | 35% | 68% | < 80% |
| 메모리 사용량 | 8.2 GB | 11.5 GB | < 14 GB |
| 디스크 I/O | 120 MB/s | 280 MB/s | < 500 MB/s |
| DB 커넥션 | 25 | 42 | < 100 |
| Redis 메모리 | 128 MB | 256 MB | < 1 GB |

## 4. DICOM 적합성 시험

### 4.1 DIMSE 프로토콜 시험

| 시험 항목 | SOP Class | 결과 | 비고 |
|-----------|-----------|------|------|
| C-STORE | CT, MR, CR, US, MG | PASS | 5개 모달리티 정상 저장 |
| C-FIND (Patient Level) | PatientRootQueryRetrieveInformationModel | PASS | 이름/ID/생년월일 검색 |
| C-FIND (Study Level) | StudyRootQueryRetrieveInformationModel | PASS | StudyDate/Modality/AccessionNumber |
| C-MOVE | StudyRootQueryRetrieveInformationModel | PASS | 외부 AE로 전송 확인 |
| C-ECHO | VerificationSOPClass | PASS | 연결 검증 |

### 4.2 DICOMweb 적합성

| 서비스 | 엔드포인트 | 결과 | 비고 |
|--------|-----------|------|------|
| QIDO-RS (Study) | GET /dicom-web/studies | PASS | 필터링, 페이지네이션 |
| QIDO-RS (Series) | GET /dicom-web/studies/{uid}/series | PASS | 전체 시리즈 반환 |
| WADO-RS (Instance) | GET /dicom-web/studies/{uid}/series/{uid}/instances/{uid} | PASS | multipart/related |
| WADO-RS (Metadata) | GET /dicom-web/studies/{uid}/metadata | PASS | JSON 메타데이터 |
| STOW-RS | POST /dicom-web/studies | PASS | multipart/related 업로드 |
| WADO-URI (레거시) | GET /wado?requestType=WADO | PASS | 단일 인스턴스 조회 |

## 5. 모달리티별 렌더링 시험

### 5.1 WeRU.B Viewer 렌더링 성능

| 모달리티 | 데이터 | 초기 로딩 | 슬라이스 전환 | W/L 조절 | 판정 |
|----------|--------|-----------|---------------|----------|------|
| CT (Abdomen) | 300 slices, 512x512 | 2.1s | 16ms | 즉시 | PASS |
| CT (Chest HRCT) | 600 slices, 512x512 | 3.5s | 18ms | 즉시 | PASS |
| MR (Brain) | 180 slices, 256x256 | 1.2s | 12ms | 즉시 | PASS |
| MR (Spine) | 120 slices, 320x320 | 1.0s | 14ms | 즉시 | PASS |
| CR (Chest PA) | 1 image, 2048x2500 | 1.8s | N/A | 즉시 | PASS |
| US (Cardiac) | 60 frames, 640x480 | 0.8s | N/A | 즉시 | PASS |
| MG (MLO/CC) | 4 images, 3328x4096 | 4.2s | N/A | 즉시 | PASS |

### 5.2 측정 도구 정확도

| 측정 유형 | 테스트 | 기대값 | 측정값 | 오차 | 판정 |
|-----------|--------|--------|--------|------|------|
| 길이 측정 | CT Phantom 10cm rod | 100.0 mm | 100.1 mm | 0.1% | PASS |
| 면적 측정 | CT Phantom 5cm circle | 19.63 cm² | 19.58 cm² | 0.3% | PASS |
| 각도 측정 | CT Phantom 90° angle | 90.0° | 90.2° | 0.2% | PASS |
| HU 값 | CT Water phantom | 0 HU | -2 HU | 2 HU | PASS |

## 6. 동시 사용자 시험

### 6.1 시나리오

50명의 가상 사용자가 실제 판독 워크플로우를 동시 수행:
1. 로그인 → 2. 워크리스트 조회 → 3. Study 선택 → 4. 뷰어 오픈 → 5. 영상 조회 → 6. 리포트 작성 → 7. 리포트 저장

### 6.2 결과

| 동시 사용자 | 평균 응답(ms) | p95(ms) | 에러율 | 판정 |
|-------------|---------------|---------|--------|------|
| 10 | 28 | 65 | 0% | PASS |
| 20 | 35 | 95 | 0% | PASS |
| 30 | 42 | 125 | 0% | PASS |
| 50 | 58 | 175 | 0% | PASS |
| 75 | 85 | 240 | 0.1% | PASS (주의) |
| 100 | 135 | 380 | 0.5% | FAIL |

**판정**: 50명 동시 사용자 기준 p95=175ms (목표 < 200ms). **PASS**
- 권장 최대 동시 사용자: 75명 (8core/16GB 환경)
- 100명 지원 시 16core/32GB 업그레이드 권장

## 7. 24시간 안정성 시험 (Soak Test)

### 7.1 시험 조건
- 동시 사용자: 20명 (평균 운영 부하)
- 지속 시간: 24시간 연속
- 시나리오: 혼합 워크플로우 (조회 60%, 판독 25%, QC 10%, AI 5%)

### 7.2 결과

| 측정 항목 | 시작 (0h) | 8h | 16h | 24h | 판정 |
|-----------|-----------|-----|------|------|------|
| p95 응답시간(ms) | 92 | 95 | 98 | 101 | PASS (< 200ms) |
| 에러율 | 0% | 0% | 0% | 0% | PASS |
| 메모리 사용량 | 6.8 GB | 7.1 GB | 7.3 GB | 7.5 GB | PASS (누수 없음) |
| CPU 사용률 평균 | 18% | 19% | 18% | 19% | PASS |
| DB 커넥션 | 15 | 16 | 15 | 16 | PASS |
| Docker 재시작 | 0 | 0 | 0 | 0 | PASS |

**판정**: 24시간 연속 운영 시 성능 저하 없음, 메모리 누수 없음. **PASS**

## 8. 종합 판정

| 시험 항목 | 기준 | 결과 | 판정 |
|-----------|------|------|------|
| API 부하 테스트 | p95 < 200ms | p95 = 142ms (Study 목록 기준) | **PASS** |
| 동시 사용자 | 50명 이상 | 50명 p95=175ms, 에러 0% | **PASS** |
| DICOM DIMSE 적합성 | 5개 SOP Class | 5/5 통과 | **PASS** |
| DICOMweb 적합성 | QIDO/WADO/STOW | 6/6 통과 | **PASS** |
| 모달리티 렌더링 | CT/MR/CR/US/MG | 7/7 통과 | **PASS** |
| 측정 도구 정확도 | 오차 < 1% | 최대 0.3% | **PASS** |
| 24시간 안정성 | 성능 저하 없음 | 응답 +9ms, 메모리 +0.7GB | **PASS** |
| **최종 판정** | | | **적합** |

## 9. 참조 문서

- TD-001 요구사항 명세서 (NFR-001, NFR-002)
- TD-005 V&V 보고서
- IEC 62304:2006+A1:2015 §5.6 소프트웨어 검증
- DICOM Part 18 (DICOMweb)
- DICOM Part 7 (DIMSE)
