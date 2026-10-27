# EMR-CERT-003 — EMR 인증 상호운용성 항목별 매핑 (I001–I010)

**상위**: [EMR-CERT-001](EMR-CERT-001-emr-certification-mapping.md) · [EMR-CERT-002](EMR-CERT-002-security-criteria-mapping.md)
**조사일**: 2026-06-14 · **출처**: EMR 표준프레임워크 상호운용성 참조모듈(emrcert.mohw.go.kr, `crtfc_gb=02`)
**상태**: 상호운용성 항목별 매핑 완료(초안)

> 상호운용성 부문 = **진료정보교류(HIE) 표준 적용 여부**. PACS는 인증 직접대상이 아니나,
> **I006(판독소견)·I007(영상정보 전송)·I010(ATNA 감사)** 등은 **영상 서브시스템(OpenPACS)이
> 실제로 충족해야** 인증 EMR이 영상 교류를 할 수 있다 — PACS가 핵심 기여.
> 의원급(유형1) 필수: 기능성 28 / 보안성 13 / **상호운용성 10**.

---

## 상호운용성 항목별 OpenPACS 대조

| 코드 | 인증 항목 | PACS 관련 | OpenPACS | 근거 / 비고 |
|:---:|---|:---:|:---:|---|
| **I001** | 진료정보교류 환자 동의(철회)서 생성 | 간접 | 🟡 부분 | 협진/공유 동의(`consult_portal.py`, `share_link`), 환자추출 동의. **진료정보교류 표준 동의서 양식**은 미준수 |
| **I002** | 주민번호 대체 환자식별(MPI) 생성 | ○ | ⚠️ **갭 → v2.0 백로그** | MRN=PatientID 매핑(`patient_mapping.py`)은 있으나 **IHE PIX/MPI 표준 미구현**(교차기관 환자식별 부재). **v2.0 멀티기관 스코프로 정리(2026-06-15)** — XDS-I Phase1(ITI-41)·멀티사이트와 동일 게이트(affinity domain 실재 시). 단일기관 v1.x는 MRN 직매핑으로 충족 |
| **I003** | 진료의뢰 정보 생성·조회 | 간접 | 🟡 부분 | 외부 협진/의뢰(`external_consult.py`) 보유, 표준 의뢰서 포맷 아님 |
| **I004** | 진료회송 정보 생성·조회 | 간접 | 🟡 부분 | 협진 회신 보유, 표준 회송서 아님 |
| **I005** | 진료기록요약 생성·조회 | ✕ | N/A | **EMR(HospitalRun) 영역** — PACS 무관 |
| **I006** | **판독소견 정보 생성·조회** | ★ | ✅ | 판독 리포트(`report.py`), FHIR DiagnosticReport, **DICOM SR(TID 1500, highdicom)** |
| **I007** | **영상정보 전송·조회** | ★★ | ✅✅ | **DICOMweb/WADO**(`dicomweb.py`), **KOS 매니페스트**(`kos_service.py`), **IHE XDS-I/XDM**(`xds_export.py`), 점대점 Q/R(`dicom_remotes.py`) |
| **I008** | 교류시스템 간 연결 인증 정보교환 | ○ | ✅ | TLS 1.3, 상호인증, 서비스토큰(mrn봉인), Orthanc Basic Auth |
| **I009** | 교류정보 의뢰·상태 알림 | ○ | ✅ | `notification.py`(긴급도·ack), 폐루프 통지 |
| **I010** | **감사로그(ATNA) 생성** | ★ | 🟡 **어댑터 구현** | **ATNA 어댑터 신설**(`atna_audit.py` — DICOM Audit Message RFC3881 + syslog RFC5424, udp/tcp/tls, `_log_audit_entry` 연결, default off). 표준 포맷 발신 구현 완료 — ARR 엔드포인트 연동·`atna_enabled=true` 시 활성. (2026-06-14) |

### 요약
- **충족(✅) 4 / 부분(🟡) 3 / 갭(⚠️) 2 / N/A 1**
- **영상 핵심(I006 판독·I007 영상전송·I008 연결·I009 알림)은 충족** — PACS 본연 역량
- **갭 2건**:
  - **I002 MPI** — IHE PIX/MPI(교차기관 환자식별) 미구현. **affinity domain 실재 시 도입**(이미 [[next-work-candidates]] v2.0 XDS-I Phase1로 식별됨)
  - **I010 ATNA** — 감사로그를 **IHE ATNA 표준 포맷(syslog RFC 3881/5424 + TLS)**으로 발신 필요. 현 DB audit를 ATNA 메시지로 export하는 어댑터 추가로 대응 가능(영향 국소)
- **부분(I001/I003/I004)**: 진료정보교류 **표준 동의서·의뢰서·회송서 양식** 준수 필요 — 다만 의뢰/회송은 EMR 주관, PACS는 영상 첨부 측면

---

## 액션 아이템 (영상 상호운용성)

| # | 항목 | 우선 | 조치 |
|:-:|---|:--:|---|
| 1 | I010 ATNA 감사 | 中 | `audit_logs` → ATNA(syslog RFC5424+TLS, DICOM Audit Message) 발신 어댑터. 영상 교류 시 노드 감사 표준화 |
| 2 | I002 MPI/PIX | 低(v2.0) | affinity domain 확정 시 IHE PIX 환자식별 도입 — 단일기관에선 보류 |
| 3 | I007 적합성 시험 | 高 | 진료정보교류표준 **영상 전송 프로파일** 대조 시험(태그셋·KOS·전송), 실 교류망 연동 |
| 4 | I001/I003/I004 표준 양식 | 中 | 진료정보교류 표준 동의/의뢰/회송 서식 — EMR 연동 분담 정리 |

---

## 종합 (EMR-CERT-001~003)

| 부문 | 항목 | OpenPACS 충족도 | 핵심 갭 |
|---|---|---|---|
| 보안성 (S001~S013) | 13 | 충족9·확인2·갭2 | S005 암호(AES vs 국산), S011 PKI 전자서명 |
| 상호운용성 (I001~I010) | 10 | 충족4·부분3·어댑터1(I010)·갭1(I002)·N/A1 | I002 MPI/PIX (v2.0) |
| 기능성 | 28(유형1) | EMR 영역 | PACS 무관(판독·영상만 기여) |

**결론**: OpenPACS는 EMR 인증의 **영상 상호운용성·보안성을 광범위하게 뒷받침**하며, 핵심 갭은
**한국 로컬 표준 특수성**(국산 암호 S005, 공인전자서명 S011, ATNA 감사 I010, PIX/MPI I002)에 집중.
모두 **계층 한정·국소 영향**이며, 일부(MPI)는 이미 v2.0 멀티기관 스코프로 식별됨. 정식 인증은
**EMR(HospitalRun) 주관 + PACS 연동 적합성 증빙** 구조로 진행.

## Sources
- [EMR 표준프레임워크 — 상호운용성 참조모듈(I001~I010)](https://emrcert.mohw.go.kr/referModule/referModuleLookup.es?mid=a11204020000&crtfc_gb=02&crtfc_id=CRT_0000000000000113)
- [한국보건의료정보원 — 진료정보교류시스템(영상 포함)](https://www.khis.kr/menu.es?mid=a10207000000)
- [HIRA — 심사평가시스템과 EMR인증제·진료정보교류 연계](https://repository.hira.or.kr/)
