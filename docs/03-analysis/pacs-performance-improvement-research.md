# PACS 성능 개선 — 추가 프레임워크·기능 조사

**작성일**: 2026-06-06
**대상**: WeRU.B PACS (Orthanc + FastAPI + Cornerstone3D/OHIF + PostgreSQL + Nginx)
**방법**: 현 운영 설정 실측 + 최신 기법 리서치(2025–2026)

---

## 0. 핵심 요약

API 성능은 양호(p95 180ms@100동시, 부하테스트 검증). 실제 PACS 체감 성능의 병목은 **영상 전달·렌더(대용량 CT/MR 로딩)** 이다. 조사 결과 **즉시 적용 가능한 저비용 개선 3건 + 영상 전달 고임팩트 개선(HTJ2K 프로그레시브)** 이 핵심이다.

> **현황 실측에서 드러난 누락**: Nginx `gzip_types` 주석처리(JSON/JS 미압축), **HTTP/2 미적용**, Orthanc가 웹 최적화 포맷(HTJ2K)이 아닌 Explicit VR LE로 전사.

---

## 1. Tier 1 — 즉시 적용 (저비용·고효율)

### 1.1 Nginx 압축·HTTP/2 ⭐
- **현황**: `gzip on`이나 `gzip_types`가 **주석** → DICOMweb 메타데이터(QIDO/WADO JSON)·뷰어 번들(JS) 비압축. `listen 443 ssl`(HTTP/2 없음).
- **개선**:
  - `gzip_types application/json application/dicom+json application/javascript text/css application/xml ...` 활성 (+`gzip_comp_level 5`)
  - **HTTP/2 활성**: `listen 443 ssl http2;` → 뷰어의 다수 프레임 요청 멀티플렉싱
  - (선택) **brotli** 모듈 — 정적 자산 추가 압축
- **효과**: 메타데이터/번들 전송량 60–80%↓, 다중 요청 지연↓. **난이도: 하** (nginx 설정, HospitalRun 영향 없음, /tmp→sudo cp 절차)

### 1.2 뷰어 디코드 병렬성
- **현황**: `maxNumberOfWebWorkers: 3`, `prefetch: 25`.
- **개선**: 워커를 클라이언트 코어 기반으로(`Math.min(navigator.hardwareConcurrency-1, 7)`), prefetch 윈도우 튜닝.
- **효과**: 다중 슬라이스 디코드 병렬↑. **난이도: 하** (config + 재빌드)

### 1.3 측정 베이스라인 (선행 권장)
- **현황**: Grafana/Prometheus/exporters **이미 운영 중**.
- **개선**: 영상 로드시간·WADO-RS 지연·디코드 시간 대시보드화 → 개선 전후 정량 비교.
- **효과**: 추측 아닌 데이터 기반 우선순위. **난이도: 하**

---

## 2. Tier 2 — 영상 전달 고임팩트 (핵심)

### 2.1 HTJ2K 프로그레시브 로딩 ⭐⭐⭐
현대 PACS 웹 성능의 핵심 기법. **첫 렌더 45ms**(vs JLS 359ms, 4G 기준) — 비트스트림 수신과 함께 화질이 점진 개선.
- **경로 A — 비-HTJ2K 프로그레시브 (재인코딩 불필요, 권장 1차)**: Cornerstone3D `retrieveOptions`로 **축소해상도/썸네일 먼저 → 전체** 단계 로드. 기존 J2K/JLS 데이터로 동작. 설정 수준.
- **경로 B — 풀 HTJ2K (최대 효과, 중간 노력)**: 영상을 HTJ2K(progressive resolution order)로 인코딩 + 뷰어 스트리밍 리더. Orthanc의 HTJ2K 전사는 네이티브 제약(Kakadu SDK/플러그인 필요) → **전사 파이프라인** 또는 수집 시 변환 필요.
- **효과**: 대용량 CT/MR 첫 화면 체감 대폭↑. **난이도: 중**(A) ~ 중상(B). OHIF/Cornerstone3D 공식 지원(ImNO 2024 발표).

### 2.2 서버측 프레임 캐싱 / CDN
- 디코드/전사된 프레임을 Redis 또는 CDN에 캐시 → 재판독·prior 비교 시 Orthanc 부하·지연↓.
- **효과**: 반복 조회 가속. **난이도: 중**

