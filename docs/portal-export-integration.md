# 환자 결과 추출 연동 규약 (외부 환자포털 → PACS)

**대상**: 외부 환자포털 개발자
**버전**: 1.0 (2026-06-12, v11.7)
**전제**: 포털이 **환자 본인확인을 완료**한 뒤 서버-서버로 호출. 환자 브라우저는 PACS에 직접 접근하지 않는다.

---

## 1. 데이터 흐름

```
환자 → [포털] ──①요청──▶ [PACS /api/v1/patient-export/requests]
            ──②폴링──▶ [PACS .../requests/{id}]  (ready 시 download_token + package_key)
            ──③수령──▶ [PACS /portal-export/{download_token}]  (1회용)
       복호(package_key) → 환자에게 표시
```

- 패키지(암호화 바이트)는 ③경로로, **복호 키는 ②(인증된 상태조회)로만** 전달된다.
  다운로드 토큰이 유출돼도 키가 없으면 내용 열람 불가.

## 2. 인증 — 서비스 토큰 (JWT HS256)

PACS와 **공유한 시크릿**으로 서명. 클레임:

| 클레임 | 필수 | 값 |
|--------|:---:|-----|
| `scope` | ✅ | `"patient-export"` (고정) |
| `mrn` | ✅ | 본인확인된 환자번호 (= DICOM PatientID) |
| `exp` | ✅ | 만료(짧게, 예: 10분) |
| `iss` | 권장 | 포털 식별자 |

- **토큰의 `mrn`은 요청·조회의 환자와 일치해야 함** — 불일치 시 403. 한 환자 토큰으로 다른
  환자 데이터를 추출할 수 없다.
- 시크릿은 **export 전용**(`PATIENT_EXPORT_SECRET` ↔ 포털 `pacs.exportSecret`, 동일 값) — SSO와 분리,
  합의는 PACS↔포털 2자. 운영자가 양측 직접 주입(레포/compose 금지). **로그에 토큰·시크릿·키 금지.**
- **베이스 URL**: 요청·폴링은 `/api/v1/patient-export/...`, **수령은 `/portal-export/{token}`(루트, `/api/v1` 없음)**.
  동일 호스트 포털은 루프백 `http://127.0.0.1:8000` 하나로 3개 모두 호출.

```python
import jwt, time   # PyJWT 또는 python-jose
token = jwt.encode({"scope":"patient-export","mrn":"P2026-0006",
                    "iss":"patient-portal","exp":int(time.time())+600}, SECRET, "HS256")
```

## 3. API

### ① 추출 요청
```
POST {PACS}/pacs-api/api/v1/patient-export/requests
Authorization: Bearer <service-token>
{ "mrn": "P2026-0006", "study_instance_uids": ["..."]?, "purpose": "patient_view" }
→ 202 { "request_id": "...", "status": "processing" }
```
- `study_instance_uids` 생략 시 해당 환자 **전체 study**.
- `purpose`: 감사용 목적 코드(예: patient_view, second_opinion).

### ② 상태/키 조회 (폴링: 2초 간격, 5분 타임아웃 권장)
```
GET {PACS}/pacs-api/api/v1/patient-export/requests/{request_id}
Authorization: Bearer <service-token>   # mrn 일치 필수
→ { "status": "processing|ready|failed|expired",
    "study_count": 2, "package_bytes": 488460, "expires_at": "...",
    "download_token": "...",   # ready일 때만
    "package_key": "..." }     # ready일 때만 (Fernet 키)
```

### ③ 패키지 수령 (1회용)
```
GET {PACS}/portal-export/{download_token}     # JWT 아님, 토큰만
→ 200 application/octet-stream  (Fernet 암호문)
→ 410  (이미 사용됨/만료 — 재요청 불가)
```

## 4. 패키지 구조 (복호 후)

Fernet 복호 → ZIP:
```
manifest.json                       # mrn, purpose, generated_at, studies[]
studies/<uid>/dicom.zip             # study별 DICOM 원본
studies/<uid>/report.html           # final 판독문(있을 때만)
```
```python
from cryptography.fernet import Fernet
import io, zipfile
plain = Fernet(package_key.encode()).decrypt(encrypted_bytes)
zf = zipfile.ZipFile(io.BytesIO(plain))
manifest = zf.read("manifest.json")
```
(Node: `fernet` npm 또는 동등 구현)

## 5. 수명·보안

- 다운로드 토큰/키 TTL: **1시간**. PACS 스테이징 패키지: 24시간 후 자동 삭제.
- 포털은 수령 후 **자체 정책으로 보관·만료** 관리(PACS는 재발급만 가능 — 새 요청).
- 전송 전 구간 TLS. 포털 보관 시에도 암호화 권장. 환자 열람 종료 후 삭제 권장.
- PACS는 요청/수령을 감사기록(`PATIENT_EXPORT_REQUESTED/DOWNLOADED`).
- 운영 시 PACS nginx `/portal-export/`에 포털 egress IP 허용목록 추가 권장.

## 6. 오류 코드

| 코드 | 의미 |
|------|------|
| 401 | 서비스 토큰 없음 |
| 403 | scope 불일치 / mrn 봉인 위반 / 시그니처 오류 |
| 404 | request_id 없음 |
| 410 | 다운로드 토큰 사용됨·만료 |
| 503 | `EXPORT_DISABLED` — 기능 비활성(운영자가 시크릿 합의 후 활성화 전까지 기본값) |
| status=failed | 추출 실패(`error` 필드: no_studies 등) |

> **활성화 상태**: PACS는 `patient_export_enabled`가 기본 **비활성**. 인증(401/403)은 항상 검사되며,
> 유효 토큰이라도 비활성이면 `POST /requests`가 503 `EXPORT_DISABLED`. 활성화 절차는
> `docs/portal-export-pacs-reply.md` §3 참조.

## 7. 참고

- 본인 제공(개인정보보호법) — 익명화 없는 원본 DICOM + final 판독문만 포함(preliminary 제외).
- 검증 하니스: `scripts/patient_export_test.py` (요청→수령→복호 전 과정).
