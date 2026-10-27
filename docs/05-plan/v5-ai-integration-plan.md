# OpenPACS v5.0 — AI Server 연동 강화 + AI 판독문 작성 기획서

> **작성일**: 2026-05-12
> **기반**: OpenPACS v4.1 (79 API) + WeRUB AI Server v2.35 (MedGemma 4B)
> **목표**: AI 서버의 의료 모델을 OpenPACS Admin에서 직접 활용하여, AI 보조 판독문 작성 워크플로우 구현

---

## 1. 현재 상태

### 1.1 AI Server (WeRUB v2.35) 의료 기능

| API | 용도 | 상태 |
|-----|------|:----:|
| `POST /api/vision/medical/analyze` | 의료 영상 분석 (소견/판독/권고) | ✅ 연동 완료 |
| `POST /api/medical/report` | 구조화 판독문 생성 | ⬜ 미연동 |
| `GET /api/medical/models` | 의료 모델 목록 | ⬜ 미연동 |
| `POST /api/medical/summarize` | 의무기록 요약 | ⬜ 미연동 |
| `POST /api/medical/explain` | 소견 쉽게 설명 | ⬜ 미연동 |
| `POST /api/medical/differential` | 감별 진단 | ⬜ 미연동 |
| `POST /api/vision/medical/compare` | 이전 영상 비교 판독 | ⬜ 미연동 |

### 1.2 OpenPACS 현재 AI 파이프라인

```
영상 수신 → 자동 트리거 → MedGemma analyze → DICOM SR 저장
```

**미구현**:
- AI 분석 결과로 **판독문 초안 자동 작성**
- **이전 검사 비교 판독** (compare API)
- AI 서버 모델 상태를 Admin Portal에서 확인
- 판독의가 AI 소견을 **편집하여 최종 판독문으로 확정**

---

## 2. 목표

### 2.1 핵심 워크플로우

```
영상 수신 (C-STORE)
    │
    ▼ 자동 트리거
    │
    ├── MedGemma analyze → 소견/판독소견/권고
    │
    ▼ AI 판독문 초안 자동 생성
    │
    ├── 소견 (Findings) ← AI analyze + 한국어 판독 템플릿 결합
    ├── 결론 (Impression) ← AI impression
    ├── 권고 (Recommendations) ← AI recommendations
    │
    ▼ 판독의 검토
    │
    ├── AI 초안 확인/편집 (듀얼 화면 판독 뷰)
    ├── 이전 검사 비교 (compare API 호출)
    ├── 수정 후 서명
    │
    ▼ 최종 판독문
    │
    ├── DICOM SR 저장
    ├── PDF 생성
    └── 의뢰의 알림
```

### 2.2 대상 사용자 시나리오

**영상의학과 전문의 (판독의)**
1. 판독 큐에서 검사 선택 → 듀얼 화면 열기
2. **"AI 분석" 버튼** 클릭 → MedGemma가 소견 자동 생성
3. AI 소견이 리포트 패널에 **자동 채워짐** (초안)
4. 판독의가 소견 검토/수정 → 결론 확인
5. **"이전 검사 비교"** 버튼 → AI가 변화 분석
6. 서명 → 최종 판독문

---

## 3. 기능 명세

### 3.1 AI Server 연동 API 확장

#### 3.1.1 AI 영상 분석 + 판독문 초안 자동 생성

**백엔드 API**:
```
POST /api/v1/ai/analyze-and-draft
{
  "study_instance_uid": "1.2.3...",
  "series_instance_uid": "1.2.3...",  // 선택
  "modality": "CR",
  "template_id": "chest-pa-template-id",  // 선택, 있으면 템플릿 구조에 맞춰 AI 소견 배치
  "auto_create_report": true  // true면 리포트 초안 자동 생성
}
```

**처리 흐름**:
1. Orthanc에서 영상 가져오기 (JPEG 변환)
2. AI Server `/api/vision/medical/analyze` 호출
3. 응답의 findings/impression/recommendations를 한국어 판독 템플릿에 매핑
4. `auto_create_report=true`면 Report를 draft 상태로 자동 생성
5. 결과 반환 (AI 소견 + 리포트 ID)

**응답**:
```json
{
  "ai_analysis": {
    "findings": "폐는 투명하고 팽창 정상...",
    "impression": "정상 흉부 소견",
    "recommendations": "추가 검사 불필요",
    "model": "medgemma:4b",
    "duration_ms": 525
  },
  "report_id": "uuid-...",  // 자동 생성된 리포트 ID
  "report_status": "draft",
  "template_applied": "흉부 X-ray (Chest PA)"
}
```

