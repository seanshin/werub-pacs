# OpenPACS — IHE XDS-I.b 적합성 매핑 (Phase 0)

**작성**: 2026-06-12
**목적**: 기존 OpenPACS 자산을 IHE XDS-I.b 액터/트랜잭션에 매핑해, 멀티기관(v2.0) 도입 시
**무엇이 충족·미충족인지** 명확화. *연동 대상 도메인 미정으로 구현은 보류, 본 문서는 게이트 자료.*

---

## 1. XDS-I.b 액터 vs OpenPACS

| IHE 액터 | 역할 | OpenPACS 현황 | 판정 |
|----------|------|---------------|:----:|
| **Imaging Document Source** | 영상+매니페스트를 Repository에 제출 | KOS 생성 보유, 제출(ITI-41) 미구현 | 🟡 부분 |
| **Imaging Document Consumer** | Registry 질의→영상 retrieve | 점대점 Q/R만(`dicom_remotes`), Registry 질의 없음 | 🟡 부분 |
| **Document Registry** | 메타데이터 색인·질의(ITI-18/42) | 없음 | ❌ |
| **Document Repository** | 매니페스트/문서 저장(ITI-41/43) | 없음(내부 Orthanc는 자기 저장소) | ❌ |
| **Patient Identity Source / PIX·PDQ** | 교차기관 환자 ID | 단일기관 MRN만 | ❌ |
| **ATNA (감사·보안)** | 감사·노드인증 | 감사로그 보유, IHE ATNA 포맷 미준수 | 🟡 부분 |

## 2. 트랜잭션 매핑

| 트랜잭션 | 설명 | 기존 자산 | 격차 |
|----------|------|-----------|------|
| **RAD-68 Provide & Register Imaging Document Set** | 소스→저장소 제출 | KOS `kos_service.build_kos` 생성 가능 | ITI-41 제출 클라이언트 미구현 |
| **ITI-18 Registry Stored Query** | 등록소 환자 영상 질의 | — | 미구현(Registry 부재) |
| **RAD-69 Retrieve Imaging Document Set** | 매니페스트 기반 원격 retrieve | DICOMweb WADO-RS / `dicom_remotes` C-MOVE | XDS 매니페스트 연계 미구현 |
| **RAD-55 WADO Retrieve** | WADO로 인스턴스 조회 | DICOMweb 보유 | ✅(전송 계층은 충족) |
| **ITI-8/44 Patient Identity Feed** | 환자 ID 동기 | 단일기관 매핑(HIS) | 교차기관 PIX 부재 |

## 3. 핵심 산출물: KOS 매니페스트

XDS-I의 중심은 영상 목록을 기술하는 **KOS(Key Object Selection)** 매니페스트다. OpenPACS는
`kos_service.build_kos`(highdicom `KeyObjectSelectionDocument`)로 **이미 표준 KOS를 생성**한다
(study 단위, 참조 SOP 인스턴스 기술). → XDS-I 제출 시 이 KOS를 그대로 매니페스트로 사용 가능.

**미충족**: KOS를 외부 **Repository에 ITI-41로 제출**하는 클라이언트와, 제출 메타데이터
(submission set, patient ID in affinity domain) 구성.

## 4. 격차 요약 → v2.0 작업 항목

| 우선 | 항목 | Phase |
|:----:|------|:-----:|
| 1 | Imaging Document Source: KOS→외부 Registry/Repository ITI-41 제출 | 1 (대상 도메인 필요) |
| 2 | 교차기관 환자식별(PIX/PDQ 또는 affinity domain ID 매핑) | 2 |
| 3 | Consumer: ITI-18 Stored Query + RAD-69 retrieve 연계 | 2 |
| 4 | ATNA 감사 포맷·노드 인증 | 2 |
| (대안) | Registry/Repository 자체 호스팅 | v2.0 멀티기관 본체 |

## 5. 현재 충족 중인 대안 (단일기관 맥락)

기관 간 영상 공유 수요를 OpenPACS는 **점대점·포털형**으로 충족 중:
- **외부 PACS Q/R** `dicom_remotes`(C-ECHO/FIND/MOVE) — 알려진 노드 간 직접 조회·수신
- **협진/공유 포털** `external_consult`·`share_link`·`consult_portal` — 토큰 기반 외부 열람
- **환자 결과 추출** `patient-export`(v11.7) — 의료망 분리 외부 전달
- **FHIR ImagingStudy** — 현대적 색인 대안(향후 MHD/IID로 XDS 대체 경로도 가능)

→ **affinity domain 없이도 실무 공유는 위 수단으로 가능.** XDS-I는 표준화된 다자 교류체계에
참여할 때 가치가 크다.

## 6. Phase 1 착수 게이트 (재확인)

1. 연동할 XDS-I affinity domain 실재 (지역/국가 영상교류) — **현재 없음 → Phase 0에서 정지**
2. Registry/Repository 엔드포인트 + 환자 ID 매핑 규약 제공
3. 위 충족 시 Phase 1(Source 역할) 착수: KOS는 보유했으므로 **ITI-41 제출 클라이언트 + 환자ID
   매핑**이 주 작업

## 결론

OpenPACS는 XDS-I의 **매니페스트(KOS)·전송(WADO/DICOMweb)·점대점 Q/R**을 보유하나, **등록소와
교차기관 환자식별**이 없어 완전 XDS-I는 **v2.0 멀티기관 트랙**이다. 연동 대상 도메인이 확정되면
Phase 1(Imaging Document Source)이 가장 작은 진입점이며, KOS 자산 덕에 중간 규모로 가능하다.
대상 부재인 현재는 **본 적합성 문서로 게이트를 표시하고 보류**한다.
