# v2.0 트랙 A — XDS-I.b Phase 1 (ITI-41) + PIX/MPI (I002) 설계 노트

**작성**: 2026-07-08
**상태**: **Step 1~4 구현 완료 (2026-07-08)** — 모의 도메인 자체검증 통과. Step 6(실 affinity domain)만 외부 게이트 대기.
**관련**: `docs/01-plan/v2.0-scope-2026.md`(A1·A2 = P0), `docs/xds-i-conformance.md`(Phase 0 매핑),
`docs/regulatory/EMR-CERT-003-interoperability-criteria-mapping.md`(I002 MPI 갭)

---

## 0. 요약

v2.0 트랙 A의 P0 = **A2(PIX/MPI) + A1(XDS-I.b Phase 1 제출)**. EMR 인증 **I002(주민번호 대체
환자식별 MPI)** 갭과 **동일 스코프**이므로 2건을 1 트랙으로 통합한다.

**핵심 게이트(불변)**: 연동할 **affinity domain(상대 기관·Registry/Repository·환자ID 발급기관 규약)이
현재 실재하지 않는다.** 따라서:

- **실 end-to-end 연동 검증은 대상 확정 전까지 불가** — 이 게이트는 코드로 해소 못 함.
- 그러나 v12.2 XDS-I *export*가 "도메인 없이 표준 패키지 생성"으로 성공했듯, **클라이언트/서버 구조는
  모의 affinity domain(루프백 Registry/Repository·모의 발급기관)으로 자체 구현·검증 가능**하다.
- 본 노트는 그 **자체 검증 가능한 PoC 표면**을 정의한다. 실 도메인 확정 시 엔드포인트·OID만 교체하면
  Phase 1 제출이 가동되도록 계약을 고정한다("연동≠생성" 노선).

**비목표(명시)**: IHE Gazelle 공식 인증(A4·별도), Registry/Repository *자체 호스팅*(v2.0 멀티기관 본체·B1),
XCA-I 교차커뮤니티(A3), 실 상대 기관 대상 라이브 제출(대상 부재).

---

## 1. 액터·트랜잭션 매핑 (현 자산 대비)

| IHE 액터/트랜잭션 | OpenPACS가 맡을 역할 | 기존 자산 | 본 Phase 신규 |
|---|---|---|---|
| **Imaging Document Source** (RAD-68 = ITI-41 P&R) | ✅ 우리가 제출자 | `kos_service.build_kos`(KOS 매니페스트), `xds_metadata.build_metadata_xml`(ebRIM) | **ITI-41 SOAP/ebXML+MTOM 엔벨로프 + 제출 클라이언트** |
| **Patient Identity Consumer** (PIX Query ITI-9 / PIXm ITI-83) | ✅ 우리가 질의자 | HIS MRN 매핑(`PatientMapping`) | **MPI 교차참조 테이블 + PIX Query/PIXm 클라이언트** |
| **Patient Identity Source** (PIX Feed ITI-8 / ITI-44) | 🟡 우리가 피드 발신(우리 MRN을 도메인에 등록) | `hl7_listener`(MLLP ORM/ADT 수신) | **ADT^A04/A08 송신(Feed) — 선택** |
| Document Registry / Repository (ITI-18/41/42/43) | ❌ 우리가 호스팅 안 함(상대측) | — | **모의 스텁만**(자체검증용, 프로덕션 아님) |
| ATNA 감사 | 🟡 어댑터 보유 | `docs/regulatory` ATNA 어댑터(v12.4) | ITI-41/PIX 트랜잭션에 감사 이벤트 연결 |
| WADO / RAD-55·69 retrieve | ✅ 전송계층 충족 | DICOMweb WADO-RS, `dicom_remotes` | (변경 없음 — Consumer retrieve는 Phase 2) |

**결론**: 우리는 **Imaging Document Source + Patient Identity Consumer** 두 액터만 Phase 1에서 구현한다.
Registry/Repository는 상대측이 호스팅하는 것이 정상 — 우리는 **제출·질의 클라이언트**만 만든다.

---

## 2. A2 — PIX/MPI 설계 (I002 갭 해소)