#### 3.1.2 이전 검사 비교 판독

**백엔드 API**:
```
POST /api/v1/ai/compare-studies
{
  "current_study_uid": "1.2.3...",
  "prior_study_uid": "1.2.3...",  // 선택, 없으면 자동으로 이전 검사 탐색
  "modality": "CR"
}
```

**처리 흐름**:
1. 현재 + 이전 영상을 각각 JPEG 변환
2. AI Server `/api/vision/medical/compare` 호출 (또는 두 영상을 analyze 후 비교)
3. 변화 분석 결과 반환

**응답**:
```json
{
  "comparison": {
    "changes": "이전 검사 대비 폐야 투명도 변화 없음. 심비대 진행 없음.",
    "progression": "stable",  // improved, stable, worsened
    "key_differences": ["변화 없음"]
  },
  "current_analysis": { ... },
  "prior_analysis": { ... }
}
```

#### 3.1.3 AI Server 모델 상태 조회

**백엔드 API**:
```
GET /api/v1/ai/server-status
```

**응답**:
```json
{
  "server_url": "https://example.org/ollama",
  "healthy": true,
  "ollama_status": "running",
  "gpu": { "model": "RTX 5080", "vram_total": "16GB", "vram_used": "4GB" },
  "models": [
    {"name": "medgemma:4b", "size_gb": 4.0, "loaded": true},
    {"name": "medllama2", "size_gb": 3.8, "loaded": true}
  ]
}
```

#### 3.1.4 AI 소견 쉬운 설명 (환자용)

**백엔드 API**:
```
POST /api/v1/ai/explain-findings
{
  "findings": "양측 폐야 깨끗함. 심비대 소견 없음.",
  "target": "patient"  // patient (쉬운 말) 또는 referring (의뢰의용)
}
```

### 3.2 Admin Portal UI 개선

#### 3.2.1 판독 뷰 — AI 보조 버튼 추가

현재 듀얼/단일 판독 뷰에 다음 버튼 추가:

```
┌──────────────────────────────┬──────────────────────┐
│                              │  📋 판독 리포트       │
│    OHIF Viewer               │                      │
│                              │  [🤖 AI 분석]         │
│                              │  [📊 이전 비교]       │
│                              │  ───────────────     │
│                              │  소견: (AI 자동 채움)  │
│                              │  결론: (AI 자동 채움)  │
│                              │  ───────────────     │
│                              │  [저장] [서명]        │
└──────────────────────────────┴──────────────────────┘
```

**AI 분석 버튼 클릭 시**:
1. 로딩 스피너 표시 ("MedGemma 분석 중...")
2. `/api/v1/ai/analyze-and-draft` 호출
3. 소견/결론/권고 필드에 AI 결과 자동 채움
4. "AI 초안" 배지 표시 (판독의가 검토 필요함을 명시)
5. 판독의가 수정 후 서명

**이전 비교 버튼 클릭 시**:
1. 동일 환자의 이전 Study 자동 탐색
2. `/api/v1/ai/compare-studies` 호출
3. 비교 결과를 소견 하단에 추가 ("이전 검사 비교: ...")

#### 3.2.2 AI 서버 모니터링 페이지

Admin Portal `/pacs-admin/ai` 페이지에 추가:

```
┌─────────────────────────────────────────────┐
│  AI Server Status                           │
│  ┌─────────────────────────────────────────┐│
│  │  🟢 Connected: example.org/ollama        ││
│  │  GPU: RTX 5080 (4/16 GB VRAM)          ││
│  │  Models: medgemma:4b ✅, medllama2 ✅   ││
│  └─────────────────────────────────────────┘│
│                                             │
│  Recent AI Analyses                         │
│  ┌────────┬─────────┬──────┬───────┬──────┐│
│  │ 시간    │ 환자     │ 모달 │ 시간   │ 결과 ││
│  │ 10:30  │ 홍길동   │ CR  │ 525ms │ 정상  ││
│  │ 10:25  │ 김철수   │ CT  │ 3.9s  │ 이상  ││
│  └────────┴─────────┴──────┴───────┴──────┘│
└─────────────────────────────────────────────┘
```

### 3.3 판독문 자동화 워크플로우

#### 3.3.1 AI 판독문 초안 자동 생성 규칙

