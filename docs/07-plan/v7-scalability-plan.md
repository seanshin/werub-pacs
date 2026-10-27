# OpenPACS v7.0 — 대규모 운영 확장성 기획서

> **작성일**: 2026-05-12
> **기반**: v5.1 (83 API, 10 컨테이너, 단일 서버)
> **목표**: 일일 500건 이상 검사, 동시 50명 판독의 환경에서 안정적 운영

---

## 1. 현재 병목 분석

### 1.1 판독 대기 목록 (가장 심각)

```
현재 흐름:
GET /dashboard/reading-queue
  → Orthanc GET /studies (ID 목록)           1회
  → Orthanc GET /studies/{id} × N건         N회 (순차)
  → DB SELECT reports (전체)                 1회
  → Python에서 매칭/정렬                     O(N²)

100건 = ~102 HTTP 요청, ~3초
500건 = ~502 HTTP 요청, ~15초
1000건 = ~1002 HTTP 요청, ~30초+ (타임아웃 위험)
```

**문제점**:
- N+1 HTTP 요청 (순차)
- 전체 Report 테이블 로드
- 페이지네이션 없음
- 클라이언트 전체 렌더링

### 1.2 AI 추론 (병렬 처리 필요)

```
현재 흐름:
영상 수신 → StableStudy → AI 자동 트리거
  → Celery Worker 1개 (concurrency=2)
  → 순차 처리

MedGemma 544ms/건 × 100건 = 54초 (1워커)
CT 100슬라이스 Study → 단일 대표 슬라이스만 분석 중
```

**문제점**:
- 워커 1개, 동시 처리 2건
- GPU 서버 1대에 의존
- 대량 수신 시 큐 적체
- 멀티 슬라이스 CT 분석 미지원

### 1.3 DICOM 수신 (동시 다발)

```
현재: Orthanc 단일 인스턴스
  → DicomThreadsCount: 4
  → HttpThreadsCount: 8
  → PostgreSQL 단일 연결

피크 시나리오: CT 5대 동시 촬영 완료
  → 5 × 300슬라이스 = 1500 C-STORE 동시
  → Orthanc 부하 집중
```

### 1.4 데이터 증가

| 기간 | 일일 검사 | 누적 인스턴스 | 저장 용량 | 쿼리 성능 |
|------|:--------:|:-----------:|:--------:|:--------:|
| 현재 | 10 | 180 | 87MB | 즉시 |
| 6개월 | 100 | ~50,000 | ~25GB | 양호 |
| 1년 | 300 | ~200,000 | ~100GB | 주의 |
| 2년 | 500 | ~500,000 | ~250GB | 위험 |

---

## 2. 확장 전략

### 2.1 Phase 1: 쿼리 최적화 (즉시)

**판독 큐 N+1 해결**

```
개선 흐름:
GET /dashboard/reading-queue?page=1&size=20
  → Orthanc POST /tools/find (서버 사이드 검색)    1회
  → 결과에 메타데이터 포함 (Expand=true)           0회
  → DB SELECT reports WHERE study_uid IN (...)     1회
  → 서버에서 매칭/정렬/페이지네이션                  O(N)

500건 = 2~3 HTTP 요청, <1초
```

**구현**:
```python
# reading_queue API 개선
@router.get("/reading-queue")
async def reading_queue(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=10, le=100),
    sort: str = Query("date_desc"),  # date_desc, date_asc, urgency
    modality: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),  # 환자명/번호 검색 (초성 지원)
):
    # Orthanc /tools/find with pagination
    offset = (page - 1) * size
    ...
```

**프론트엔드 페이지네이션**:
```
┌─────────────────────────────────────────────────────┐
│ 판독 대기 목록                    총 487건 | 20건/페이지 │
│                                                     │
│ 🔍 [____________] 모달리티: [전체▼] 상태: [전체▼]     │
│                                                     │
│ ┌──────┬──────────┬────────┬────┬──────┬──────────┐ │
│ │ 상태 │ 환자명    │ 환자번호│모달│검사설명│ 검사일    │ │
│ │ ...  │ ...      │ ...   │ ...│ ...  │ ...      │ │
│ │ (20건 표시)                                      │ │
│ └──────┴──────────┴────────┴────┴──────┴──────────┘ │
│                                                     │
│         ◀ 이전  1 2 3 ... 25  다음 ▶                 │
└─────────────────────────────────────────────────────┘
```

### 2.2 Phase 2: Orthanc 인덱스 캐시 (1주)

**Redis 기반 Study 메타데이터 캐시**

```
영상 수신 (OnStoredInstance)
  → Redis HSET study:{uid} {patient_name, date, modality, ...}
  → TTL 1시간

판독 큐 조회
  → Redis에서 메타데이터 조회 (Orthanc HTTP 호출 제거)
  → Cache miss 시 Orthanc에서 가져와 캐시

효과: Orthanc HTTP 호출 95% 감소
```