### 2.1 문제
현 `PatientMapping`은 **단일 식별 도메인**만 안다: HIS MRN ↔ DICOM PatientID (1:1, 같은 기관).
교차기관에선 **환자 1명이 도메인마다 다른 식별자**를 가진다(예: 우리 MRN `HR-...`, 지역 EMPI ID
`^^^&2.16.840.1.113883.2.x&ISO`, 상대기관 MRN). MPI = 이 식별자들을 **하나의 환자로 교차참조**.

### 2.2 데이터 모델 (신규)

```
identity_domains                    # 식별자 발급기관(assigning authority)
  id UUID pk
  name            VARCHAR           # "OpenPACS-Local", "지역 EMPI", "상대기관 A"
  namespace_id    VARCHAR           # HL7 CX.4.1 (예: "OPENPACS")
  universal_id    VARCHAR           # OID (예: 2.16.840.1.113883.2.x)  — CX.4.2
  universal_type  VARCHAR default 'ISO'
  is_local        BOOLEAN           # 우리 도메인 여부
  is_affinity     BOOLEAN           # affinity domain 대표ID 여부(제출 시 사용)

patient_identifiers                 # 도메인별 환자 식별자
  id UUID pk
  enterprise_id   UUID fk -> mpi_patients.id   # 교차참조 앵커
  domain_id       UUID fk -> identity_domains.id
  identifier      VARCHAR                        # 해당 도메인의 환자 ID
  UNIQUE(domain_id, identifier)

mpi_patients                        # 엔터프라이즈 환자(교차참조 앵커)
  id UUID pk                        # = enterprise identifier(내부)
  created_from    VARCHAR           # 'local' | 'pix_query' | 'feed'
  demographics    JSONB            # 이름/성별/생년(대조 검증용, PHI 최소)
```

> 기존 `patient_mappings`(HIS↔DICOM)는 **유지**. MPI는 그 위 계층 — `is_local` 도메인의 식별자로
> 기존 MRN을 흡수(부팅 마이그레이션 백필: patient_mappings.dicom_patient_id → OPENPACS 도메인 식별자).

### 2.3 인터페이스 (2트랙, 병렬 지원)

**PIXm (FHIR, 권장 — 현대 IHE)** — 이미 FHIR R4 자산 보유:
- `GET /api/v1/pix/Patient/$ihe-pix?sourceIdentifier={system|value}&targetSystem={system}`
  → 소스 도메인 식별자 → 타깃 도메인 교차참조 식별자 반환 (ITI-83).
- 응답: FHIR Parameters(targetIdentifier). 미매칭 시 빈 결과(404 아님).

**PIX v2 (HL7v2, 레거시 상호운용)** — `hl7_listener` MLLP 확장:
- **ITI-9 Query**: `QBP^Q23^QBP_Q21` 수신 → `RSP^K23^RSP_K21` 응답(교차참조 PID.3 목록).
- **ITI-8 Feed**: `ADT^A04(등록)/A08(갱신)/A40(병합)` — 우리 로컬 환자를 affinity domain에 피드(송신·선택).

> Phase 1 자체검증은 **PIXm 우선**(HTTP/FHIR로 E2E 테스트 쉬움). HL7v2 PIX는 상대가 v2만 지원할 때 대비.

### 2.4 자체 검증 (모의 도메인)
- 시드: `identity_domains` 3개(로컬 + 모의 EMPI + 모의 상대기관), `mpi_patients` N명에 도메인별 식별자.
- E2E: `$ihe-pix`로 로컬 MRN → 모의 EMPI ID 교차참조 반환 확인. Feed로 신규 환자 등록 → Query 재확인.

---

## 3. A1 — XDS-I.b Phase 1 (ITI-41 제출 클라이언트)

### 3.1 제출 페이로드 구조 (RAD-68 Provide & Register Imaging Document Set-MTOM)
```
SOAP Envelope (ITI-41 액션: urn:ihe:iti:2007:ProvideAndRegisterDocumentSet-b)
 └ Body: ProvideAndRegisterDocumentSetRequest
    ├ SubmitObjectsRequest (ebRIM)         ← xds_metadata.build_metadata_xml 재사용/확장
    │   ├ RegistryPackage (SubmissionSet)  ← patientId in affinity domain(§2 MPI에서 조회)
    │   ├ ExtrinsicObject (DocumentEntry)  ← KOS 매니페스트 기술
    │   └ Association (HasMember)
    └ Document (MTOM/XOP binary)           ← kos_service.build_kos() DICOM KOS 바이트
```

