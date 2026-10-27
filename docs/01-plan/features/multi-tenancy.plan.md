# v2.0 다중 기관 멀티테넌시 기획서

**작성일**: 2026-05-18  
**우선순위**: P2 (사업 확장 핵심)  
**예상 기간**: 4~6주  
**전제 조건**: v1.1 완료 (✅)

---

## 1. 배경 & 목표

### 1.1 현재 (v1.x): 단일 기관

```
[병원 A] → [OpenPACS 서버 1대] → [Orthanc 1개] → [DB 1개]
```

- 1개 병원만 사용 가능
- 모든 데이터가 하나의 DB/Orthanc에 혼재
- 신규 병원 도입 시 서버를 별도로 구축해야 함

### 1.2 목표 (v2.0): 다중 기관

```
[병원 A] ─┐
[병원 B] ─┼─→ [OpenPACS 멀티테넌트] → [기관별 격리된 데이터]
[클리닉 C] ┘
```

- 하나의 서버에서 **복수 의료기관** 운영
- 기관 간 데이터 **완전 격리** (환자, 영상, 리포트)
- 기관별 독립 관리자, 사용자, 설정
- 중앙 관리 (슈퍼 관리자) + 기관별 관리

---

## 2. 멀티테넌시 모델 비교

| 모델 | 구조 | 격리 수준 | 비용 | 복잡도 |
|------|------|:---------:|:----:|:------:|
| **A. DB 분리** | 기관별 별도 DB | 최고 | 높음 | 높음 |
| **B. 스키마 분리** | 기관별 별도 Schema | 높음 | 중간 | 중간 |
| **C. Row-level (권장)** | tenant_id 컬럼 | 중간 | 낮음 | **낮음** |

### 권장: C. Row-Level Isolation

**이유**:
- 기존 코드 변경 최소 (테이블에 `tenant_id` 컬럼 추가)
- 하나의 DB 커넥션 풀 공유 → 리소스 효율
- 중소 병원 10~50개 규모에 적합
- Orthanc Label 기능으로 영상 격리 가능 (v1.12+)

---

## 3. 아키텍처 설계

### 3.1 테넌트 격리

```
┌─────────────────────────────────────────────┐
│  Nginx (도메인/경로 기반 테넌트 식별)        │
│  hospital-a.openpacs.kr → tenant_id = "A"   │
│  hospital-b.openpacs.kr → tenant_id = "B"   │
│  또는 /api/v1/... + X-Tenant-ID 헤더        │
└──────────────────┬──────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │ FastAPI Backend    │
         │ TenantMiddleware   │
         │ (모든 요청에       │
         │  tenant_id 주입)   │
         └─────────┬─────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───┴───┐   ┌─────┴─────┐  ┌────┴────┐
│ PostgreSQL│ │   Orthanc  │  │  Redis   │
│ tenant_id │ │   Labels   │  │ prefix   │
│ RLS 정책  │ │ 기관별 라벨│  │ tenant:  │
└───────────┘ └───────────┘  └─────────┘
```

### 3.2 테넌트 식별 방법

| 방법 | 장점 | 단점 |
|------|------|------|
| **서브도메인** (`a.openpacs.kr`) | 직관적, SSL 와일드카드 | DNS 관리 필요 |
| **경로** (`/tenant/a/api/...`) | DNS 불필요 | URL 길어짐 |
| **헤더** (`X-Tenant-ID: a`) | 기존 URL 유지 | 프론트엔드 관리 필요 |
| **JWT claim** (`tenant_id` in token) | 보안 강력 | 토큰 재발급 |

**권장**: JWT claim 기반 (로그인 시 tenant_id 포함) + 서브도메인 (UI 분리)

### 3.3 데이터 모델 변경

```sql
-- 모든 주요 테이블에 tenant_id 추가
ALTER TABLE users ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE reports ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE worklist_items ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE batch_jobs ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE audit_logs ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE ai_models ADD COLUMN tenant_id UUID;  -- NULL = 공유 모델
ALTER TABLE inference_jobs ADD COLUMN tenant_id UUID NOT NULL;

-- Row Level Security (RLS) 정책
CREATE POLICY tenant_isolation ON users
  USING (tenant_id = current_setting('app.current_tenant')::uuid);

-- 테넌트 관리 테이블 (신규)
CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(128) NOT NULL,           -- "서울대병원", "강남클리닉"
  slug VARCHAR(64) NOT NULL UNIQUE,     -- "snu", "gangnam"
  domain VARCHAR(256),                  -- "snu.openpacs.kr"
  is_active BOOLEAN DEFAULT true,
  settings JSONB DEFAULT '{}',          -- 기관별 설정
  storage_quota_gb INTEGER DEFAULT 100,
  max_users INTEGER DEFAULT 50,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 테넌트 사용자 매핑
CREATE TABLE tenant_users (
  tenant_id UUID REFERENCES tenants(id),
  user_id UUID REFERENCES users(id),
  role VARCHAR(32) NOT NULL,  -- tenant_admin, radiologist, etc.
  PRIMARY KEY (tenant_id, user_id)
);
```

### 3.4 Orthanc 영상 격리

Orthanc 1.12+의 **Label** 기능을 사용:

```python
# 영상 업로드 시 테넌트 라벨 부착
await orthanc.put(f"/studies/{study_id}/labels/{tenant_id}")

# 영상 조회 시 테넌트 라벨로 필터
await orthanc.post("/tools/find", json={
    "Level": "Study",
    "Labels": [tenant_id],
    "Query": {...}
})
```

