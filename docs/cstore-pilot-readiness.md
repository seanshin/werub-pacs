# C-STORE 수신 파일럿 준비 가이드

**목적**: 실제 병원 모달리티(CT/CR/DX/US 등)에서 WeRU.B PACS(Orthanc)로 DICOM C-STORE(DIMSE) 직접 전송을 수신하기 위한 준비 절차.
**대상 독자**: 운영/배포 담당자
**관련**: [pilot-test-checklist.md](pilot-test-checklist.md) · [dicom-conformance-statement.md](dicom-conformance-statement.md)
**작성 기준**: 2026-06-05 (Orthanc 1.12.11 · AE 제목 `OPENPACS`)

---

## 0. 현재 상태 — 기본값은 C-STORE를 거부함 (의도된 보안 설정)

`docker/orthanc/orthanc.json` 및 `docker-compose.yml`의 v10.0 하드닝 기본값은
**외부 장비의 C-STORE를 차단**한다. 파일럿 시 아래 3개 게이트를 모달리티 정보에 맞춰 선택적으로 해제해야 한다.

| 게이트 | 위치 | 기본값 | 의미 |
|--------|------|--------|------|
| ① 저장 허용 정책 | `orthanc.json: DicomAlwaysAllowStore` | `false` | 등록되지 않은 AE의 저장 거부 |
| ② 허용 모달리티 목록 | `orthanc.json: DicomModalities` | `{}` (비어있음) | 화이트리스트 비어 있음 |
| ③ DICOM 포트 노출 | `docker-compose.yml` 포트 매핑 | `127.0.0.1:4242` | LAN 장비에서 접근 불가 |

> ⚠️ ②를 채우는 것이 ①을 `true`로 여는 것보다 **안전하다**. `DicomAlwaysAllowStore: true`는
> 모든 AE를 무조건 허용하므로 파일럿에서도 권장하지 않는다. 화이트리스트(②)를 우선 사용.

---

## 1. 모달리티 정보 수집 (사전)

전송할 장비마다 아래 4개 값을 확보한다 (장비 DICOM 설정 화면 또는 영상팀 문의).

- [ ] **Calling AE Title** (장비의 AET, 예: `CT_GE_01`)
- [ ] **장비 IP 주소** (병원 LAN, 예: `10.20.0.51`)
- [ ] **장비 포트** (C-MOVE 회신용; C-STORE 수신만이면 선택)
- [ ] WeRU.B 쪽 **Called AE Title = `OPENPACS`**, **Port = 4242** 를 장비에 등록

---

## 2. Orthanc 화이트리스트 등록 (게이트 ①②)

`docker/orthanc/orthanc.json`의 `DicomModalities`에 장비를 추가한다:

```jsonc
"DicomModalities": {
  "CT_GE_01": [ "CT_GE_01", "10.20.0.51", 104 ]
  // [AET, Host, Port]  — 장비마다 한 줄
},
```

`DicomModalities`에 등록된 AE는 `DicomAlwaysAllowStore`가 `false`여도 **C-STORE가 허용**된다.
따라서 ①은 `false` 유지(권장). 등록 후 Orthanc 재시작:

```bash
ssh deploy@198.51.100.73 -p 819 \
  "cd /home/deploy/hospital-run/infra/docker && docker compose restart orthanc"
```

> 서버의 실제 `orthanc.json` 경로/마운트는 운영 compose 기준이며, 리포의 placeholder 비밀번호
> (`changeme_*`)와 다른 실제 값이 적용되어 있어야 한다. 커밋된 파일은 템플릿일 뿐이다.

---

## 3. DICOM 포트 LAN 노출 (게이트 ③)

기본 매핑은 `127.0.0.1:${ORTHANC_DICOM_PORT}:4242`라 localhost 외부에서 닿지 않는다.
파일럿 동안 **해당 장비 IP에 한해** 4242를 열어야 한다. 두 가지 방식:

**방식 A (권장) — 호스트 방화벽으로 출발지 제한 + 포트 노출**
```yaml
# docker-compose.yml (orthanc.ports)
- "0.0.0.0:${ORTHANC_DICOM_PORT}:4242"   # 노출
```
```bash
# 그리고 OS 방화벽에서 장비 IP만 허용 (예시: ufw)
sudo ufw allow from 10.20.0.51 to any port 4242 proto tcp
sudo ufw deny 4242/tcp     # 그 외 전부 차단
```

**방식 B — 노출 없이 SSH 터널** (단일 워크스테이션 테스트용, Horos/OsiriX 등)
```bash
ssh -p 819 -L 4242:127.0.0.1:4242 deploy@198.51.100.73
# 로컬 127.0.0.1:4242 → 서버 Orthanc DIMSE
```

> ③은 보안 표면을 넓히므로 **파일럿 종료 후 원복**한다. 변경 시
> `docs/hospitalrun-pacs-separation.md`의 포트 정책과 충돌 없는지 확인.

---

## 4. 수신 검증

```bash
# 4-1. C-ECHO (연결 확인) — 장비 측 "DICOM Echo/Verification" 버튼 또는:
#       Orthanc는 DicomAlwaysAllowEcho=true 라 어떤 AE든 echo 성공해야 정상

# 4-2. 장비에서 테스트 영상 1건 C-STORE 전송 후, 수신 확인:
curl -sk https://his.example.org/pacs-api/api/v1/statistics   # (인증 필요) 검사 수 증가 확인
curl -sk https://his.example.org/dicom-web/studies            # 새 스터디 표시

# 4-3. 뷰어 확인
#       https://his.example.org/werub-viewer/ 에서 수신 스터디 렌더링
```

### 비표준 DICOM 자동 검증 (수신 직후)
- Celery beat가 5분 주기로 미검증 스터디를 자동 스캔(24 규칙, 15 자동수정).
- 수신 영상의 JPEG 밀도(DPI/DPM) vs Pixel Spacing 교차 검증 여부 확인 (측정 정확도 직결).
- 이슈 발생 시 `/pacs-admin/dicom-issues`에서 확인/수정.

---

## 5. 체크리스트 요약

- [ ] 1. 모달리티 4값 수집 (AET/IP/Port/Called-AE 등록)
- [ ] 2. `DicomModalities`에 장비 추가 + Orthanc 재시작 (게이트 ①②)
- [ ] 3. 4242 포트를 장비 IP에 한해 개방 (게이트 ③) — 방화벽 출발지 제한 필수
- [ ] 4. C-ECHO 성공 확인
- [ ] 5. 테스트 영상 1건 C-STORE → 통계/DICOMweb/뷰어 수신 확인
- [ ] 6. 비표준 검증 결과 확인 (`/pacs-admin/dicom-issues`)
- [ ] 7. 파일럿 종료 후 포트 노출 원복

---

## 부록: 코드 차원 준비 상태 (2026-06-05 기준)

수신 경로 자체(Orthanc DIMSE → PostgreSQL 인덱스 → DICOMweb → 뷰어/검증)는 구현 완료 상태이며,
파일럿 차단 요인은 **설정·네트워크**(위 3 게이트)에 국한된다. 외부 PACS Q/R(C-FIND/C-MOVE)은
`/pacs-admin/remotes`에서 관리하며, 피어 자격증명은 v10.0 이후 암호화 저장된다
(`app/core/crypto.py`).
