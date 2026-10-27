# 경쟁력 갭 해소 — 실제 구현 기획서

**작성일**: 2026-06-06
**근거**: `docs/03-analysis/pacs-commercial-comparison.md` (상용 대비 갭 분석)
**목표**: 상용 PACS 대비 식별된 갭 중 **실제 구현 가능·고가치** 항목을 단계적으로 구현해 경쟁력 확보

---

## 1. 갭 우선순위 (구현 관점)

비교표의 갭을 **임상가치 × 구현가능성**으로 우선순위화:

| 갭 | 임상가치 | 구현난이도 | 외부의존 | 우선 |
|---|:---:|:---:|---|:---:|
| **MWL SCP**(촬영실 워크리스트) | ★★★ | 중 | 없음(Orthanc 플러그인) | **P1** |
| **3D 임상 튜닝**(전용 HP·VR 프리셋) | ★★ | 중 | 없음 | **P2** |
| MPPS(촬영 상태 추적) | ★★ | 중 | 모달리티 지원 | P3 |
| ~~Storage Commitment~~ | ★★ | 중 | — | ✅ **완료(2026-06-06)** — pynetdicom N-ACTION/N-EVENT-REPORT, mwl-scp에 통합. Orthanc 존재확인 후 committed/failed 응답 (검증 완료) |
| 음성인식(dictation) | ★★ | 중상 | 외부 STT API | P3 |
| 다중기관/VNA | ★★★ | 상 | 아키텍처 | v2.0 |
| 고급 3D(fusion·혈관분석) | ★★ | 상 | — | v2.0 |
| MFDS 인증 | ★★★ | — | 인증기관 | 별도 트랙 |

→ **본 기획서는 P1(MWL SCP)을 상세 설계**하고, P2(3D 임상 HP)를 개요로 다룬다.

---

## 2. P1 — Modality Worklist (MWL) SCP

### 2.1 배경·가치
현재 모달리티(CT/MR/CR 등)는 촬영 시 **환자 정보를 수기 입력** → 오타·환자 불일치·태그 오류 발생(본 제품의 비표준 검증이 사후 잡지만, **MWL은 사전 예방**). MWL SCP는 모달리티가 PACS에서 **예약된 검사 목록을 C-FIND로 조회** → 환자/검사 정보 자동 채움. 상용 PACS 표준 기능, 본 제품 미지원(현재 HIS API로 부분 대체).

### 2.2 설계 (Orthanc Worklist 플러그인 기반)
```
[HIS] --POST /api/v1/orders--> [worklist_items DB]
                                      │ (Celery sync, 1분)
                                      ▼
                          [.wl 파일 생성 (pydicom)]  →  /var/lib/orthanc/worklists/
                                      │
[CT/MR 모달리티] --C-FIND(MWL SOP 1.2.840.10008.5.1.4.31)--> [Orthanc Worklist 플러그인] → 매칭 응답
```

- **Orthanc**: `OrthancWorklists` 플러그인 활성화(`Worklists: { Enable: true, Database: "/worklists" }`). DICOM 디렉터리의 `.wl`(DICOM 데이터셋) 파일을 C-FIND 질의에 매칭·응답.
- **백엔드 서비스** `mwl_service.py`: 예약 상태 `worklist_items`(또는 scheduled orders)를 **MWL 데이터셋(.wl)** 으로 생성. pydicom으로 ScheduledProcedureStepSequence 등 필수 태그 작성:
  - PatientName/ID/BirthDate/Sex
  - AccessionNumber, StudyInstanceUID(사전생성)
  - ScheduledProcedureStepSequence: Modality, ScheduledStationAETitle, ScheduledProcedureStepStartDate/Time, ScheduledProcedureStepDescription
  - RequestedProcedureID/Description
- **동기화** `mwl_sync_task`(Celery beat 1분): 신규/변경 예약 → `.wl` 갱신, 완료/취소 → 제거.
- **Admin**: 예약 등록 화면(기존 워크리스트 활용) + MWL 상태(생성된 .wl 수, 매칭 로그).

### 2.3 작업 분해 (Tasks)
1. Orthanc Worklist 플러그인 활성화 + `/worklists` 볼륨 마운트 (docker-compose)
2. `mwl_service.build_worklist_file()` — 예약 → .wl (pydicom), 필수 태그 검증
3. `mwl_sync_task` — DB→.wl 동기화 (Celery beat)
4. 예약 API/Admin: ScheduledStationAET·StartDate 등 입력 필드 보강
5. MWL 모니터링: 생성 .wl 목록·매칭 통계
6. **검증**: DCMTK `findscu`로 MWL C-FIND 질의 → 응답 확인 (모달리티 에뮬레이션)

### 2.4 난이도·리스크
- 난이도: **중**. Orthanc 플러그인 문서화 양호, .wl 생성은 pydicom 표준.
- 리스크: **낮음**(기존 기능 무영향, 추가형). 단 모달리티 AET 사전 등록 필요(`docs/cstore-pilot-readiness.md` 연계).
- 의존: 없음(전부 self-contained).

### 2.5 완료 기준
- `findscu` MWL 질의에 예약 검사가 정확히 응답(환자/Accession/모달리티 매칭)
- 예약→촬영→C-STORE 시 AccessionNumber 일관(MWL의 UID 사전생성으로 study 연결)

