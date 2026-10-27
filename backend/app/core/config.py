from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "OpenPACS"
    debug: bool = False

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://127.0.0.1:6379/0"

    # Orthanc
    orthanc_url: str = "http://127.0.0.1:8042"
    orthanc_username: str = "admin"
    orthanc_password: str
    # Our DICOM Application Entity Title (institution-configurable). Must match
    # Orthanc's configured AET and how remote modalities/PACS address us — used
    # as the C-MOVE TargetAet and the MWL scheduled-station AE.
    orthanc_aet: str = "OPENPACS"

    # Institution identity (per-install). Used for display, DICOM tags
    # (InstitutionName), reports, and to derive public-facing URLs below.
    institution_name: str = "WeRU.B PACS"
    institution_id: str = "WERUB"          # short code (HL7 facility, provenance)
    timezone: str = "Asia/Seoul"           # TAT/SLA/report timestamps
    base_url: str = "https://his.example.org"  # public origin of this install

    # Security
    secret_key: str
    session_idle_timeout_minutes: int = 30  # Auto-logout after idle period
    password_min_length: int = 12  # Minimum password length

    # HIS SSO (HospitalRun)
    hospitalrun_auth_secret: str = ""  # Shared secret for HIS JWT verification (HS256)
    his_sso_enabled: bool = True       # Enable/disable HIS SSO
    his_jwt_issuer: str = ""           # Optional: validate JWT issuer claim (e.g. "hospitalrun")
    # Hospital common SSO JWKS endpoint (RS256). When set, OpenPACS accepts the
    # common-SSO tokens for login. Empty = HS256 shared-secret only (legacy).
    # e.g. https://his.example.org/api/v1/sign-integration/jwks
    his_jwks_url: str = ""
    # Expected aud for OpenPACS *login* tokens (e.g. "pacs"). Empty = skip aud check
    # (dev). Set this so a sign-scoped token (aud=sign) cannot be reused for PACS
    # login — tokens are audience-scoped (viewer=pacs/ohif, e-sign=sign).
    his_jwt_audience: str = ""
    # JWKS bounded stale: 갱신 실패 시 캐시를 이 시간까지만 신뢰(초). 짧은 blip은 stale로
    # SSO 유지, 초과(장기 다운)면 fail-closed(폐기키 무한 검증 방지). 기본 6시간.
    his_jwks_max_stale_seconds: int = 6 * 3600
    # HIS→PACS 기계간 inbound(/api/v1/his/* 파괴적 쓰기)용 서비스 인증. 기존엔 아무 PACS 사용자
    # JWT로 검사취소/환자명변조 가능했음(P3). default-off — HIS 연동 합의 시 키 주입+enable.
    his_inbound_enabled: bool = False
    his_inbound_api_key: str = ""        # X-API-Key (HIS 송신측과 2자 합의·서버 config만)
    # On-demand IMAGING order sync (admin-triggered, read-only). Empty = disabled.
    # e.g. postgresql+asyncpg://hospital:secret@127.0.0.1:5432/hospitalrun
    hospitalrun_db_url: str = ""
    # 배치 정규화 업로드 스풀 — backend(업로드 저장)와 celery-worker(읽기)가 별도 컨테이너라
    # 반드시 **공유 볼륨** 경로여야 함(기존엔 /tmp라 워커가 못 읽어 배치가 전부 실패). export-staging
    # 마운트(양 컨테이너 공유) 하위 재사용 — 전용 볼륨 추가 시 이 값만 교체.
    batch_spool_dir: str = "/app/export-staging/batch-spool"

    # Phase 5: AI Integration
    model_storage_path: str = "/models"
    celery_ai_concurrency: int = 2
    redis_model_cache_ttl: int = 300
    celery_ai_max_retries: int = 3

    # WeRU.B AI Server (원내 구축 서버 — arch-invariants 감사 v1.1에서 경계 확정)
    ai_server_url: str = "https://example.org/ollama"
    ai_api_key: str = ""
    ai_medical_key: str = ""
    # external_api 모델의 endpoint host 화이트리스트(콤마 구분, ai_server_url host와
    # localhost는 항상 허용). 추론 픽셀이 원외로 나가는 것을 등록/실행 양쪽에서 차단
    # (INV-PHI-03 유지 가드). 예: "ai2.hospital.local,10.0.0.5"
    ai_endpoint_allowlist: str = ""

    # Patient result export (patient-portal feature). OFF by default: the
    # endpoint extracts PHI and is only as safe as the shared secret, so it
    # stays disabled until an operator sets a real HOSPITALRUN_AUTH_SECRET and
    # flips this on. Auth (401/403) is still checked before this gate.
    patient_export_enabled: bool = False
    # Dedicated export signing secret (separate from HIS SSO). When set, the
    # portal↔PACS agreement is 2-party and SSO rotation has zero impact. Empty =
    # fall back to hospitalrun_auth_secret.
    patient_export_secret: str = ""
    # 공개판: 반출 상한 — 요청 한 건에 담는 스터디 수 · 환자(MRN)별 시간당 요청 수
    patient_export_max_studies: int = 20
    patient_export_max_requests_per_hour: int = 10

    # Patient result-VIEW portal (환자 본인 웹 열람 — /pacs-admin/patient-view).
    # PHI 읽기 표면이므로 default OFF (patient_export와 동형). 스태프 발급 토큰
    # (SHA-256 해시 저장·만료·폐기)으로만 접근.
    patient_view_enabled: bool = False

    # Outbound webhook PHI masking (arch-invariants INV-NET-01). Webhook 대상 URL은
    # 운영자 설정 임의 주소(외부 SaaS 가능)이므로 발송 페이로드의 환자명/환자ID를 마스킹.
    # 원내 알림센터(DB/WS)는 원문 유지 — 웹훅 사본만 마스킹. off는 전 대상이 원내일 때만.
    webhook_mask_phi: bool = True

    # Storage fundamentals (pacs-fundamentals 1축). disk_watch_path는 호스트 바인드
    # 마운트 경로여야 실제 호스트 fs를 반영한다(backend·worker 공통: export-staging).
    disk_watch_path: str = "/app/export-staging"
    # alertmanager → webhook 게이트(빈값 = 503 비활성, HIS inbound 서비스키와 동형)
    alertmanager_webhook_token: str = ""
    disk_warn_pct: float = 85.0
    disk_crit_pct: float = 95.0
    retention_years: int = 5                       # 의료법 제22조 — 만료 후보 알림 기준

    # AI governance/monitoring (ai-governance). Drift thresholds + retention.
    governance_drift_success_drop: float = 0.15    # success_rate drop (pp) → drift
    governance_drift_time_increase: float = 0.50   # avg inference time +50% → drift
    governance_drift_acceptance_drop: float = 0.20 # acceptance_rate drop (pp) → drift
    governance_min_samples: int = 20               # per-window job floor to judge
    governance_retention_days: int = 365
    # Drift circuit-breaker: on confirmed drift, auto-deactivate (quarantine) the
    # model so inference stops selecting it (is_active=false). Default OFF — SaMD
    # safety; quarantine requires manual reactivation. No version history exists
    # (ai_models = 1 row/name), so this is auto-quarantine, not version rollback.
    governance_auto_quarantine: bool = False

    # Opportunistic AI screening (opportunistic-ai). Auto-screen incoming studies;
    # only actionable findings alert, so on-by-default is safe. Disable if GPU load
    # is a concern. Runtime overrides live in Redis (pacs:screening:config).
    screening_enabled: bool = True
    screening_actionable_confidence: float = 0.85   # alert if conf >= this OR is_critical
    screening_max_per_scan: int = 20                # cap new jobs per 5-min cycle

    # Predictive prefetch (3d-ai-performance Track A)
    # Warm requests must traverse nginx so its proxy_cache gets populated.
    # celery runs with network_mode:host, so the public vhost is reachable locally.
    prefetch_warm_base_url: str = "https://his.example.org"
    prefetch_enabled: bool = True
    prefetch_next_n: int = 2            # next assignments to warm on study-open
    prefetch_prior_n: int = 1           # priors of current patient to warm
    prefetch_max_frames_per_study: int = 2000

    # IHE ATNA audit (EMR-CERT I010 / 진료정보교류 감사로그 표준). Emits DICOM Audit
    # Messages (RFC 3881) over syslog (RFC 5424) to an Audit Record Repository.
    # Default OFF — the existing DB audit_logs is unaffected; enable when an ARR
    # endpoint exists (cross-institution exchange). Best-effort, never blocks ops.
    atna_enabled: bool = False
    atna_host: str = "127.0.0.1"
    atna_port: int = 514            # 514 udp/tcp, 6514 tls
    atna_transport: str = "udp"     # udp | tcp | tls
    atna_source_id: str = "OpenPACS"
    atna_enterprise_site_id: str = ""

    # External e-signature service (sign.example.org; dev http://127.0.0.1:4100/v1).
    # PACS report staff-sign (STAFF=radiologist) + patient consent. x-api-key =
    # PACS_API_KEY (dedicated ConsumerApp). Reports/consents stay in PACS; only the
    # SHA-256 hash is sent. Empty key / disabled = no-op.
    sign_service_url: str = "http://127.0.0.1:4100/v1"
    sign_service_api_key: str = ""       # x-api-key (PACS_API_KEY)
    sign_service_enabled: bool = False
    sign_service_callback_url: str = ""  # optional webhook; empty = poll GET /verify/:id
    sign_portal_base_url: str = "https://sign.example.org"  # patient portal host
    consent_storage_path: str = "/data/consents"           # PACS keeps the consent PDFs

    # XDS-I.b Phase 1 (ITI-41 Provide & Register). 실 affinity domain Repository로 KOS+
    # DICOM을 외부 반출한다 → PHI 외부 전송이므로 default OFF. 실 도메인 규약(엔드포인트·OID·
    # TLS 상호인증) 확정 전까지 비활성. 켜져 있어도 target endpoint 미설정 시 no-op.
    # 설계: docs/02-design/xds-i-pix-mpi-phase1.design.md
    # /auth/setup(무인증 최초 ADMIN 생성)은 설치 툴링(create_admin 스크립트)이 대체 — redundant.
    # default-off로 게이트해 전 사용자 삭제 시 무인증 재시드 벡터 차단(S13). 신규 설치는 스크립트 사용.
    initial_setup_enabled: bool = False

    xdsi_submit_enabled: bool = False
    xdsi_repository_endpoint: str = ""   # 상대 Document Repository ITI-41 URL
    xdsi_source_oid: str = ""            # 우리 SubmissionSet.sourceId OID (미설정 시 로컬 도메인 OID)

    # 요청 본문 상한(DoS/OOM 백스톱) — Content-Length가 이 값 초과면 pre-read 413 거부.
    # 단일 업로드 요청 기준 2GB(대형 CT study도 통상 이하). nginx 0(무제한) 레시피의 갭 보강.
    # 비스트리밍 엔드포인트(전체를 RAM에 읽음)의 OOM 백스톱.
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    # 스트리밍 엔드포인트(청크로 디스크에 스풀, RAM 바운드)의 상한 — CD/DVD ZIP 등 대형 허용.
    # 미들웨어는 아래 경로 프리픽스에 한해 이 값까지 통과시키고, 헬퍼가 정밀 상한을 강제한다.
    max_streaming_upload_bytes: int = 5 * 1024 * 1024 * 1024
    # 청크 스트리밍으로 디스크에 받는 업로드 엔드포인트(Content-Length 백스톱 완화 대상).
    streaming_upload_paths: tuple[str, ...] = (
        "/api/v1/import/cd",
        "/api/v1/upload/zip",
    )
    # ── ZIP 압축 해제 상한 (v13.45) ─────────────────────────────────────────
    # 위 상한들은 **유입 바이트**만 묶는다. 압축 해제 후 팽창은 상한이 없었다 —
    # 작은 ZIP 하나가 디스크/RAM을 무제한 점유할 수 있었다. 이 호스트는 디스크를
    # 여러 스택이 쿼터 없이 공유하므로 고갈은 PACS 단독 장애로 끝나지 않는다.
    # 값 근거: DICOM 픽셀은 이미 압축돼 있어 실무 팽창비는 1~1.5배 → 유입 상한
    # 5GB의 2배를 누적 총량으로 잡았다. 정상 CD/DVD 임포트는 여유롭게 통과한다.
    max_zip_extract_bytes: int = 10 * 1024 * 1024 * 1024   # 누적 해제 총량
    max_zip_member_bytes: int = 1024 * 1024 * 1024          # 멤버 1개(디스크 스트리밍)
    # 멤버를 RAM에 올려야 하는 경로(Orthanc POST 본문)는 더 좁게 잡는다 —
    # gunicorn 4워커 동시 요청까지 곱해지므로 디스크 상한과 같은 값을 쓸 수 없다.
    max_zip_member_ram_bytes: int = 256 * 1024 * 1024
    max_zip_entries: int = 50000                            # 멤버 개수(다수 소파일 폭탄)

    model_config = {"env_file": ".env"}


settings = Settings()
