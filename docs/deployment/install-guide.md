# WeRU.B PACS 설치 가이드

> 신규 의료기관 1대 온프레미스 서버 설치. 전제조건은 `prerequisites.md`,
> 전체 준비 기획은 `install-preparation-plan.md` 참고.
> 실운영(HA·재해복구·규제 인증·오프사이트)은 별도 준비.

## 0. 준비물
- Linux x86_64 서버(Docker Engine 24+, Compose v2), 공개 도메인 + TLS 인증서
- 소스(이 저장소)를 서버에 클론/복사

## 1. 전제조건 점검
```bash
bash scripts/install/preflight.sh
```
- FAIL이 없어야 진행. WARN은 검토(운영은 해소 권장).
- 임계치/저장경로 조정: `MIN_RAM_GB=16 DICOM_PATH=/data/dicom bash scripts/install/preflight.sh`

## 2. 원커맨드 설치
```bash
bash scripts/install/install.sh
```
순서대로 자동 수행:
1. 전제조건 점검
2. `.env` 생성(시크릿 자동 — `gen-secrets.sh`) + 기관명·도메인 입력
3. 이미지 빌드 → 4. 서비스 기동(스키마는 부팅 시 자동 마이그레이션)
5. 백엔드 헬스 대기 → 6. 첫 관리자 생성(**출력된 비밀번호 안전 보관**) + 기본값 시드 + 검증(smoke)

> 비대화식/CI: `ADMIN_PASSWORD=… SKIP_PREFLIGHT=1 bash scripts/install/install.sh`

## 3. 수동 설치(스크립트 없이)
```bash
bash scripts/install/gen-secrets.sh           # .env 생성
# .env에서 INSTITUTION_NAME / BASE_URL / (선택) AI_API_KEY 설정
docker compose build && docker compose up -d
docker compose exec -T -e ADMIN_PASSWORD='<12자+>' backend \
  python -m app.scripts.create_admin --username admin --email admin@hospital.example.org
docker compose exec -T backend python -m app.scripts.seed_institution
bash scripts/install/verify-install.sh
```

## 4. TLS / 도메인
- 인증서를 `docker/nginx/certs/`(fullchain.pem·privkey.pem)에 배치
- `docker/nginx/templates/default.conf.template`의 HTTPS 서버 블록 활성화 후 `docker compose restart nginx`
- 인증서 자동 갱신(certbot) 권장

## 5. 모달리티 / 외부 PACS 연동
- 관리자 → **외부연동**에서 외부 PACS 노드(AE Title/IP/Port) 등록
- 장비에서 C-STORE 수신: `.env`의 `DICOM_BIND=0.0.0.0`(또는 LAN IP)로 변경 → `docker compose up -d`,
  장비망 방화벽만 허용. 상세: `cstore-pilot-readiness.md`
- 우리 AE Title은 `.env`의 `ORTHANC_AET`(기본 OPENPACS)

### 5.1 DICOM TLS (옵션 — 모달리티망 DIMSE 암호화)
평문 DIMSE(4242) 대신 TLS로 암호화하려는 경우. **모든 모달리티가 DICOM TLS를 지원할 때만** 활성화
(활성 시 4242는 TLS 전용 → 비TLS 장비는 접속 불가). 기본 비활성.
```bash
# 1) 인증서 생성 (Orthanc 호스트명 또는 LAN IP)
bash scripts/install/gen-dicom-tls.sh pacs.clinic.local        # → docker/orthanc/tls/{ca,server-*}.pem
# 2) .env 활성화
#    ORTHANC_DICOM_TLS_ENABLED=true
#    (상호 TLS 원하면 ORTHANC_DICOM_TLS_MUTUAL=true + 모달리티마다 --client 발급)
docker compose up -d orthanc
# 3) 검증 (격리 컨테이너로 TLS C-ECHO 3종)
bash scripts/install/it-dicom-tls.sh
```
- 모달리티에는 `docker/orthanc/tls/ca-cert.pem`(내부 CA)을 신뢰 등록. 상호 TLS면 클라이언트 인증서도 설치.
- 인증서/키는 커밋 금지(`.gitignore` 처리). 재발급: `gen-dicom-tls.sh ... --force`.

## 6. 모니터링(선택)
```bash
docker compose --profile monitoring up -d     # prometheus / grafana / node-exporter
```

## 7. 접속
- 관리자 콘솔: `https://<도메인>/pacs-admin`  (생성한 관리자 계정)
- 뷰어: `https://<도메인>/werub-viewer`
- 사용 설명서: 콘솔 상단 **📖 매뉴얼**

---

# 관리자 런북(운영)

## 시작/정지/상태
```bash
docker compose ps                 # 상태
docker compose logs -f backend    # 로그
docker compose restart backend    # 재시작
docker compose --profile monitoring up -d   # 모니터링 포함 기동
```

## 코드/설정 변경 반영
- backend는 `./backend/app` 볼륨 마운트 → `docker compose restart backend`
- celery·mwl-scp·hl7-listener·admin·werub는 빌드 베이크 → `docker compose build <svc> && docker compose up -d <svc>`
- nginx 라우팅 변경 → 템플릿 수정 후 `docker compose restart nginx`

## 백업 / 복구
```bash
# 정기 백업 cron(운영 인계 — root crontab)
30 3 * * * /path/to/scripts/server/backup-openpacs.sh >> /var/log/openpacs-backup.log 2>&1
# 복구 리허설
bash scripts/server/restore-openpacs.sh <백업파일>
```
> 오프사이트 복제·immutable 백업은 운영 별도 준비.

## 사용자 / 역할
- 관리자 → **사용자**에서 계정·역할 부여(판독의/방사선사/임상의/연구자)
- HIS SSO 사용 시 최초 로그인에 자동 프로비저닝(JIT)

## 점검 / 검증
```bash
bash scripts/install/verify-install.sh    # 컨테이너·웹·DIMSE 종단 점검
curl -sk https://<도메인>/pacs-api/health
```

## 트러블슈팅
| 증상 | 확인 |
|------|------|
| 컨테이너 미기동 | `docker compose ps` / `logs <svc>` |
| 뷰어 영상 안 열림 | DICOMweb `/dicom-web/studies` 200? `ORTHANC_BASIC_AUTH` 정확? 비표준 영상은 DICOM 이슈/정규화 |
| 장비 C-STORE 안 됨 | `DICOM_BIND`·방화벽·장비 AE 등록 / C-ECHO 검증 |
| 로그인 안 됨 | 관리자 계정 재생성: `create_admin`(멱등, 비번 미변경 → 새 username으로 생성) |
| 스키마 누락 | backend 로그의 startup 마이그레이션 / `docker compose restart backend` |