---

## 4. 구현 단계

### Phase 1: 기반 (1주)

| 항목 | 내용 |
|------|------|
| `tenants` 테이블 | 기관 관리 DB 모델 |
| `tenant_users` 테이블 | 기관-사용자 매핑 |
| `TenantMiddleware` | 모든 요청에서 tenant_id 추출 |
| JWT 확장 | 토큰에 tenant_id claim 추가 |
| 슈퍼 관리자 | 기관 CRUD API |

### Phase 2: 데이터 격리 (2주)

| 항목 | 내용 |
|------|------|
| 기존 테이블 마이그레이션 | `tenant_id` 컬럼 추가 (Alembic) |
| PostgreSQL RLS | Row-Level Security 정책 적용 |
| Orthanc Label 연동 | 업로드/조회 시 라벨 자동 처리 |
| Redis 격리 | 캐시 키에 `tenant:{id}:` 프리픽스 |
| API 필터 적용 | 모든 쿼리에 tenant_id 조건 추가 |

### Phase 3: 관리 UI (1주)

| 항목 | 내용 |
|------|------|
| 슈퍼 관리자 대시보드 | 기관 목록, 사용량, 상태 |
| 기관 관리 페이지 | 기관 설정, 사용자 관리 |
| 기관 전환 UI | 슈퍼 관리자 기관 전환 |
| 기관별 로그인 | 서브도메인 또는 기관 선택 |

### Phase 4: 테스트 & 안정화 (1주)

| 항목 | 내용 |
|------|------|
| 격리 테스트 | 기관 A 데이터가 기관 B에서 안 보이는지 |
| 성능 테스트 | 10개 기관, 기관당 50 사용자 |
| 마이그레이션 | 기존 단일 기관 → 멀티테넌트 전환 스크립트 |
| 문서화 | 기관 온보딩 가이드 |

---

## 5. 영향 분석

### 변경되는 파일 (예상)

| 영역 | 파일 수 | 변경 내용 |
|------|:------:|----------|
| DB 모델 | ~10 | 모든 모델에 `tenant_id` 추가 |
| API 엔드포인트 | ~25 | 쿼리에 tenant_id 필터 추가 |
| 인증 (JWT) | 2 | 토큰에 tenant_id claim |
| 미들웨어 | 1 | TenantMiddleware 신규 |
| Admin UI | ~5 | 기관 관리 + 기관 전환 |
| Alembic | 2 | 테이블 추가 + 컬럼 추가 |
| **합계** | **~45** | |

### 변경되지 않는 것

- Orthanc 컨테이너 설정 (Label API 사용, 설정 변경 없음)
- WeRU.B Viewer (뷰어는 DICOMweb 데이터만 표시)
- DICOM 정규화 엔진 (데이터 독립적)
- AI 추론 파이프라인 (기관별 모델 공유 또는 분리)

---

## 6. 위험 요소

| 위험 | 확률 | 영향 | 완화 |
|------|:----:|:----:|------|
| 기존 데이터 마이그레이션 실패 | 중 | 높음 | 마이그레이션 전 백업, 단계적 전환 |
| RLS 정책 누락 → 데이터 유출 | 낮 | **최고** | 모든 테이블 RLS 적용 확인 체크리스트 |
| 성능 저하 (tenant_id JOIN) | 낮 | 중 | 인덱스 추가, 캐시 활용 |
| Orthanc Label 제한 | 낮 | 중 | Label당 스터디 수 제한 없음 (확인됨) |

---

## 7. 비용 추정

| 항목 | 단일 기관 (현재) | 멀티테넌트 (10기관) |
|------|:--------------:|:-----------------:|
| 서버 | 1대 (16GB) | 1대 (32GB) 또는 2대 |
| DB | 1개 | 1개 (RLS) |
| 스토리지 | 315GB | 1TB+ (기관별 100GB) |
| Orthanc | 1개 | 1개 (Label 격리) |
| 월 비용 | ~$20 | ~$40~80 |

---

## 8. 일정

```
Phase 1 (1주): 기반 — tenants 테이블, 미들웨어, JWT
Phase 2 (2주): 데이터 격리 — RLS, Label, Redis, API 필터
Phase 3 (1주): 관리 UI — 슈퍼 관리자 대시보드
Phase 4 (1주): 테스트 — 격리 검증, 성능, 마이그레이션

총 5주
```

---

## 9. 선행 조건

- [x] v1.1 Sprint 1~4 완료
- [x] Alembic 마이그레이션 체계 구축
- [x] 자동 백업 시스템 (마이그레이션 전 필수)
- [ ] 최소 2개 기관 테스트 데이터 준비
- [ ] 서버 스토리지 확장 (필요 시)

---

## 10. 결정 필요 사항

| # | 질문 | 옵션 | 권장 |
|---|------|------|------|
| 1 | 테넌트 식별 방법 | 서브도메인 / JWT claim / 헤더 | JWT claim |
| 2 | 영상 격리 방법 | Orthanc 인스턴스 분리 / Label | Label |
| 3 | AI 모델 공유 | 기관별 독립 / 공유 | 공유 (tenant_id=NULL) |
| 4 | 요금제 | 무료 / 스토리지 기반 / 사용자 수 기반 | (사업 결정) |
| 5 | 도메인 | *.openpacs.kr / 기관 자체 도메인 | (사업 결정) |

---

**작성**: Claude Code  
**다음 단계**: 결정 사항 확정 후 Phase 1 착수
