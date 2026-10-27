# WeRU.B PACS 설치·설정 준비 기획서

> 작성 2026-06-16 · 목표: **개발용 단일 서버 → 신규 의료기관에 깨끗하게 설치 가능한 제품 상태**
> 범위 제외(별도 준비): 고가용성(HA)·재해복구 운영·규제 인증·오프사이트 스토리지·의료망 분리.
> 이 문서는 “한 대의 온프레미스 서버(클리닉/중소병원)에 처음부터 설치·구동”에 필요한 준비 작업을 다룬다.

---

## 1. 현황 진단 (설치 관점)

| 구분 | 항목 | 상태 |
|------|------|:----:|
| 설정 | `core/config.py` 환경변수 기반(pydantic Settings) | ✅ |
| 설정 | `.env.example` (PG/Redis/Orthanc/SSO/AI/포트/Keycloak 31항목) | ✅ |
| 설정 | `docker-compose.yml` `${VAR}` 변수화(시크릿 인라인 없음) | ✅ |
| 백업 | `scripts/server/backup-openpacs.sh` · `restore-openpacs.sh` | ✅ |
| 표준 | `docs/dicom-conformance-statement.md` · `xds-i-conformance.md` | ✅ |
| 보안 | PBKDF2·fail-closed·RBAC·세션타임아웃·보안헤더·non-root | ✅ |
| 설정 | **Orthanc 자격증명 하드코딩** — `retake_request.py:117,121` `("admin","ORTHANC_PASSWORD 로 정한 값")`, `normalization_settings.py:133`, `storage_commitment_service.py:28`(env+하드코딩 fallback) | ⚠️ |
| 설정 | **AE Title `OPENPACS` 하드코딩**(followups·provenance·dicom_remotes·mwl_scp·dicom_ai_standard 등 5+파일) — 기관별 변경 불가 | ⚠️ |
| 설정 | **도메인 기본값**(`his.example.org`·`example.org`)이 config 기본값·`.env.example`에 잔존(prefetch_warm_base_url·sign_portal_base_url·ai_server_url) | ⚠️ |
| 설치 | **원클릭 설치 스크립트 없음** — 현재 수동 scp 배포(서버≠repo 드리프트 빈발) | ❌ |
| 설치 | **초기 설정/시드 없음** — 관리자 계정·기관정보·모달리티·AE 노드 수동 | ❌ |
| 설치 | **전제조건 점검 스크립트 없음**(OS/Docker/포트/디스크/TLS) | ❌ |
| 설치 | **설치 후 검증(smoke) 자동화** 별도 정리 안 됨(E2E는 있음) | ⚠️ |
| 설치 | repo compose(Keycloak/Grafana 포함 standalone) ↔ 서버 compose(HospitalRun 공존 split) **2종 분기** | ⚠️ |

**결론**: 토대(env 설정·compose·보안)는 양호. 부족한 건 ① 잔여 하드코딩 제거 ② 설치 자동화(스크립트·시드) ③ 전제조건·검증 ④ 설치 문서.

---

## 2. 준비 작업 — Phase 구성

### Phase 1. 설정 외부화 완성 (코드)  〔필수·선행〕
신규 기관 값으로 100% 구성 가능하게 잔여 하드코딩 제거.

- **1-1 Orthanc 접속 일원화** — `retake_request.py`·`normalization_settings.py`·`storage_commitment_service.py`의 인라인 `("admin","ORTHANC_PASSWORD 로 정한 값")`·`http://orthanc:8042`를 `settings.orthanc_url` / `settings.orthanc_username` / `settings.orthanc_password`로 교체. (이미 `orthanc_uploader.py`는 외부화됨 — 동일 패턴 적용)
- **1-2 AE Title 설정화** — `settings.orthanc_aet = "OPENPACS"`(env `ORTHANC_AET`) 신설 → 하드코딩 `"OPENPACS"` 5+곳을 `settings.orthanc_aet`로. MWL/StgCmt/Q-R/provenance 영향 검토.
- **1-3 기관 메타 설정** — `institution_name`·`institution_id`·`timezone`·`base_url`(공개 도메인) env 신설. DICOM 태그(InstitutionName)·리포트·프리페치/sign 도메인에 사용. `prefetch_warm_base_url`/`sign_portal_base_url` 기본값을 `base_url` 파생으로.
- **1-4 `.env.example` 보강** — 누락 항목 추가(`ORTHANC_AET`·`INSTITUTION_*`·`BASE_URL`·`PREFETCH_WARM_BASE_URL`·`SIGN_PORTAL_BASE_URL`·`PATIENT_EXPORT_SECRET`·`ATNA_*`), 모든 비밀은 `CHANGE_ME`로. 섹션별 주석.
- 산출물: 위 파일 변경 + 갱신된 `.env.example`. **하드코딩 기관값 0 검증**(grep 게이트).

### Phase 2. 설치 패키징 (스크립트)  〔필수〕
한 대 서버에 재현 가능 설치.

- **2-1 단일 설치 compose 확정** — 신규 기관용은 standalone(`docker-compose.yml`, 자체 PG/Redis/Orthanc/뷰어/admin/모니터링). HospitalRun 공존(split)은 “기존 인프라 연동” 부록으로 분리. 어느 쪽이 정본인지 명시.
- **2-2 `install.sh`(설치 마법사)** — ① 전제조건 점검 호출 ② `.env` 생성(시크릿 자동 생성: `openssl rand`로 `SECRET_KEY`/패스워드) ③ `docker compose pull/build` ④ DB 초기화(스키마는 startup 마이그레이션 러너가 처리) ⑤ 첫 관리자 계정 생성 ⑥ smoke 검증 호출. 멱등 재실행 가능.
- **2-3 시크릿 생성 표준화** — 평문 기본값 금지. 설치 시 무작위 생성 후 `.env`에만 저장(레포·로그 미기록).
- 산출물: `scripts/install/install.sh`·`gen-secrets.sh`·표준 `docker-compose.yml`(+`.override` 예시).

