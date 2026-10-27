# HL7 v2 RIS 연동 — 구현 계획서

**작성일**: 2026-06-06
**근거**: `docs/03-analysis/pacs-commercial-comparison.md` 갭(HL7/RIS 완전 통합 △) — 개발 가능 1순위
**목표**: HL7 v2 메시징으로 HIS/RIS와 표준 연동, **DICOM 워크플로(MWL/MPPS/StgCmt) 루프를 HL7로 완성**

---

## 1. 배경·가치

현재 HIS 연동은 **REST API + JWT SSO**(his_integration.py)로 부분 구현. 그러나 다수 병원은 **HL7 v2**(ADT/ORM/ORU)를 표준 메시징으로 사용 → 상용 PACS는 완전 지원, 본 제품은 미지원(갭).

이번 세션에 만든 **DIMSE 워크플로(MWL/MPPS/Storage Commitment)**와 **완벽히 짝**을 이룬다:

```
HIS --HL7 ORM(오더)--> [worklist_items] --MWL C-FIND--> 촬영실
                                              │
                                         촬영 --MPPS--> 상태(진행→완료)
                                              │
HIS <--HL7 ORU(판독결과)-- [판독 서명] <-------┘
```

→ "오더 수신 → 촬영실 워크리스트 → 촬영 추적 → 결과 회신"의 **end-to-end 표준 루프 완성**.

---

## 2. 범위 (Scope)

**In**:
- **MLLP 리스너**(inbound): ORM/OMG/OMI(영상 오더) → `worklist_items` 생성, ADT(환자) → 환자정보 upsert. HL7 ACK 응답.
- **MLLP 클라이언트**(outbound): 판독 서명 시 ORU^R01(판독 결과) → HIS 회신.
- 메시지 파싱·매핑(hl7apy), 코드 매핑(오더→모달리티/검사).
- 관리: HL7 엔드포인트 설정(HIS 호스트/포트), 메시지 로그·재시도.

**Out (후속)**: HL7 FHIR 변환(이미 FHIR R4 있음), SIU(스케줄), DFT(과금), 양방향 환자 머지.

---

## 3. 아키텍처

```
[HIS] ──TCP/MLLP──> [hl7-listener 컨테이너]
                         │ hl7apy 파싱
                         ├─ ORM^O01 → worklist_service.create (→ MWL 자동 노출)
                         ├─ ADT^A04/A08 → patient upsert
                         └─ ACK(AA) 회신
[판독 서명 이벤트] ──> [hl7_outbound] ──MLLP──> [HIS] (ORU^R01)
```

- **신규 컨테이너 `hl7-listener`** (host network, MLLP 포트 예 2575) — mwl-scp와 동일 패턴(backend 이미지, `python -m app.services.hl7_listener`).
- **의존성**: `hl7apy`(파싱·검증·메시지 구성) 또는 `python-hl7`(경량 파싱). → `hl7apy` 권장(ACK/구성 용이).
- **DB 재사용**: `worklist_items`(MWL 모델), `users`/patient. 동기 엔진(mwl-scp 패턴).

---

## 4. 메시지 매핑

### 4.1 Inbound ORM^O01 (영상 오더) → worklist_items
| HL7 필드 | → WorklistItem |
|---|---|
| PID-3 (Patient ID) | patient_id |
| PID-5 (Patient Name) | patient_name |
| PID-7/8 (DOB/Sex) | patient_birth_date / patient_sex |
| ORC-2 / OBR-3 (Placer/Filler Order) | accession_number |
| OBR-4 (Universal Service ID) | requested_procedure_description, modality 매핑 |
| OBR-24 (Diagnostic Service) | modality |
| OBR-27 / TQ1 (Timing) | scheduled_date/time |
| ORC-12 / OBR-16 (Ordering Provider) | referring_physician |

→ 생성 시 StudyInstanceUID 사전생성(MWL과 동일) → 촬영 C-STORE 연결.

### 4.2 Inbound ADT (환자) → patient upsert
- A04(등록)/A08(수정)/A28/A31 → PID 세그먼트로 환자 demographics 갱신.

### 4.3 Outbound ORU^R01 (판독 결과)
- 판독 서명 시: PID(환자) + OBR(검사) + OBX(판독 텍스트/인상) 구성 → MLLP로 HIS 회신.