**구현**:
```python
class StudyCache:
    """Redis-based study metadata cache."""

    async def get_studies(self, page, size, filters) -> list:
        # 1. Redis에서 필터링된 Study UID 목록
        # 2. 각 UID의 메타데이터 Redis에서 조회
        # 3. Cache miss만 Orthanc에서 보충
        ...

    async def on_study_received(self, study_uid, metadata):
        # OnStoredInstance 콜백에서 호출
        await redis.hset(f"study:{study_uid}", mapping=metadata)
        await redis.expire(f"study:{study_uid}", 3600)
        await redis.zadd("studies:by_date", {study_uid: timestamp})
```

### 2.3 Phase 3: AI 병렬 추론 (2주)

**Celery Worker 스케일아웃**

```yaml
# docker-compose.yml
celery-worker-1:
  command: celery -A ... worker -Q ai_inference -c 4 --hostname=w1@%h
celery-worker-2:
  command: celery -A ... worker -Q ai_inference -c 4 --hostname=w2@%h
celery-worker-3:
  command: celery -A ... worker -Q ai_priority -c 2 --hostname=w3@%h  # 긴급 전용
```

**GPU 서버 부하 분산**:
```python
# 모델별 라우팅
ROUTING = {
    "medgemma-4b": "ai_inference",      # 일반 큐
    "chest-xray-analyzer": "ai_fast",    # 빠른 큐 (ONNX/통계)
    "emergency-detect": "ai_priority",   # 긴급 큐
}
```

**멀티 슬라이스 CT 분석**:
```python
# CT Study → 대표 슬라이스 3장 선택 (상/중/하)
# 각 슬라이스 병렬 분석 → 결과 통합
async def analyze_ct_study(study_uid):
    slices = select_representative_slices(study_uid, count=3)
    tasks = [analyze_slice.delay(s) for s in slices]
    results = await gather_results(tasks)
    return merge_findings(results)
```

### 2.4 Phase 4: 데이터베이스 확장 (1개월)

**PostgreSQL 최적화**

```sql
-- 판독 큐 전용 인덱스
CREATE INDEX idx_reports_study_status ON reports(study_instance_uid, status);
CREATE INDEX idx_reports_created_date ON reports(created_at DESC);
CREATE INDEX idx_worklist_date_status ON worklist_items(scheduled_date, status);

-- 파티셔닝 (월별)
CREATE TABLE validation_results_2026_05 PARTITION OF validation_results
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
```

**Orthanc PostgreSQL 인덱스 튜닝**:
```
-- Orthanc 내부 인덱스 추가
-- PatientID + StudyDate 복합 인덱스
-- ModalitiesInStudy 인덱스
```

**읽기 전용 Replica**:
```
Primary (쓰기) ──→ Replica (읽기)
  ↑                    ↑
  Orthanc/API          판독 큐 조회
  리포트 작성           대시보드 통계
```

### 2.5 Phase 5: Orthanc 수평 확장 (2개월)

**멀티 Orthanc 인스턴스**

```
                    Load Balancer (Nginx)
                    ┌────────┐
                    │        │
              ┌─────┤        ├─────┐
              ▼     └────────┘     ▼
         Orthanc-1            Orthanc-2
         (C-STORE)            (C-STORE)
              │                    │
              └────────┬───────────┘
                       ▼
                PostgreSQL (공유 인덱스)
                       │
              ┌────────┴───────────┐
              ▼                    ▼
         Storage-1            Storage-2
         (로컬 SSD)           (S3/MinIO)
```

**라우팅 전략**:
- CT/MR → Orthanc-1 (고용량 SSD)
- CR/DX → Orthanc-2 (일반 스토리지)
- 또는 Round-Robin

### 2.6 Phase 6: 마이크로서비스 분리 (3개월+)

**현재 (모놀리식)**:
```
FastAPI Backend (83 API, 단일 프로세스)
```

**분리 후**:
```
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Gateway API    │ │ Reading Service│ │ AI Service     │
│ (인증, 라우팅)  │ │ (판독, 리포트) │ │ (추론, 모델)   │
│ 포트 8000      │ │ 포트 8001      │ │ 포트 8002      │
└────────────────┘ └────────────────┘ └────────────────┘
         │                  │                │
         └──────────────────┴────────────────┘
                           │
                      Redis (이벤트 버스)
                           │
              ┌────────────┴───────────┐
              ▼                        ▼
         PostgreSQL               Orthanc
```

---

## 3. 성능 목표