### Phase 3. 초기 설정·시드 (부팅 1회)  〔필수〕
빈 시스템을 진료 가능 상태로.

- **3-1 부트스트랩 시드** — 관리자 계정(설치 시 입력), 기관정보, 기본 역할, 기본 판독 템플릿(모달리티별), DICOM 검증 규칙(24규칙 seed — 이미 `seed.py` 존재), SLA 기본 임계.
- **3-2 모달리티·AE 등록 가이드** — 장비(AE Title/IP)·외부 PACS 노드 등록 절차(관리자 UI `외부연동`). C-STORE 수신 AE 화이트리스트 설정(보안).
- **3-3 HIS/RIS 연동 설정**(선택) — SSO 시크릿/JWKS, 오더 동기화 파라미터. 미연동 시 standalone로 가동.
- 산출물: `scripts/install/seed_institution.py`(멱등) + 설정 체크리스트.

### Phase 4. 전제조건·인프라 점검  〔필수〕
- **4-1 `preflight.sh`** — OS/커널, Docker·compose 버전, CPU/RAM/디스크 여유, 포트 충돌(80/443/8042/4242/5432/6379…), 시간동기(NTP), 로케일/타임존, TLS 인증서 존재.
- **4-2 스토리지 계획** — DICOM 저장 경로·예상 용량(검사량×보존 5년)·디스크 분리 권고. (계층화/콜드스토리지는 운영 별도)
- **4-3 네트워크/포트 매트릭스** — 외부 노출(443만) vs 내부 바인딩(127.0.0.1) 표. DICOM 4242는 장비망에서만.
- 산출물: `scripts/install/preflight.sh` + `docs/deployment/prerequisites.md`(포트/리소스/TLS 표).

### Phase 5. 설치 후 검증 (smoke)  〔필수〕
- **5-1 `verify-install.sh`** — health 200, DICOMweb 응답, 테스트 DICOM C-STORE→수신→뷰어 표시→판독 1건→감사로그 기록까지 종단 점검. 기존 E2E(`e2e/`) 일부 재사용.
- **5-2 적합성 자가점검** — Conformance Statement 대비 핵심 서비스(C-ECHO/STORE/FIND/MOVE·MWL·DICOMweb) 응답 확인.
- 산출물: `scripts/install/verify-install.sh` + 설치 합격 기준.

### Phase 6. 설치·운영 문서  〔필수〕
- **6-1 설치 가이드**(`docs/deployment/install-guide.md`) — 전제조건→install.sh→초기설정→검증, 스크린샷/명령 포함.
- **6-2 관리자 런북** — 백업/복구(스크립트 가동), 로그/모니터링(Grafana), 사용자/역할, 트러블슈팅.
- **6-3 인수인계 체크리스트** — 시크릿 전달·도메인/TLS·장비 AE·HIS 연동·교육(사용 설명서 `/pacs-admin/manual.html` 연계).

---

## 3. 설치 체크리스트 (요약)

```
[ ] 전제조건: Docker/compose, 포트 가용, 디스크, TLS 인증서, NTP
[ ] .env 생성: 모든 CHANGE_ME 치환, 시크릿 무작위 생성
[ ] 기관 설정: INSTITUTION_NAME, BASE_URL(도메인), ORTHANC_AET
[ ] docker compose up: 전 컨테이너 healthy
[ ] startup 마이그레이션: 스키마 생성 확인
[ ] 첫 관리자 계정 생성·로그인
[ ] 모달리티/외부 PACS AE 등록 + C-STORE 화이트리스트
[ ] HIS/RIS 연동(해당 시) 또는 standalone 확정
[ ] 검증: 테스트 DICOM 종단 통과(수신→판독→감사)
[ ] 백업 cron 가동(운영 인계) · 모니터링 확인
[ ] 사용 설명서 안내 · 사용자 교육
```

---

## 4. 우선순위·산출물 매핑

| 순위 | Phase | 핵심 산출물 | 성격 |
|:---:|------|------|------|
| 1 | P1 설정 외부화 | 하드코딩 제거 + `.env.example` | 코드(내가 가능) |
| 2 | P4 전제조건 | `preflight.sh`·prerequisites.md | 스크립트/문서 |
| 3 | P2 설치 패키징 | `install.sh`·`gen-secrets.sh`·정본 compose | 스크립트 |
| 4 | P3 초기 시드 | `seed_institution.py` | 코드/스크립트 |
| 5 | P5 검증 | `verify-install.sh` | 스크립트 |
| 6 | P6 문서 | install-guide·런북 | 문서 |

**착수 권고**: Phase 1(설정 외부화)부터. 잔여 하드코딩이 남으면 어떤 설치 자동화도 기관값으로 깨끗이 구성되지 않으므로 선행 필수.

## 5. 주의·리스크
- **시크릿**: 평문 기본값(`ORTHANC_PASSWORD` 로 정한 값 등) 설치 산출물·레포 잔존 금지 — 설치 시 생성·`.env`에만.
- **compose 2종 분기**: 정본을 standalone로 확정하지 않으면 설치/유지보수 혼란. 서버 드리프트 교훈([[server-drift]]) 반복 방지 — 설치는 정본 compose 1종.
- **AE Title 변경 영향**: MWL/StgCmt/Q-R/타 시스템 등록과 맞물림 — 1-2는 회귀 테스트 동반.
- **타임존/로케일**: 한국 기관은 Asia/Seoul·ko_KR — TAT/SLA/리포트 시각 정확성에 영향.
