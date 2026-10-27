# EMR-CERT-004 — 진료정보교류표준 영상 적합성 시험계획

**상위**: [EMR-CERT-001](EMR-CERT-001-emr-certification-mapping.md) · [002](EMR-CERT-002-security-criteria-mapping.md) · [003](EMR-CERT-003-interoperability-criteria-mapping.md)
**조사일**: 2026-06-14 · **상태**: 시험계획(Plan) — 실행은 시험 교류망 구축 후

> 본 문서는 **시험계획**(어떻게 검증할지)이며 시험결과가 아니다. 실제 적합성 시험은
> 시험용 진료정보교류망(또는 IHE Gazelle 류 도구) 연동 환경에서 수행해야 한다.

---

## 1. 적용 표준 (근거)

| 표준 | 내용 |
|---|---|
| **진료정보교류 표준** | 보건복지부고시 **제2021-171호**(2021.6.23). 7개 시스템 항목: 환자식별체계·동의/철회·교류객체등록번호·교류문서생성·교류문서교환·**감사로그**·보안 |
| 기반 국제표준 | **HL7 CDA**, **IHE XDS.b**, **ATNA**(감사+노드인증), 영상은 **IX(Image eXchange)≈IHE XDS-I.b** |
| 핵심교류데이터 | **KR-CDI**(2023.8, 77 교류항목) |
| EMR 인증 상호운용성 | I001~I010 ([EMR-CERT-003]) |

## 2. 시험 대상·범위

PACS가 직접 기여하는 영상 상호운용성 + 관련 보안 운영 증빙:
- **I006** 판독소견 · **I007** 영상정보 전송(IX) · **I008** 연결인증 · **I009** 상태알림 · **I010** ATNA 감사
- 보안 운영: S001 백업가동 · S003 NTP · (S005/S011 갭 항목은 조건부)

## 3. 시험 시나리오

| TC | 항목 | 시나리오 | 합격 기준 | 예상 |
|---|:---:|---|---|:---:|
| TC-01 | I007 | study → **KOS 매니페스트** 생성 → **XDS-I/IX(XDM)** 패키지 전송 → 수신측 영상 조회 | KOS(SOPClass 1.2.840.10008.5.1.4.1.1.88.59) 유효, METADATA.XML(ebRIM) 파싱, DICOM 무손실 | ✅ 통과 예상 (`xds_export`·`kos_service` 검증済) |
| TC-02 | I007 | **DICOMweb(QIDO/WADO-RS)** 로 영상 검색·조회 | 표준 응답, 픽셀 정합 | ✅ |
| TC-03 | I006 | 판독소견서 → **DICOM SR(TID 1500)** / FHIR DiagnosticReport 생성·전송 | SR 구조 유효, 소견 코드(LOINC/SNOMED) 매핑 | ✅ (SR) / 🟡 (결론용어 표준코드 매핑은 부분) |
| TC-04 | I008 | 교류 노드 간 **TLS 상호인증** 연결·정보교환 | TLS1.2+ 상호인증, 인증서 검증 | ✅ |
| TC-05 | I009 | 교류 의뢰·수신 **상태 알림** | 폐루프 통지·ack | ✅ |
| TC-06 | **I010** | 접근·전송 이벤트 → **ATNA 감사 메시지**(syslog RFC5424/3881, TLS) 발신 | ATNA 스키마 적합 메시지 수신 | ✅ **어댑터 구현완료**(`atna_audit.py`) — ARR 연동·`atna_enabled=true` 시 통과. XML well-formed·EventID/Participant 검증済 |
| TC-07 | I002 | **MPI/PIX** 환자식별 교환 | PIX 질의·응답 | ⚠️ **미충족** — 단일기관 보류(v2.0) |
| TC-08 | I001 | 환자 **동의/철회** 표준 서식 생성 | 표준 동의서 양식 | 🟡 부분(자체 동의 보유) |
| TC-09 | S001 | 백업·복구 실증 | 백업 cron 가동·복구 리허설 | 🟡 **cron 가동 필요** |
| TC-10 | S005/S011 | 저장 암호·전자서명 | 국산암호 인정/PKI 서명 | ⚠️ 갭(EMR-CERT-002) |

## 4. 예상 결과 요약

| 분류 | TC | 비고 |
|---|---|---|
| ✅ 통과 예상 | TC-01~05 | 영상전송·판독소견·연결·알림 = PACS 본연 |
| ⚠️ 미충족(갭) | TC-06(ATNA)·TC-07(MPI)·TC-10(암호/서명) | 한국 로컬표준 — 개별 조치 필요 |
| 🟡 조건부 | TC-03(결론용어)·TC-08(동의서식)·TC-09(백업가동) | 표준 양식/운영 보강 |

## 5. 시험 환경
- 시험용 진료정보교류 연동망(또는 모의 XDS.b Registry/Repository), DICOMweb/XDM 수신 검증기
- IHE Gazelle 류 적합성 도구(가용 시) — XDS-I.b/ATNA 메시지 검증
- 실 CT/MR 데이터셋(비식별)

## 6. 우선 조치 (시험 전 갭 해소)

| 순위 | 조치 | 항목 | 영향 |
|:--:|---|:---:|---|
| 1 | **백업 cron 가동** | TC-09/S001 | 운영 1줄 — 즉시 |
| 2 | ~~ATNA 감사 어댑터~~ ✅ **구현완료**(`atna_audit.py`, default off) — ARR 엔드포인트만 연동 | TC-06/I010 | 完 |
| 3 | S005 **AES 인정 여부 확인** → 필요시 국산 알고리즘 | TC-10 | 정책 확인 우선 |
| 4 | S011 전자서명 요구수준 확인 | TC-10 | 정책 확인 |
| 5 | MPI/PIX | TC-07 | v2.0(affinity domain) |

## Sources
- [국가법령정보센터 — 진료정보교류 표준(고시 제2021-171호)](https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000202199)
- [보건복지부 — 의료기관 간 진료정보교류 표준 정립](http://www.ssis.or.kr/lay1/bbs/S1T101C487/A/221/view.do?article_seq=110681)
- [한국보건의료정보원 — 진료정보교류시스템(영상 IX)](https://k-his.or.kr/menu.es?mid=a10207000000)
- [대한영상의학회 — 보건의료데이터 상호운용성 표준화(PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11625841/)