### 2.6 배포 현실 — 플러그인 부재 (2026-06-06 발견)
**구현 코드는 완료**(`mwl_service.py` 데이터셋 빌더 + `mwl_sync_task.py` + beat 등록). 그러나 배포 시 블로커:
- **서버 Orthanc(env-var 설정)에 worklist 플러그인 없음** — `orthancteam/orthanc:latest-full`에도 `libModalityWorklists.so` 미포함 확인.
- 서버 Orthanc 설정은 `ORTHANC__*` 환경변수(compose), repo `orthanc.json` 미사용.

**두 가지 배포 경로 (인프라 결정 필요)**:
| 경로 | 방식 | 장점 | 단점/리스크 |
|---|---|---|---|
| **A. 커스텀 Orthanc 이미지** | `FROM orthancteam/orthanc` + worklist 플러그인(.so) 추가 + `ORTHANC__WORKLISTS__*` env + 공유볼륨. `.wl` 동기화 방식 그대로 | 표준 플러그인, Orthanc가 SCP 담당 | 코어 PACS 이미지 변경, 플러그인 빌드/획득, 공유볼륨 |
| **B. pynetdicom MWL SCP 서비스** | 별도 경량 컨테이너가 DICOM 포트(예 4243)에서 MWL C-FIND를 DB 직접 조회로 응답(`build_worklist_dataset` 재사용) | 코어 Orthanc 무변경, .wl파일·볼륨 불필요, DB 실시간 | 신규 서비스·포트·pynetdicom 의존, 모달리티가 별도 AET/포트 지정 |

> **권장: B(pynetdicom SCP)** — 코어 Orthanc를 건드리지 않고 격리된 신규 컨테이너로 추가. 단 신규 DICOM 서비스 추가는 운영 결정이라 승인 후 진행. 데이터셋 빌더는 이미 양쪽 공용으로 작성됨.

### 2.7 ✅ 구현·배포·검증 완료 (2026-06-06, 경로 B)
- **`app/services/mwl_scp.py`** — pynetdicom 3.0.4 MWL C-FIND SCP. `worklist_items`(status=SCHEDULED) DB 직접 조회, `build_worklist_dataset` 응답. 매칭: PatientID·AccessionNumber·Modality·ScheduledStationAETitle·StartDate(범위).
- **컨테이너** `mwl-scp` (compose, host network, backend 이미지, `python -m app.services.mwl_scp`) — AE=**OPENPACS-MWL**, 포트 **127.0.0.1:4243**.
- **검증**: MWL C-FIND SCU → 전체 3건(홍길동/CR, LIDC/CT, 홍길동/CT, **한글명 정상**), Modality=CT 필터 2건. StudyInstanceUID 포함(C-STORE 연결).
- **서버 변경**: compose에 mwl-scp 서비스 추가(백업 `docker-compose.yml.bak.20260606-mwl`), backend 이미지 재빌드(pynetdicom 3.0.4).
- **파일럿 노출**: 현재 127.0.0.1 바인딩(Orthanc 4242와 동일 보안 정책). 모달리티 연동 시 LAN 노출 + 모달리티에 MWL AE(OPENPACS-MWL:4243) 등록.
- **부수 발견**: 일부 테스트 데이터의 AccessionNumber가 23자(DICOM SH VR 16자 초과) — 검증엔진 대상 데이터 이슈.

---

## 3. P2 — 3D 임상 튜닝 (개요)

`docs/03-analysis/3d-pacs-capability-review.md` G2/G3 연계:
- **3D 전용 Hanging Protocol**: 흉부 CT(폐/종격동 창 + MPR+VR 자동 레이아웃), 복부 CT, 자동 모달리티 매칭.
- **한국형 VR transfer function 튜닝**: 폐/뼈/연부/혈관 프리셋의 불투명도·색상 곡선 임상 검증(현재는 라벨만 한국어).
- 난이도: 중. 뷰어 HP 작성 + VR 프리셋 정의 + 임상 검증.

---

## 4. 로드맵·단계

| 단계 | 내용 | 산출물 |
|---|---|---|
| **1차** | P1 MWL SCP 구현·검증 | mwl_service, sync task, Orthanc 설정, findscu 검증 |
| **2차** | P2 3D 전용 HP + VR 프리셋 튜닝 | 뷰어 HP, 한국형 VR 프리셋 |
| **3차** | ✅ **MPPS 구현 완료(2026-06-06)** — N-CREATE/N-SET SCP, 예약→진행→완료 루프 (검증 IN_PROGRESS→COMPLETED). Storage Commitment는 Orthanc 제약으로 보류 | mwl-scp 서비스에 통합 |
| **별도** | MFDS 인증 트랙 | 인증 문서(기존 24종 활용) |
| **v2.0** | 다중기관·VNA·고급 3D | 아키텍처 확장 |

> **권장 착수**: **P1 MWL SCP** — 외부 의존 없이 self-contained, 촬영실 워크플로 표준화로 즉각적 임상 가치, 본 제품의 비표준 검증(사후)과 **MWL(사전 예방)이 상호 보완**.

---

## 5. PDCA 연계
- Plan: 본 문서
- Design: P1 MWL 상세 설계(.wl 태그 스키마, Orthanc 설정, sync 주기)
- Do: mwl_service + sync + Orthanc 설정
- Check: findscu 검증 + gap 분석
- Act/Report: 완료 보고