### 3.2 재사용 vs 신규
- **재사용**: `xds_metadata.build_metadata_xml`(ebRIM SubmissionSet/DocumentEntry/Association 이미 생성),
  `kos_service.build_kos`(KOS 매니페스트). **v12.2 XDM export의 METADATA.XML과 동일 ebRIM** — 차이는
  "ZIP에 담기"(XDM) vs "SOAP+MTOM으로 POST"(ITI-41).
- **신규**:
  1. **SOAP/ebXML 엔벨로프 + MTOM/XOP 멀티파트** 빌더 (KOS를 바이너리 첨부).
  2. **제출 클라이언트** (`services/xdsi_submit.py`): 엔드포인트 URL·TLS 상호인증(상대 규약)·응답 파싱
     (RegistryResponse Success/Failure).
  3. **환자ID = affinity domain 식별자**: §2 MPI에서 로컬 study의 PatientID → affinity 도메인 ID 변환
     (미매칭 시 제출 거부 — Source는 도메인 ID 필수).
  4. **submission 이력 테이블** `xdsi_submissions`(study_uid, target_domain, status, registry_response,
     submitted_at) — 감사·재시도.

### 3.3 자체 검증 (모의 Repository)
- **모의 Repository 스텁**(`scripts/server/mock-xds-repository`): ITI-41 POST 수신 → ebRIM 파싱 →
  RegistryResponse(Success) 반환. **프로덕션 아님, 자체검증 전용.**
- E2E: 실 study → KOS 생성 → MPI로 affinity ID 매핑 → ITI-41 POST → 모의 Repo가 SubmissionSet/
  DocumentEntry 구조 검증 후 Success → `xdsi_submissions` status=SUBMITTED 기록.
- **구조적 최소적합만 주장**(v12.2와 동일 톤) — Gazelle 인증은 A4·별도.

---

## 4. DB 스키마 델타 (부팅 마이그레이션 러너 `core/schema_migrations`)
신규 테이블 4: `identity_domains`, `mpi_patients`, `patient_identifiers`, `xdsi_submissions`.
기존 `patient_mappings` 백필 1회(로컬 도메인 식별자 흡수). **모두 additive** — 단일기관 운영 무영향.

---

## 5. API 표면 (신규 `/api/v1/pix/*`, `/api/v1/xds-i/*`)
| EP | 트랜잭션 | 역할게이트 |
|---|---|---|
| `GET /pix/Patient/$ihe-pix` | ITI-83 PIXm Query | 인증(read) |
| `POST /pix/domains` · `GET /pix/domains` | 도메인 관리 | ADMIN, `allow_btg=False` |
| `POST /pix/patients/{id}/identifiers` | MPI 교차참조 등록 | ADMIN/TECH, `allow_btg=False` |
| `POST /xds-i/submit` | ITI-41 제출 트리거(study→affinity) | ADMIN/RAD, **외부반출→`allow_btg=False`** |
| `GET /xds-i/submissions` | 제출 이력 | ADMIN/RAD |
| (MLLP) PIX Feed/Query ITI-8/9 | HL7v2 | 네트워크 노드 신뢰 |

> ITI-41 제출은 **외부 반출**이므로 감사(v13.6 패턴)·`allow_btg=False` 필수.

---

## 6. 착수 순서 (게이트 인지)

```
Step 1 [구현 가능]  A2 MPI 데이터모델 + 부팅 마이그레이션 + patient_mappings 백필
Step 2 [구현 가능]  PIXm $ihe-pix 조회 EP + 모의 도메인 시드 + E2E(교차참조)
Step 3 [구현 가능]  ITI-41 SOAP/MTOM 엔벨로프 빌더(xds_metadata·KOS 재사용) + xdsi_submissions
Step 4 [구현 가능]  모의 Repository 스텁 + ITI-41 자체검증 E2E(study→제출→Success)
Step 5 ✅완료      PIX v2(ITI-8/9) MLLP — pix_hl7.py, 서버 E2E PASS (2026-07-08 선제 구현)
Step 6 [게이트]     실 affinity domain 확정 → 엔드포인트·OID·TLS 규약 교체 → 라이브 제출·Gazelle
```

**Step 1~4는 모의 도메인으로 완결 가능** — 실 대상 없이 구조 구현·자체검증까지. **Step 6만 외부 게이트.**