| 조건 | 동작 |
|------|------|
| 영상 수신 + AI 자동 트리거 완료 | 리포트 초안 자동 생성 (draft) |
| 긴급 소견 (is_critical) | 즉시 알림 + 리포트에 "긴급" 표시 |
| 이전 검사 존재 | 자동 비교 분석 포함 |
| AI 실패 | 빈 리포트 생성 (수동 판독) |

#### 3.3.2 AI 초안 → 최종 판독문 흐름

```
1. AI 분석 완료 → Report(draft) 자동 생성
   - findings = AI 소견
   - impression = AI 판독소견
   - recommendation = AI 권고
   - ai_findings = { raw AI response }
   - status = "draft"
   - author = "AI (MedGemma 4B)"

2. 판독의가 판독 큐에서 확인
   - 판독 큐에 "AI 초안" 배지 표시
   - Study 옆에 AI 분석 요약 (정상/이상)

3. 판독의가 듀얼 화면 열기
   - 좌: OHIF 뷰어 (영상)
   - 우: AI 초안이 채워진 리포트 패널

4. 판독의가 검토/수정
   - AI 소견 확인, 필요 시 수정
   - 이전 비교 버튼으로 추가 분석
   - 결론 수정

5. 서명 → Final
   - author 변경 (AI → 판독의)
   - DICOM SR 저장
   - 의뢰의 알림
```

---

## 4. 기술 구현 계획

### 4.1 백엔드 추가 API (4개)

| API | 설명 |
|-----|------|
| `POST /ai/analyze-and-draft` | AI 분석 + 리포트 초안 자동 생성 |
| `POST /ai/compare-studies` | 이전 검사 비교 분석 |
| `GET /ai/server-status` | AI 서버 상태 (GPU, 모델, 건강) |
| `POST /ai/explain-findings` | AI 소견 쉬운 설명 (환자/의뢰의용) |

### 4.2 프론트엔드 수정

| 페이지 | 수정 |
|--------|------|
| `/pacs-admin/reading/view` | AI 분석/비교 버튼, AI 초안 자동 채움 |
| `/pacs-admin/ai` | AI 서버 상태 패널, 최근 분석 이력 |
| `/pacs-admin/reading` | AI 초안 상태 배지 |

### 4.3 Celery Worker 수정

| 작업 | 설명 |
|------|------|
| AI 추론 완료 후 | 리포트 초안 자동 생성 (auto_create_report) |
| 이전 Study 탐색 | 동일 환자 + 동일 모달리티 자동 매칭 |

---

## 5. 개발 일정

| Phase | 기간 | 내용 |
|:-----:|:----:|------|
| 1 | 1일 | analyze-and-draft API + 리포트 초안 자동 생성 |
| 2 | 1일 | compare-studies API + 이전 검사 비교 |
| 3 | 1일 | Admin UI 수정 (AI 버튼, 서버 상태) |
| 4 | 0.5일 | E2E 테스트 + 릴리즈 |

---

## 6. AI Server 연동 상세

### 6.1 WeRUB AI Server 의료 API (v2.35)

| 카테고리 | API 수 | 설명 |
|----------|:------:|------|
| **Medical Vision** | 3 | 영상 분석, 비교 판독, 모델 목록 |
| **Medical AI** | 22 | SOAP 요약, 감별진단, 약물상호작용, RAG |
| **Symptom Triage** | 4 | 증상→진료과, 응급감지 |
| **Medical CLI** | - | 수가계산, 청구검증, 약물조회 |

### 6.2 연동 대상 API

| AI Server API | OpenPACS 용도 | 우선순위 |
|---------------|-------------|:--------:|
| `/api/vision/medical/analyze` | 영상 분석 + 소견 생성 | ✅ 완료 |
| `/api/vision/medical/compare` | 이전 검사 비교 | P0 |
| `/api/medical/report` | 구조화 판독문 생성 | P0 |
| `/api/medical/models` | AI 모델 상태 조회 | P1 |
| `/api/medical/explain` | 소견 쉬운 설명 | P1 |
| `/api/medical/summarize` | 의무기록 요약 | P2 |
| `/api/medical/differential` | 감별 진단 | P2 |

---

## 7. 성공 기준

| 기준 | 목표 |
|------|------|
| AI 소견 자동 채움 | 판독의가 빈 리포트 대신 AI 초안부터 시작 |
| AI 분석 시간 | < 5초 (MedGemma 4B, GPU) |
| 판독 TAT 단축 | AI 초안으로 판독 시간 30% 이상 단축 |
| 이전 비교 | 동일 환자 이전 검사 자동 탐색 + AI 비교 |
| 긴급 소견 | AI 감지 → 즉시 알림 → 판독 큐 최상단 |