### 2.3 Orthanc WADO-RS 튜닝
- `HttpThreadsCount`(현 8) 상향, keep-alive, byte-range 지원 확인. 대량 동시 뷰어 세션 대비.
- **난이도: 하~중**

---

## 3. Tier 3 — 서버·스토리지·DB 스케일링

### 3.1 PostgreSQL 메모리 튜닝
- **현황**: `shared_buffers 128MB`(기본값, 15Gi 서버에 과소). `work_mem 4MB`.
- **개선**: `shared_buffers ~2–4GB`, `effective_cache_size`(현 4GB) 점검. **공유 DB라 HospitalRun 영향 고려, 재시작 필요.**
- **효과**: Orthanc 인덱스 쿼리(상시 ~56연결)·검색 가속. **난이도: 중** (공유 인프라 변경)

### 3.2 Orthanc Advanced Storage Plugin
- 다중 디스크, indexer 모드(파일 복사 없이 인덱싱 — 스토리지 풋프린트↓). 대용량 아카이브 스케일링.
- **난이도: 중**

### 3.3 Prior/Next 프리페치
- 워크리스트 다음 스터디·prior 비교본 백그라운드 선로드 → 판독 전환 체감↑.
- **난이도: 중**

---

## 4. 권장 로드맵

| 순위 | 항목 | 효과 | 난이도 | 비고 |
|:---:|---|:---:|:---:|---|
| 1 | **Nginx gzip_types + HTTP/2** ✅ **완료(2026-06-06)** | ★★★ | 하 | HTTP/2 활성 + gzip(JS/CSS/JSON/dicom+json). app-config.js 22.8KB→7.8KB(66%↓). 양 시스템 정상. 백업 `/tmp/hospital-run.bak.20260606`, `/etc/nginx/nginx.conf.bak.20260606` |
| 2 | **측정 베이스라인** ✅ **완료(2026-06-06)** | ★★ | 하 | FastAPI 메트릭 활성(아래 §6), 전 타깃 UP, 베이스라인 스냅샷 확보 |
| 3 | 뷰어 워커/prefetch 튜닝 ✅ **완료(2026-06-06)** | ★★ | 하 | maxNumberOfWebWorkers 3→동적(코어-1, ≤7), prefetch 25→50. app-config.js 검증 (commit 397e53d) |
| 4 | **영상 전달 무손실 압축** ✅ **완료·검증(2026-06-06)** | ★★★ | 중 | J2K 무손실 요청 → 524→176KB(3×↓). **브라우저 렌더 정상 확정**. 풀 HTJ2K는 Orthanc 인코딩 부재로 blocked |
| 5 | PostgreSQL 메모리 ✅ **완료(2026-06-06)** | ★★ | 중 | effective_cache_size 4→8GB(즉시), shared_buffers 128MB→2GB(staged). **cache_hit 100%라 전용 재시작 불필요** → 다음 자연 재시작 시 적용 |
| 6 | 서버측 프레임 캐싱 | ★★ | 중 | 반복 조회 |
| 7 | HTJ2K 풀(경로 B)·Advanced Storage | ★★★ | 중상 | 본격 스케일·전사 파이프라인 |

> **즉시 가치**: **#1(Nginx gzip+HTTP/2)** — 설정 한 번으로 메타데이터·번들·다중요청 전반이 빨라지고 HospitalRun 영향 없음. 그다음 **#2 측정 → #4 HTJ2K 프로그레시브**로 영상 체감 성능을 끌어올린다.

---

## 5. 적용 시 주의
- **측정 우선**: 모니터링 스택이 이미 있으니 개선 전후 정량 비교(추측 금지).
- **공유 인프라**: PostgreSQL·Nginx는 HospitalRun과 공유 → gzip/http2는 무영향이나 shared_buffers·재시작은 신중.
- **뷰어 변경은 재빌드 필수**(번들 캐시).
- **HTJ2K 재인코딩은 무손실 검증** — 의료영상 화질·측정 정확도 보존 필수(사용자 강조 원칙).

---

## 6. 측정 베이스라인 (2026-06-06, #1 적용 후)

**관측성 상태**: Prometheus 타깃 6종 전부 UP. Orthanc 네이티브 메트릭 + node/postgres/redis exporter + **FastAPI 메트릭(신규 활성)**. Grafana 운영 중 → `http_requests_total`·`http_request_duration_seconds`로 엔드포인트별 지연/처리량 대시보드화 가능.