### 구현 산출물 (2026-07-08, Step 1~4)
- **Step 1**: `models/mpi.py`(IdentityDomain·MpiPatient·PatientIdentifier·XdsiSubmission + `_DDL`),
  `core/schema_migrations`에 수집 등록, 로컬 도메인(`OPENPACS`) 멱등 시드. 백필은
  `POST /pix/admin/backfill-local`(멱등, patient_mappings→로컬 식별자 흡수).
- **Step 2**: `api/pix.py` — 도메인 CRUD, MPI 환자/식별자 교차참조, **PIXm `$ihe-pix`(ITI-83)** 질의.
  RBAC: 관리=ADMIN·쓰기=ADMIN/TECH·질의=ADMIN/RAD/TECH(RESEARCHER 제외), 모두 `allow_btg=False`.
- **Step 3**: `services/xdsi_submit.py` — **ITI-41 SOAP1.2+MTOM/XOP 빌더**(stdlib만, `xds_metadata`
  ebRIM·`kos_service` KOS 재사용) + `parse_registry_response` + httpx `submit`. `api/xds_i.py` —
  `POST /xds-i/submit`(default-off `XDSI_SUBMIT_ENABLED` 게이트, `allow_btg=False`, MPI로 affinity ID
  유도, 감사) + 이력 EP. config: `xdsi_submit_enabled`·`xdsi_repository_endpoint`·`xdsi_source_oid`.
- **Step 4**: `scripts/server/mock_xds_repository.py`(stdlib http.server, ITI-41 구조검증→Success/Failure) +
  `scripts/server/it-xdsi-pix.sh`(서버 E2E: 도메인 시드→교차참조→PIXm→합성 study→제출→SUBMITTED 검증).
- **로컬 검증(deps 무): ITI-41 빌더 순수 테스트 5/5 통과** — MTOM 구조, RegistryResponse 파싱,
  CX 포맷, mock repo end-to-end(Success), 음성 케이스(Failure).
- **Step 5 ✅ (2026-07-08 선제 구현)**: `services/pix_hl7.py`(ITI-9 QBP^Q23→RSP^K23, ITI-8 ADT Feed,
  A40 Merge) + hl7_listener 디스패치. 서버 E2E `scripts/server/it-pix-hl7.sh` 전부 PASS(피드→질의→
  affinity id 반환·NF·단일 엔터프라이즈 교차참조). hl7-listener 컨테이너 재빌드 배포.
- **잔여**: Step 6(실 affinity domain — 외부 게이트)만.

---

## 7. 진입 전 사용자/사업 결정 (v2.0-scope §3 재확인)
1. **affinity domain 운영 주체**: 지역/국가 영상교류(건강정보 고속도로) vs 기관 컨소시엄 vs WeRU.B 중앙 —
   OID 발급·환자ID 규약이 여기서 결정됨. **Step 6 게이트.**
2. **PIXm vs PIX v2 우선**: 상대 도메인이 FHIR 지원하면 PIXm만으로 충분(Step 5 생략).
3. **멀티테넌시(B1)와의 순서**: MPI는 단일 인스턴스에서도 유효하나, 멀티사이트 페더레이션(B4)엔 B1 선행 필요.
4. **본 Phase를 "지금 구현"할지 "설계만"할지**: Step 1~4는 실 대상 없이도 자산이 되나(EMR I002 갭 부분해소·
   구조 준비), 실 가동은 Step 6 대기. **선투자 판단.**

---

## 8. 리스크 / 교훈 반영
- **"연동≠생성"**(v12.2): 모의 도메인으로 생성·구조검증은 하되, **"Gazelle 인증"이라 주장 금지**.
- **enum NAME 함정**(세션 4회): 신규 status 컬럼(submission status)은 raw SQL 대문자.
- **PHI 최소화**: MPI demographics는 대조검증 최소치만(이름/성별/생년), 감사 스코프.
- **드리프트**: 서버↔repo — 신규 파일이라 드리프트 없음. 배포 시 shasum 대조.
- **외부반출 게이트**: ITI-41 = PHI 외부 전송 → default-off 활성 플래그(`XDSI_SUBMIT_ENABLED`) 권장
  (patient-export v11.8 패턴), 실 도메인 규약 확정 전 비활성.
</content>
</invoke>
