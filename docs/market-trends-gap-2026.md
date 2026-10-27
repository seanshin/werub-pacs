# 해외 PACS 트렌드 vs OpenPACS 갭 분석 (2026-06)

해외 상용 PACS의 2025–2026 트렌드를 조사하고 OpenPACS 현 기능과 대조한 결과.
**결론: OpenPACS는 트렌드 대부분을 이미 보유. 진짜 신규 기획 갭은 2건.**

## 트렌드 → OpenPACS 보유 여부

| 2025–2026 트렌드 | OpenPACS | 근거 |
|------------------|:--------:|------|
| AI 오케스트레이션(3rd-party 라우팅, SR 임베드) | ✅ 보유 | `ai_orchestration.py` 파이프라인+버전+롤백 (v8.8) |
| AI 결과 → DICOM SR(TID 1500) | ✅ 보유 | highdicom TID 1500 SR (v10.1) |
| AI 결과 → FHIR DiagnosticReport 브리지 | ✅ 보유 | `ai_advanced.py` → FHIR R4 DiagnosticReport+Observation |
| 워크플로 오케스트레이션(리딩리스트, 부하분산) | ✅ 보유 | 근무 자동배정, SLA 에스컬레이션 |
| 폐루프 위험소견 통지(ack) | ✅ 보유 | `notification.py` acknowledge, 긴급도 |
| 환자 engagement 포털 | ✅ 보유 | 환자 결과 추출(v11.7~8) |
| Zero-footprint 서버 렌더(대용량 3D 스트리밍) | 🟡 부분 | 클라이언트 VRT 완료, 서버 GPU는 직결망 대기(자가진단) |
| 구조화 리포팅 | ✅ 보유 | 템플릿, 구조화 입력, SR |
| 표준 상호운용(DICOMweb/FHIR) | ✅ 보유 | DICOMweb, FHIR R4 |
| **수신 시 자동 AI 스크리닝(opportunistic)** | ❌ **갭** | `auto_validate`는 **검증만**, AI는 on-demand |
| **AI 거버넌스(성능 모니터링/드리프트/수용률)** | 🟡 부분 | 버전·롤백은 있으나 모니터링·드리프트·수용추적 없음 |
| 엔터프라이즈 이미징(다과 통합: 심장·병리·안과) | ❌ | 영상의학 전용 — v2.0 대규모 |
| 클라우드 네이티브 / 멀티사이트 / XDS-I | ❌ | 단일기관 — v2.0 스코프(기 명시) |

## 진짜 갭 (단일기관 v1.x 범위 내, 신규 기획 가능)

### 갭 1 — Opportunistic AI 스크리닝 (★ 최우선, 트렌드 1위)
**무엇**: 수신되는 **모든** 검사에 AI를 자동 실행해 우연소견(폐결절, 관상동맥석회화 CAC 등)을
선제 탐지하고 판독의에게 알림. 2025–2026 가장 뜨거운 트렌드(Aidoc/RapidAI/Rad AI 방향).
- **현재**: OpenPACS AI는 **on-demand**(뷰어에서 판독의가 트리거). 수신 시 자동 실행 없음.
- **왜 적합**: 인프라가 **이미 다 있음** — `auto_validate_new_studies`(5분 스캔 패턴) + AI 파이프라인
  29모델 + `run_inference` + 알림 시스템. **연결만 하면 됨**(스캔→모달리티별 파이프라인 자동추론→
  소견 시 통지). 낮은 비용, 높은 임팩트.
- **규제**: 선제 AI는 SaMD 경계 — 임상용/연구용 분리 원칙 적용, "보조 알림"으로 한정

### 갭 2 — AI 거버넌스/모니터링 (SaMD 정렬)
**무엇**: 모델 성능 시계열 모니터링, 드리프트 감지, **AI 소견 수용/기각 추적**(판독의가 AI를
받아들였나?), 감사·롤백 대시보드. 2026 RIS 플레이북의 "AI governance" 벤치마크.
- **현재**: 파이프라인 버전·롤백은 있으나 성능 모니터링·드리프트·수용률 추적 없음.
- **왜 적합**: SaMD 규제 대응(프로젝트 핵심 가치)과 직결. v11.6 vrt_metrics·prefetch 계측과
  동일한 "운영 데이터 수집" 노선. 갭 1의 선제 AI가 생성하는 소견의 수용률을 측정하면 자연 연계.

## v2.0 스코프(대규모, 별도 트랙)
- 엔터프라이즈 이미징(다과 통합), 클라우드 네이티브, 멀티사이트, IHE XDS-I/XCA-I

## 권고
**갭 1(Opportunistic AI 스크리닝)**을 다음 기획으로. 트렌드 1위이면서 OpenPACS 인프라로 저비용 구현
가능하고, 갭 2(거버넌스)는 그 수용률 데이터를 측정하는 후속으로 자연 연결된다.

## Sources
- [ITN — From PACS to Enterprise Imaging](https://www.itnonline.com/article/pacs-enterprise-imaging)
- [Radiology Business — Key radiology IT trends](https://radiologybusiness.com/topics/health-it/enterprise-imaging/imaging-informatics/key-radiology-it-trends-worth-watching)
- [Signify Research — 5 key trends in PACS](https://radiologybusiness.com/topics/health-it/enterprise-imaging/5-key-trends-pacs-and-enterprise-imaging-signify-research)
- [AdvaPACS — RSNA 2025 Cloud PACS](https://advapacs.com/rsna-2025-cloud-pacs-complete-imaging-solution/)
- [RSNA — AI Helps Identify Incidental Findings (2025)](https://www.rsna.org/news/2025/june/ai-helps-identify-incidental-findings)
- [Opportunistic Screening: Radiology Scientific Expert Panel (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10315516/)
- [Rad AI — RSNA 2025: Five Trends](https://www.radai.com/blogs/rsna-2025-five-trends-shaping-radiologys-next-chapter)
- [2026 European RIS Playbook (Newswire)](https://www.newswire.com/news/2026-european-radiology-information-system-playbook-sets-benchmarks-22670988)
- [Nirmitee — DICOM Meets FHIR](https://nirmitee.io/blog/dicom-fhir-medical-imaging-interoperability-complete-guide/)