> FastAPI 메트릭은 `prometheus-fastapi-instrumentator` 누락으로 미수집이었음(타깃 DOWN). 의존성 추가·재빌드로 활성화(commit d45893c). nginx 프록시 대상은 `127.0.0.1:8000`(CLAUDE.md "8001"은 outdated).

**API 지연 (gzip+HTTP/2 적용 후, 저부하)**:
| 엔드포인트 | TTFB | total |
|---|---|---|
| `/pacs-api/health` | 180ms | 180ms |
| `/pacs-api/api/v1/statistics` (401) | 154ms | 154ms |
| `/dicom-web/studies` (QIDO) | 203ms | 208ms |

**리소스 (저부하 시)**: load 0.28, RAM 5.0/15Gi 사용(여유 10Gi). 컨테이너 — backend 463MB/1.6%CPU, orthanc 288MB/0.3%, werub 7MB.
**Orthanc**: instances 188, patients 24, series 36, http threads 49 available.

> 향후 개선(#3~)은 본 스냅샷 대비 정량 비교. 남은 옵션: FastAPI/Orthanc용 Grafana 대시보드 JSON 프로비저닝(데이터는 이미 수집 중).

**#5 메모(2026-06-06)**: `pg_stat_database` cache_hit_ratio = **100%** (DB 소규모, 128MB로 핫데이터 전부 캐시). 따라서 shared_buffers 증설의 현재 이득 없음 → 전용 재시작(HospitalRun 영향) 미실시. `effective_cache_size`만 즉시 8GB(플래너 힌트, 무재시작), `shared_buffers=2GB`는 staged(다음 재시작 시). DB 성장으로 cache_hit가 ~99% 미만 되면 재시작으로 활성화 권장.

---

## 7. #4 영상 전달 — 실증 결과 (2026-06-06)

**HTJ2K 풀 프로그레시브(경로 B)는 BLOCKED**: Orthanc는 HTJ2K 네이티브 인코딩 미지원(Kakadu SDK/플러그인 필요) → SEG처럼 인프라 선결 필요.

**그러나 더 큰 즉효 레버를 실증**: 현재 저장이 **무압축(Explicit VR LE)** 이라 프레임이 비대(524KB/슬라이스). Orthanc가 WADO-RS 전송 시 **무손실 압축 전사 가능** 확인:

| 프레임(CT 1슬라이스) | 크기 | 비율 |
|---|---|---|
| 무압축 (현 default) | 524,842 B | 1.0× |
| JPEG 2000 무손실 | 176,396 B | 3.0×↓ |
| **JPEG-LS 무손실** | **168,090 B** | **3.1×↓** |

→ 133슬라이스 CT: **~70MB → ~22MB**. **무손실**이라 측정 정확도 무영향.

### 구현 경로 (택1)
- **A. 뷰어가 압축 TS 요청** — Cornerstone dicom-image-loader가 JPEG-LS/J2K Accept → Orthanc 전사. **기존 영상 전부 적용**, 저장 변경 없음. 비용: 요청당 Orthanc 전사 CPU(현 0.3%라 여유). 검증: 브라우저 디코드 확인 필요.
- **B. IngestTranscoding을 JPEG-LS 무손실로** — 신규 수집부터 **저장+전송 모두 압축**(스토리지도 3×↓). 기존 영상은 일괄 재전사 필요. Orthanc 코어 설정·재시작.

> 권장: **A**(전 영상 즉시 적용, 저장 무변경) 우선 — 단 뷰어 로더 설정+브라우저 검증 필요. 본격 신규수집 효율은 B 병행.

## 참고 (Sources)
- [Progressive Loading for non-HTJ2K — Cornerstone.js](https://www.cornerstonejs.org/docs/concepts/progressive-loading/non-htj2k-progressive/)
- [HTJ2K Compression WG-04 (DICOM Sup 235)](https://www.dicomstandard.org/news-dir/progress/docs/sups/sup235-slides.pdf)
- [OHIF v3.9 Release Notes](https://ohif.org/release-notes/3p9/)
- [Orthanc — Transcoding of DICOM files](https://orthanc.uclouvain.be/book/faq/transcoding.html)
- [Orthanc — Advanced Storage Plugin](https://orthanc.uclouvain.be/book/plugins/advanced-storage.html)
- [Progressive HTJ2K DICOM Serving (OHIF Community)](https://community.ohif.org/t/open-source-solutions-for-progressive-htj2k-dicom-serving-on-azure/2024)
