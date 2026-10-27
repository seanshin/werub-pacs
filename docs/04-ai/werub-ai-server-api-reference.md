# WeRU.B AI Server — 통합 API 레퍼런스

> Version: v2.48.0 | 330+ API | 23 Blueprint | 27 모델 (의료 11종)  
> Base URL: `https://example.org/ollama`  
> Swagger: `https://example.org/ollama/docs`

---

## 목차

1. [서버 정보](#1-서버-정보)
2. [인증](#2-인증)
3. [Ollama 프록시 (23 API)](#3-ollama-프록시)
4. [Queue 배치 (16 API)](#4-queue-배치)
5. [Image 생성 (15 API)](#5-image-생성)
6. [HR Law 법률 AI (23 API)](#6-hr-law)
7. [Game NPC AI (40 API)](#7-game-npc)
8. [Medical AI 진료 (22 API)](#8-medical-ai)
9. [Medical CLI 업무 자동화 (7 API)](#9-medical-cli)
10. [Symptom Triage 증상 추천 (4 API)](#10-symptom-triage)
11. [Coding AI 코드 생성 (17 API)](#11-coding-ai)
12. [Orchestrator 워크플로우 (7 API)](#12-orchestrator)
13. [System/Activity/RAG (30 API)](#13-system)
14. [모델 현황](#14-모델)
15. [에러 코드](#15-에러-코드)
16. [OpenPACS 연동 현황](#16-openpacs-연동)

---

## 1. 서버 정보

| 항목 | 값 |
|------|-----|
| OS | Ubuntu 24.04, RTX 5080 16GB |
| Framework | Flask + Gunicorn (gthread 2W×8T) |
| LLM Engine | Ollama v0.21.0 |
| Vector DB | ChromaDB (bge-m3 1024d, nomic-embed 768d) |
| Database | SQLite WAL (queue.db, medical.db, clinic_codes.db, chat_sessions/messages) |

---

## 2. 인증

| 방식 | 헤더 | 대상 |
|------|------|------|
| API Key | `Authorization: Bearer sk-xxx` | Ollama, Queue, System, Image 등 |
| Medical Key | `X-Medical-Key: med-xxx` | Medical AI, CLI |
| Game Key | `X-Game-Key: game-xxx` | Game NPC |
| HR Law Key | `X-Tenant-Key: hr-xxx` | HR Law |
| 없음 | — | Triage, Coding, Code RAG |

---

## 8. Medical AI (OpenPACS 연동 대상)

### 진료 지원 (한국어)

| Method | Endpoint | Description | OpenPACS |
|--------|----------|-------------|:--------:|
| POST | `/api/medical/summarize` | 진료 기록 → SOAP 요약 | ✅ |
| POST | `/api/medical/analyze` | 감별진단 (Top 3 + ICD-10) | ✅ |
| POST | `/api/medical/reference` | 의학 참고 (RAG 벡터 검색) | ✅ |
| POST | `/api/medical/explain` | 환자 설명문 | ✅ |
| POST | `/api/medical/draft` | 의무기록 초안 | ✅ |
| POST | `/api/medical/drug-interactions` | 약물 상호작용 검사 | ✅ |
| POST | `/api/medical/auto-record` | 진료대화 → SOAP + ICD-10 자동 | ✅ |

### Medical Advanced AI

| Method | Endpoint | Description | OpenPACS |
|--------|----------|-------------|:--------:|
| POST | `/api/medical/reasoning/chain` | 5단계 추론 체인 | ✅ |
| POST | `/api/medical/predict/readmission` | 30일 재입원 위험도 | ✅ |
| POST | `/api/medical/predict/complication` | 합병증 위험도 예측 | ✅ |
| POST | `/api/medical/predict/adverse-drug` | 약물 부작용 예측 | ✅ |

### Vision (의료 영상)

| Method | Endpoint | Description | OpenPACS |
|--------|----------|-------------|:--------:|
| POST | `/api/vision/medical/analyze` | 의료 영상 분석 (MedGemma) | ✅ |
| POST | `/api/vision/medical/report` | 비교 판독 보고서 | ✅ |
| POST | `/api/vision/medical/structured-report` | BI-RADS/Lung-RADS | ✅ |
| POST | `/api/vision/medical/precheck` | AI 분석 사전검증 | ✅ |

### FHIR R4 Interoperability

| Method | Endpoint | FHIR Resource | OpenPACS |
|--------|----------|---------------|:--------:|
| POST | `/api/fhir/DiagnosticReport` | 추론 → DiagnosticReport Bundle | ✅ |
| POST | `/api/fhir/RiskAssessment` | 예측 → RiskAssessment | ✅ |
| POST | `/api/fhir/Observation/drug-check` | 약물 → Observation Bundle | ✅ |
| POST | `/api/fhir/Condition/search` | KCD → Condition searchset | ✅ |
| GET | `/api/fhir/metadata` | CapabilityStatement | ✅ |

### Medical CLI (코드 검색)

| Method | Endpoint | Description | OpenPACS |
|--------|----------|-------------|:--------:|
| POST | `/api/medical/code/kcd` | KCD 질병코드 검색 | ✅ |
| POST | `/api/medical/code/edi` | EDI 수가코드 검색 | ✅ |
| POST | `/api/medical/code/mapping` | 질병→검사/처방 매핑 | ✅ |

### GPU 모니터링

| Method | Endpoint | Description | OpenPACS |
|--------|----------|-------------|:--------:|
| GET | `/api/gpu/scheduler` | GPU 스케줄러 상태 | ✅ |
| GET | `/api/gpu/status` | GPU VRAM 상태 | ✅ |
| GET | `/api/models` | 설치된 모델 목록 | ✅ |
| GET | `/api/server/stats` | 서버 통계 | ✅ |

---

## 14. 모델

### LLM (8개)

| Model | VRAM | Use Case |
|-------|------|----------|
| **qwen2.5:14b** | 9GB | 메인 — 한국어 99%, 상주 |
| qwen2.5-coder:14b | 9GB | 코딩 — HumanEval 88% |
| deepseek-coder-v2:16b | 8.9GB | 빠른 코딩 — 122tok/s |
| exaone3.5:7.8b | 4.8GB | fallback — 한/영 이중 |
| medllama2 | 3.8GB | 의료 임상 분석 (영어) |
| meditron | 3.8GB | 약물/가이드라인 (영어) |
| werub-medical:7b | 4.4GB | 의료 추론 (한국어) |
| thewindmom/llama3-med42-8b | 8.0GB | 임상 예측 |

### Embedding (3개)

| Model | Dim | Use Case |
|-------|-----|----------|
| bge-m3 | 1024 | 의학 RAG (다국어) |
| nomic-embed-text | 768 | 코드 RAG, 범용 |
| mxbai-embed-large | 1024 | 영문 특화 |

---

## 15. 에러 코드

| Code | Description |
|------|-------------|
| 200 | 성공 |
| 400 | 필수 파라미터 누락 |
| 401 | 인증 실패 |
| 404 | 리소스 없음 |
| 429 | 요청 한도 초과 |
| 503 | LLM 서버 오류 |

---

## 16. OpenPACS 연동 현황

### 연동 완료 (v8.6)

**총 27개 API 연동** — 기존 6개 + 신규 21개

#### 기존 연동 (ai_assist.py)
| OpenPACS Endpoint | AI Server API | 기능 |
|-------------------|---------------|------|
| `POST /api/v1/ai/precheck` | `/api/vision/medical/precheck` | AI 분석 사전검증 |
| `POST /api/v1/ai/analyze-and-draft` | `/api/vision/medical/analyze` | 영상 분석 + 판독 초안 |
| `POST /api/v1/ai/compare-studies` | `/api/vision/medical/analyze` ×2 | 이전 검사 비교 |
| `POST /api/v1/ai/compare-report` | `/api/vision/medical/report` | GPU 비교 판독 보고서 |
| `POST /api/v1/ai/explain-findings` | `/api/medical/explain` | 환자 설명문 |
| `POST /api/v1/ai/soap-summary` | `/api/medical/summarize` | SOAP 요약 |
| `POST /api/v1/ai/differential-diagnosis` | `/api/medical/analyze` | 감별진단 |
| `GET /api/v1/ai/server-status` | `/api/health` | AI 서버 상태 |

#### 신규 연동 (ai_advanced.py)
| OpenPACS Endpoint | AI Server API | 기능 | 응답시간 |
|-------------------|---------------|------|----------|
| `POST /api/v1/ai/advanced/reasoning-chain` | `/api/medical/reasoning/chain` | 5단계 추론 | ~8초 |
| `POST /api/v1/ai/advanced/structured-report` | `/api/vision/medical/structured-report` | BI-RADS/Lung-RADS | ~10초 |
| `POST /api/v1/ai/advanced/drug-interactions` | `/api/medical/drug-interactions` | 약물 상호작용 | <1초 |
| `POST /api/v1/ai/advanced/predict/readmission` | `/api/medical/predict/readmission` | 재입원 위험도 | ~7초 |
| `POST /api/v1/ai/advanced/predict/complication` | `/api/medical/predict/complication` | 합병증 예측 | ~6초 |
| `POST /api/v1/ai/advanced/predict/adverse-drug` | `/api/medical/predict/adverse-drug` | 약물 부작용 | ~3초 |
| `POST /api/v1/ai/advanced/fhir/diagnostic-report` | `/api/fhir/DiagnosticReport` | FHIR 진단보고서 | ~10초 |
| `POST /api/v1/ai/advanced/fhir/risk-assessment` | `/api/fhir/RiskAssessment` | FHIR 위험평가 | ~7초 |
| `POST /api/v1/ai/advanced/fhir/drug-check` | `/api/fhir/Observation/drug-check` | FHIR 약물검사 | <1초 |
| `POST /api/v1/ai/advanced/fhir/condition-search` | `/api/fhir/Condition/search` | FHIR KCD 검색 | <1초 |
| `GET /api/v1/ai/advanced/fhir/metadata` | `/api/fhir/metadata` | FHIR Capability | <1초 |
| `POST /api/v1/ai/advanced/codes/kcd` | `/api/medical/code/kcd` | KCD 코드 검색 | <1초 |
| `POST /api/v1/ai/advanced/codes/edi` | `/api/medical/code/edi` | EDI 수가코드 | <1초 |
| `POST /api/v1/ai/advanced/codes/mapping` | `/api/medical/code/mapping` | 질병→검사 매핑 | <1초 |
| `GET /api/v1/ai/advanced/gpu/status` | `/api/gpu/scheduler` | GPU 스케줄러 | <1초 |
| `GET /api/v1/ai/advanced/gpu/vram` | `/api/gpu/status` | VRAM 상태 | <1초 |
| `GET /api/v1/ai/advanced/server/models` | `/api/models` | 모델 목록 (27개) | <1초 |
| `GET /api/v1/ai/advanced/server/stats` | `/api/server/stats` | 서버 통계 | <1초 |
| `POST /api/v1/ai/advanced/medical-draft` | `/api/medical/draft` | 의무기록 초안 | ~5초 |
| `POST /api/v1/ai/advanced/medical-reference` | `/api/medical/reference` | 의학 RAG 검색 | ~3초 |
| `POST /api/v1/ai/advanced/auto-record` | `/api/medical/auto-record` | 진료대화→의무기록 | ~30초 |

### 설정

```bash
# .env (서버 환경변수)
AI_SERVER_URL=https://example.org/ollama
AI_API_KEY=CHANGE_ME
AI_MEDICAL_KEY=CHANGE_ME
```

### 테넌트 정보

| 테넌트명 | ID | 용도 |
|----------|-----|------|
| OpenPACS DICOM | 9ca46b65-3b | PACS 의료 AI |
| Hospital RUN HIS | 47b97d8b-18 | HIS 연동 |
