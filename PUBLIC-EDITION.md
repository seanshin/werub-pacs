# PACS — 공개판 안내

**PACS — about this public edition**

> **EN** — This repository is the public edition of PACS v13.48. Development continues in a private repository; this edition is its final state with internal working records (reports and replies exchanged with other systems, key-rotation runbooks, server measurements) and operational details removed, licensed under MIT. Operational domains, server addresses and accounts were replaced with example values, and **every password, secret, token and key was emptied to `CHANGE_ME`** — you must set your own before running anything. The table below lists each emptied setting and where it appears.

이 저장소는 **PACS v13.48 의 공개판**입니다. 개발은 비공개 저장소에서 계속하고, 공개판은 그 최종 상태에서 다음을 빼거나 바꾼 것입니다(MIT).

| 무엇 | 어떻게 |
|---|---|
| 내부 작업 기록 | 다른 시스템과 주고받은 결함 보고 · 회신, 키 교체 런북, 서버 실측 등 197개 문서를 뺐습니다. 소스 주석이 빠진 문서를 가리키는 곳이 남아 있을 수 있습니다 |
| 운영 정보 | 운영 도메인 · 서버 주소 · 서버 계정을 예시 값(`example.org` · 문서용 IP 대역 · `deploy`)으로 바꿨습니다 |
| 🔴 비밀값 | 비밀번호 · 비밀 · 토큰 · 키 **22곳**을 `CHANGE_ME` 로 비웠습니다. **실행 전에 아래 값을 직접 정하십시오** |

## 직접 설정할 값

| 설정 이름 | 있는 곳 |
|---|---|
| `access_token` | `docs/01-plan/features/er-kiosk.plan.md` · `docs/api/dicom-ingestion-hub-api.md` · `docs/api/patient-portal-api.md` · `docs/regulatory/technical/TD-001-srs.md` |
| `AI_API_KEY` | `docs/04-ai/werub-ai-server-api-reference.md` |
| `AI_MEDICAL_KEY` | `docs/04-ai/werub-ai-server-api-reference.md` |
| `HOSPITALRUN_AUTH_SECRET` | `.env.example`(비어 있음) |
| `password` | `docs/regulatory/technical/TD-001-srs.md` |
| `PATIENT_EXPORT_SECRET` | `.env.example`(비어 있음) |
| `refresh_token` | `docs/01-plan/features/er-kiosk.plan.md` · `docs/03-integration/api-quick-reference.md` · `docs/api/dicom-ingestion-hub-api.md` · `docs/regulatory/technical/TD-001-srs.md` |
| `SIGN_SERVICE_API_KEY` | `.env.example`(비어 있음) |
| `token` | `docs/api/dicom-ingestion-hub-api.md` |
| 문서 · 예시 속 비밀번호 | `backend/alembic.ini` · `docs/02-design/features/backend.design.md` — 접속 문자열 · 예시 명령의 비밀번호를 `CHANGE_ME` 로 비웠습니다. 실제 값으로 바꿔 쓰십시오 |

- 같은 이름이 여러 곳에 있으면 **모두 같은 값**이어야 하는지(서로 맞물리는 연동 비밀) 확인하십시오.
- 값은 길고 무작위로 만드십시오(예: `openssl rand -base64 32`). 저장소에 다시 커밋하지 마십시오.

## 켜기 전에 기관이 정할 보안 설정

아래 기능은 공개판에서 **설정하지 않으면 안전한 쪽으로 멈추거나 꺼져 있습니다.** 기관의 운영 절차에 맞춰 직접 정하십시오.

| 설정 | 무엇을 정하나 |
|---|---|
| `ORTHANC_USERNAME · ORTHANC_PASSWORD` | 영상 서버(Orthanc) 계정. **직접 정하십시오** — 공개판의 예시 · 스크립트 기본값은 모두 비워 두었습니다. nginx 는 `ORTHANC_BASIC_AUTH` 로 이 값을 주입합니다. |
| `영상 경로 토큰 게이트` | `/dicom-web` · `/wado` 는 공개판에서 **127.0.0.1 외에는 모두 토큰을 요구**합니다(사설 대역 우회 없음). 프리페치 워커는 서비스 토큰으로 부릅니다. |
| `PATIENT_EXPORT_ENABLED · 상한` | 환자 결과 내보내기는 기본 꺼짐. 켜면 요청당 스터디 수(`PATIENT_EXPORT_MAX_STUDIES`, 기본 20) · 환자별 시간당 요청 수(`PATIENT_EXPORT_MAX_REQUESTS_PER_HOUR`, 기본 10) 상한이 걸리고, 끄면 상태 조회 · 수령도 막힙니다. 수령 경로(`/portal-export/`)를 바깥에 열 때는 **포털 서버 IP 만 허용**하십시오. |
| `동의서 본문(sign `PORTAL_DOC_PREVIEW=on`)` | 환자 동의서는 PDF 본문을 sign 에 올린 뒤에만 서명 링크를 냅니다. sign 쪽 문서 미리보기를 켜야 동의서 기능이 동작합니다. |
| `부하 시험` | `tests/load/` 는 대상 주소 · 계정을 환경 변수(`PACS_BASE_URL` 등)로 받습니다. 운영 시스템에 돌리지 마십시오. |

- 코드 안의 개발용 기본값은 운영에서 반드시 환경 변수로 덮어쓰십시오.
- 이 생태계 전체의 소개 · 구축 순서: [werub-his-ecosystem](https://github.com/seanshin/werub-his-ecosystem)