### 4.4 ACK
- 모든 inbound에 MSA(AA/AE/AR) ACK 회신.

---

## 5. 작업 분해 (Tasks)

1. `hl7apy` 의존성 추가 + 코드 매핑 테이블(OBR-4 service ↔ modality).
2. `hl7_service.py` — 파싱·매핑(ORM→WorklistItem dict, ADT→patient, ORU 구성).
3. `hl7_listener.py` — MLLP TCP 서버(VT/FS/CR 프레이밍), 메시지 라우팅, ACK.
4. `hl7_outbound.py` — 판독 서명 훅 → ORU 구성 → MLLP 클라이언트 송신(재시도).
5. compose에 **hl7-listener 컨테이너** + 설정(HL7_PORT, HIS_HL7_HOST/PORT env).
6. 관리 UI/로그(선택): HL7 메시지 수신/송신 로그.
7. **검증**: 테스트 MLLP 클라이언트로 ORM 송신 → worklist_item 생성 확인 → MWL C-FIND 노출 확인. ORU 송신 → 캡처 확인.

---

## 6. 난이도·리스크

- 난이도: **중**. MLLP/HL7 파싱은 표준, hl7apy 성숙. mwl-scp 서비스 패턴 재사용.
- 리스크: **낮음**(격리된 신규 컨테이너, 기존 무영향). 단 HL7 변형(병원별 Z-segment, 인코딩) 대응 필요 → 관대한 파싱 + 로깅.
- 의존: 없음(자체완결). HIS 실연동은 HIS 측 HL7 엔드포인트 필요하나, **구현·검증은 테스트 MLLP로 자체 가능**.

---

## 7. 완료 기준

- 테스트 ORM^O01 송신 → `worklist_items` 생성 → MWL C-FIND에 노출 → (MPPS로 상태전이) 까지 **end-to-end 동작**.
- ORU^R01 outbound 구성·송신 검증.
- 잘못된 메시지에 AE/AR ACK + 로깅.

---

## 8. 다른 개발 가능 항목 (로드맵)

| 항목 | 상태 | 비고 |
|---|---|---|
| **IHE SWF 적합성 정리** | 핵심 액터 이미 구현(MWL/MPPS/StgCmt) | 적합성 문서화 + 잔여 트랜잭션 |
| **3D 전용 Hanging Protocol** | 기술부 개발 가능 | CT 자동 MPR+VR 레이아웃 (임상튜닝 별도) |
| **음성인식 강화** | 기본 구현됨(Web Speech API) | 의료 어휘·명령어 보강 |

> **권장 순서**: HL7 v2(본 계획) → IHE SWF 정리 → 3D HP → 음성 강화. HL7이 워크플로 표준 루프를 완성하므로 최우선.

---

## 9. PDCA 연계
- Plan: 본 문서
- Design: HL7 메시지 스키마 상세(세그먼트·필드), 코드 매핑 테이블, 컨테이너 설정
- Do: hl7_service + hl7_listener + hl7_outbound + 컨테이너
- Check: 테스트 MLLP ORM→worklist→MWL E2E + ORU 검증
- Act/Report: 완료 보고 + 비교표 갱신(HL7/RIS △→✅)

---

## 10. ✅ 구현·배포·검증 완료 (2026-06-06)
- **`hl7_service.py`**(python-hl7 파싱·ORM→WorklistItem 매핑·ACK/ORU 구성) + **`hl7_listener.py`**(MLLP TCP 서버, 라우팅).
- **신규 컨테이너 `hl7-listener`** (host network, **127.0.0.1:2575**, backend 이미지, `python -m app.services.hl7_listener`). hl7==0.4.5.
- **검증 (E2E)**: 테스트 ORM^O01 MLLP 송신 → **ACK MSA|AA** → `worklist_items` 생성(김철수/CT/한글명) → **MWL C-FIND 노출**(TOTAL 3→4). HL7 ORM → worklist → MWL 루프 동작 확정.
- 잔여: ORU outbound(판독 서명 훅 연결), ADT 환자 upsert(현재 ACK만), 관리 UI 로그.
- compose 백업 `docker-compose.yml.bak.20260606-hl7`. 컨테이너 14→15.