| 시나리오 | 현재 | Phase 1 | Phase 3 | Phase 5 |
|---------|:----:|:-------:|:-------:|:-------:|
| 판독 큐 (100건) | ~3초 | <0.5초 | <0.5초 | <0.3초 |
| 판독 큐 (1000건) | 타임아웃 | <1초 | <1초 | <0.5초 |
| AI 추론 (동시 10건) | 순차 54초 | 순차 54초 | 병렬 ~6초 | 병렬 ~3초 |
| DICOM 수신 (동시 5 CT) | 가능 | 가능 | 가능 | 부하 분산 |
| 동시 접속 판독의 | ~10명 | ~30명 | ~50명 | ~100명 |
| 저장 용량 | 87MB | 87MB | 87MB | TB급 (S3) |

---

## 4. 구현 우선순위

| Phase | 기간 | 내용 | 효과 |
|:-----:|:----:|------|:----:|
| **1** | **2일** | **판독 큐 페이지네이션 + Orthanc 서버 사이드 검색** | 🔴 즉시 |
| **2** | **3일** | **Redis 메타데이터 캐시 + WebSocket 실시간 갱신** | 🟡 높음 |
| 3 | 1주 | Celery 워커 스케일아웃 + AI 병렬 추론 | 🟡 높음 |
| 4 | 2주 | DB 인덱스 최적화 + 파티셔닝 + Replica | 🟢 보통 |
| 5 | 1개월 | Orthanc 멀티 인스턴스 + S3 스토리지 | 🟢 보통 |
| 6 | 3개월 | 마이크로서비스 분리 | 🔵 장기 |

---

## 5. 프론트엔드 확장 계획

### 5.1 가상 스크롤 (Virtual Scroll)

1000건 이상 목록에서 DOM 노드를 20~30개만 유지:
```typescript
// react-window 또는 @tanstack/react-virtual
import { useVirtualizer } from '@tanstack/react-virtual';
```

### 5.2 무한 스크롤 vs 페이지네이션

| 방식 | 장점 | 단점 | 선택 |
|------|------|------|:----:|
| 페이지네이션 | 명확한 위치, 북마크 가능 | 페이지 전환 | ✅ 판독 큐 |
| 무한 스크롤 | 자연스러운 탐색 | 위치 불명확 | 감사 로그 |

### 5.3 Optimistic UI

- 리포트 서명 → 즉시 UI 갱신 (API 응답 전)
- 워크리스트 생성 → 즉시 목록에 추가
- 실패 시 롤백 + 에러 토스트

### 5.4 WebSocket 실시간 갱신

```
서버 이벤트 → WebSocket → 클라이언트 자동 갱신

이벤트:
- new_study: 판독 큐에 새 행 추가 (fade-in 애니메이션)
- study_read: 판독 완료 → 상태 배지 변경
- ai_complete: AI 분석 완료 → AI 배지 추가
- critical_finding: 긴급 알림 팝업 + 소리
```

---

## 6. 인프라 확장 로드맵

### 현재 (v5.1)
```
단일 서버 (Ubuntu, 16GB RAM, 8 CPU)
  + GPU 서버 (RTX 5080, AI 추론)
```

### 중기 (v7.0)
```
App 서버 (32GB RAM)
  ├── FastAPI (Gunicorn 4 workers)
  ├── Celery Workers × 3
  ├── Admin Portal
  └── Nginx

DB 서버 (16GB RAM)
  ├── PostgreSQL Primary + Replica
  └── Redis (Sentinel)

DICOM 서버 (32GB RAM, SSD)
  ├── Orthanc × 2
  └── DICOM Storage (2TB SSD)

GPU 서버 (RTX 5080)
  └── Ollama + MedGemma
```

### 장기 (v8.0+)
```
Kubernetes Cluster
  ├── API Pods (auto-scale)
  ├── AI Worker Pods (GPU node)
  ├── Orthanc StatefulSet
  ├── PostgreSQL (CloudNative-PG)
  ├── Redis Cluster
  └── S3 (MinIO/AWS)
```

---

## 7. 모니터링 확장

### 알림 규칙 (Prometheus AlertManager)

| 규칙 | 조건 | 알림 |
|------|------|------|
| 판독 큐 적체 | 대기 > 50건 (30분 이상) | Slack + 이메일 |
| AI 큐 적체 | pending > 20건 | Slack |
| Orthanc 응답 지연 | P95 > 5초 | 이메일 |
| 디스크 부족 | 사용률 > 85% | 긴급 알림 |
| API 에러율 | 5xx > 1% (5분) | Slack |
| GPU 메모리 | VRAM > 90% | 모니터링 |

### Grafana 대시보드 추가

- **판독 TAT 대시보드**: 평균 판독 시간, 지연 건수
- **AI 성능 대시보드**: 모델별 추론 시간, 큐 대기 시간
- **DICOM 수신 대시보드**: 시간대별 수신량, 장비별 통계
