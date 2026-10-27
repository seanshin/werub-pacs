import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from fastapi import Depends
from app.core.config import settings
from app.core.exceptions import AppException, NotFoundError
from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_request_id() -> str:
    return str(uuid.uuid4())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema managed by Alembic (run: alembic upgrade head)
    # Import models so relationships are registered
    from app.core.database import engine
    from app.models import User, AuditLog, ValidationResult, ValidationSummary, Report, WorklistItem  # noqa: F401
    from app.models import DicomIssueRule, ModalityRenderConfig, DicomMessageTemplate, AeTitleProfile  # noqa: F401
    from app.models.ai import AIModel, InferenceJob, InferenceResult  # noqa: F401
    from app.models.patient_mapping import PatientMapping  # noqa: F401
    from app.models.mpi import IdentityDomain, MpiPatient, PatientIdentifier, XdsiSubmission  # noqa: F401
    from app.models.template import ReportTemplate  # noqa: F401
    from app.models.notification import Notification  # noqa: F401

    # Startup
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.http_client = httpx.AsyncClient(
        base_url=settings.orthanc_url,
        auth=(settings.orthanc_username, settings.orthanc_password),
        timeout=30.0,
    )

    # 런타임 멱등 DDL을 부팅 시 1회 — per-request DDL 락 경합 제거(핸들러 가드는 방어용 유지)
    try:
        from app.core.schema_migrations import run_startup_migrations
        await run_startup_migrations(engine)
    except Exception as e:
        logging.getLogger(__name__).warning(f"startup migrations error (continuing): {e}")

    # Initialize cache manager
    from app.core.cache import get_cache_manager
    cache_mgr = get_cache_manager()
    await cache_mgr.connect(settings.redis_url)
    app.state.cache = cache_mgr

    # Initialize AI models cache
    try:
        from app.core.cache_config import CACHE_KEY_MODELS, CACHE_TTL_MODELS
        from app.models.ai import AIModel
        import json
        async with engine.begin() as conn:
            result = await conn.execute(select(AIModel).where(AIModel.is_active == True))
            rows = result.mappings().all()
            if rows and cache_mgr.available:
                model_data = [
                    {
                        "id": str(row["id"]),
                        "name": row["name"],
                        "version": row["version"],
                        "model_type": str(row["model_type"]),
                        "status": str(row["status"]),
                        "modalities": row["modalities"],
                    }
                    for row in rows
                ]
                cache_key = CACHE_KEY_MODELS + ":list"
                await cache_mgr.set(
                    cache_key,
                    json.dumps({"count": len(model_data), "models": model_data}, default=str),
                    ttl=CACHE_TTL_MODELS,
                )
                logger.info(f"AI models cache initialized: {len(model_data)} models")
    except Exception as e:
        logger.warning(f"Failed to initialize AI models cache: {e}")

    # Start Orthanc change polling for WebSocket notifications
    from app.api.websocket import poll_orthanc_changes
    poll_task = asyncio.create_task(poll_orthanc_changes(app))

    # Domain metrics refresher (pacs-fundamentals 2축 — /metrics 도메인 게이지)
    from app.services.domain_metrics import domain_metrics_loop
    metrics_task = asyncio.create_task(domain_metrics_loop(app))

    # HospitalRun order → worklist sync: handled via the API integration
    # (POST /api/v1/orders, app/api/his_integration.py). The legacy direct-DB
    # poll (order_sync_task) is DISABLED — it queried HospitalRun's internal
    # schema with multiple mismatches (prescriptions has encounter_id not
    # patient_id; department 'RADIOLOGY' is an invalid OrderDepartment enum
    # value) so it never worked, and it carried hardcoded credentials. The
    # API-based integration is the decoupled, supported path.
    order_sync_task = None

    yield

    # Shutdown
    poll_task.cancel()
    metrics_task.cancel()
    if order_sync_task:
        order_sync_task.cancel()
    await cache_mgr.disconnect()
    await app.state.redis.close()
    await app.state.http_client.aclose()


from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.validation import router as validation_router
from app.api.dicomweb import router as dicomweb_router
from app.api.worklist import router as worklist_router
from app.api.report import router as report_router
from app.api.qc import router as qc_router
from app.api.audit import router as audit_router
from app.api.ai import router as ai_router
from app.api.migration import router as migration_router
from app.api.patient import router as patient_router
from app.api.patient_mapping import router as patient_mapping_router
from app.api.anonymize import router as anonymize_router
from app.api.protocols import router as protocols_router
from app.api.study_comments import router as study_comments_router
from app.api.cohort import router as cohort_router
from app.api.oncall import router as oncall_router
from app.api.reading_assignment import router as reading_assignment_router
from app.api.structured_input import router as structured_input_router
from app.api.share_link import router as share_link_router
from app.api.finding_highlight import router as finding_highlight_router
from app.api.report_compare import router as report_compare_router
from app.api.exam_complete import router as exam_complete_router
from app.api.waiting_board import router as waiting_board_router
from app.api.external_notify import router as external_notify_router
from app.api.report_translate import router as report_translate_router
from app.api.export import router as export_router
from app.api.report_pdf import router as report_pdf_router
from app.api.system_admin import router as system_admin_router
from app.api.ai_assist import router as ai_assist_router
from app.api.ai_advanced import router as ai_advanced_router
from app.api.archive import router as archive_router
from app.api.ai_orchestration import router as ai_orchestration_router
from app.api.order import router as order_router
from app.api.dashboard import router as dashboard_router
from app.api.template import router as template_router
from app.api.notification import router as notification_router
from app.api.websocket import router as ws_router
from app.api.batch_normalizer import router as batch_normalizer_router
from app.api.batch_websocket import router as batch_websocket_router
from app.api.admin_dashboard import router as admin_dashboard_router
from app.api.v1.ai_inference import router as ai_inference_router
from app.api.v1.ws.ai_progress import router as ai_progress_router
from app.api.cd_import import router as cd_import_router
from app.api.hospitalrun import router as hospitalrun_router
from app.api.speech import router as speech_router
from app.api.prior_studies import router as prior_studies_router
from app.api.reading_stats import router as reading_stats_router
from app.api.annotations import router as annotations_router
from app.api.system_health import router as system_health_router
from app.api.structured_reports import router as structured_reports_router
from app.api.followups import router as followups_router
from app.api.physician_portal import router as physician_portal_router
from app.api.dose_management import router as dose_router
from app.api.peer_review import router as peer_review_router
from app.api.conferences import router as conferences_router
from app.api.tenants import router as tenants_router
from app.api.equipment_monitor import router as equipment_monitor_router
from app.api.emergency import router as emergency_router
from app.api.external_consult import router as external_consult_router
from app.api.consult_portal import router as consult_portal_router
from app.api.external_accounts import router as external_accounts_router
from app.api.consult_history import router as consult_history_router
from app.api.normalization_settings import router as normalization_settings_router
from app.api.retake_request import router as retake_request_router
from app.api.sla_escalation import router as sla_escalation_router
from app.api.his_integration import router as his_integration_router
from app.api.webhook_config import router as webhook_config_router
from app.api.dicom_issues import router as dicom_issues_router
from app.api.upload_center import router as upload_center_router
from app.api.dicom_remotes import router as dicom_remotes_router
from app.api.provenance import router as provenance_router
from app.api.reception import router as reception_router
from app.api.irb import router as irb_router
from app.api.teaching import router as teaching_router
from app.api.prefetch import router as prefetch_router
from app.api.vrt import router as vrt_router
from app.api.patient_export import router as patient_export_router, gateway as patient_export_gateway
from app.api.patient_view import router as patient_view_router
from app.api.screening import router as screening_router
from app.api.governance import router as governance_router
from app.api.xds_export import router as xds_export_router
from app.api.pix import router as pix_router
from app.api.xds_i import router as xds_i_router
from app.api.consent import router as consent_router
from app.api.report_esign import router as report_esign_router
from app.api.bi import router as bi_router
from app.api.viewer_launch import router as viewer_launch_router
from app.api.pathology_annotation import router as pathology_annotation_router

app = FastAPI(
    title="OpenPACS API",
    description="""## 병원/클리닉 실무용 PACS REST API

### 주요 기능
- **DICOM 검증**: 비표준 DICOM 감지, JPEG 밀도 조작 검출
- **DICOMweb**: QIDO-RS 검색, STOW-RS 업로드 (검증 연동)
- **판독 리포트**: 작성 → 서명 워크플로우, 한국어 템플릿
- **QC 관리**: Study 병합/분리, 환자정보 수정
- **AI 추론**: 모델 등록, 비동기 추론, 대시보드
- **HospitalRun 연동**: 환자별 영상 조회, 검사 오더, 알림

### 인증
JWT Bearer Token 방식. `/api/v1/auth/login`으로 토큰 발급 후 `Authorization: Bearer {token}` 헤더 사용.

### 역할 (RBAC)
| 역할 | 권한 |
|------|------|
| admin | 전체 관리 |
| radiologist | 판독, 리포트, AI |
| physician | 영상 조회, 리포트 조회 |
| technologist | 업로드, 워크리스트, QC |
| researcher | 익명화 내보내기 |
""",
    version="2.0.0",
    lifespan=lifespan,
    root_path="/pacs-api",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "auth", "description": "인증 및 사용자 관리"},
        {"name": "validation", "description": "비표준 DICOM 검증 엔진 — JPEG 밀도 조작 감지 포함"},
        {"name": "dicomweb", "description": "DICOMweb 래핑 API (QIDO-RS, STOW-RS)"},
        {"name": "worklist", "description": "검사 예약 워크리스트 (MWL)"},
        {"name": "reports", "description": "판독 리포트 — 작성, 서명, 잠금, 수정본"},
        {"name": "qc", "description": "QC 관리 — Study 병합/분리, 환자정보 수정"},
        {"name": "audit", "description": "감사 로그 — 개인정보보호법 준수"},
        {"name": "ai", "description": "AI 모델 관리 및 추론 파이프라인"},
        {"name": "migration", "description": "데이터 마이그레이션 — 대량 업로드, 이관 검증"},
        {"name": "patients", "description": "환자 중심 영상/리포트 조회 — HospitalRun 연동"},
        {"name": "orders", "description": "검사 오더 → 워크리스트 자동 생성 — HospitalRun 연동"},
        {"name": "dashboard", "description": "대시보드 — 오늘 통계, 판독 대기 큐"},
        {"name": "templates", "description": "판독 리포트 템플릿 — 한국어 구조화 템플릿"},
        {"name": "notifications", "description": "알림 시스템 — 판독 완료, 긴급 소견 알림"},
        {"name": "websocket", "description": "WebSocket 실시간 알림"},
        {"name": "Batch Normalization", "description": "배치 정규화 — 비표준 DICOM 대량 처리"},
        {"name": "Admin Dashboard", "description": "관리자 대시보드 — 배치 통계, 설정 관리"},
        {"name": "HIS Integration", "description": "HIS→PACS 연동 — 재촬영, 취소, 추가촬영, 긴급판독, 환자정보, 임상정보, 일정변경"},
    ],
)

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Convert AppException subclasses to the standard OpenPACS error envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "timestamp": _utc_now_iso(),
                "request_id": exc.request_id,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert FastAPI HTTPException to the standard OpenPACS error envelope."""
    _code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "RESOURCE_NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }
    error_code = _code_map.get(exc.status_code, "ERROR")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": error_code,
                "message": detail,
                "details": {},
                "timestamp": _utc_now_iso(),
                "request_id": _generate_request_id(),
            }
        },
    )


from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://his.example.org"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Multi-tenancy middleware
from app.core.tenant import TenantMiddleware
app.add_middleware(TenantMiddleware)

# 본문 크기 상한(DoS/OOM 백스톱) — Content-Length 초과 시 핸들러 진입 전 413 거부.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as _JSONResponse


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit():
            # 스트리밍 업로드 경로는 청크로 디스크에 스풀(RAM 바운드)하므로 더 큰 상한 허용.
            if request.url.path.startswith(settings.streaming_upload_paths):
                limit = settings.max_streaming_upload_bytes
            else:
                limit = settings.max_upload_bytes
            if int(cl) > limit:
                return _JSONResponse(
                    {"detail": f"요청 본문이 너무 큽니다(최대 {limit // (1024*1024)}MB)"},
                    status_code=413)
        return await call_next(request)


app.add_middleware(BodySizeLimitMiddleware)

# Prometheus metrics endpoint (/metrics)
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/health", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("Prometheus metrics enabled at /metrics")
except ImportError:
    logger.warning("prometheus-fastapi-instrumentator not installed, /metrics disabled")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(validation_router)
app.include_router(dicomweb_router)
app.include_router(worklist_router)
app.include_router(reading_stats_router)  # Must be before report_router to avoid /{report_id} shadowing
app.include_router(report_router)
app.include_router(qc_router)
app.include_router(audit_router)
app.include_router(ai_router)
app.include_router(migration_router)
app.include_router(patient_router)
app.include_router(patient_mapping_router)
app.include_router(order_router)
app.include_router(dashboard_router)
app.include_router(template_router)
app.include_router(notification_router)
app.include_router(anonymize_router)
app.include_router(protocols_router)
app.include_router(study_comments_router)
app.include_router(cohort_router)
app.include_router(oncall_router)
app.include_router(reading_assignment_router)
app.include_router(structured_input_router)
app.include_router(share_link_router)
app.include_router(finding_highlight_router)
app.include_router(report_compare_router)
app.include_router(exam_complete_router)
app.include_router(waiting_board_router)
app.include_router(external_notify_router)
app.include_router(report_translate_router)
app.include_router(export_router)
app.include_router(report_pdf_router)
app.include_router(system_admin_router)
app.include_router(ai_assist_router)
app.include_router(ai_advanced_router)
app.include_router(archive_router)
app.include_router(ai_orchestration_router)
app.include_router(ws_router)
app.include_router(batch_normalizer_router)
app.include_router(batch_websocket_router)
app.include_router(admin_dashboard_router)
app.include_router(ai_inference_router)
app.include_router(ai_progress_router)
app.include_router(cd_import_router)
app.include_router(hospitalrun_router)
app.include_router(speech_router)
app.include_router(prior_studies_router)
app.include_router(prefetch_router)
app.include_router(vrt_router)
app.include_router(patient_export_router)
app.include_router(patient_export_gateway)
app.include_router(patient_view_router)
app.include_router(screening_router)
app.include_router(governance_router)
app.include_router(xds_export_router)
app.include_router(pix_router)
app.include_router(xds_i_router)
app.include_router(consent_router)
app.include_router(report_esign_router)
app.include_router(bi_router)
app.include_router(viewer_launch_router)
app.include_router(pathology_annotation_router)
app.include_router(annotations_router)
app.include_router(system_health_router)
app.include_router(structured_reports_router)
app.include_router(followups_router)
app.include_router(physician_portal_router)
app.include_router(dose_router)
app.include_router(peer_review_router)
app.include_router(conferences_router)
app.include_router(tenants_router)
app.include_router(equipment_monitor_router)
app.include_router(emergency_router)
app.include_router(external_consult_router)
app.include_router(consult_portal_router)
app.include_router(external_accounts_router)
app.include_router(consult_history_router)
app.include_router(normalization_settings_router)
app.include_router(retake_request_router)
app.include_router(sla_escalation_router)
app.include_router(his_integration_router)
app.include_router(webhook_config_router)
app.include_router(dicom_issues_router)
app.include_router(upload_center_router)
app.include_router(dicom_remotes_router)
app.include_router(provenance_router)
app.include_router(reception_router)
app.include_router(irb_router)
app.include_router(teaching_router)

from app.api.monitoring import router as monitoring_router
app.include_router(monitoring_router)


@app.get("/health")
async def health_check():
    checks = {"status": "ok", "services": {}}

    # Redis
    try:
        await app.state.redis.ping()
        checks["services"]["redis"] = "ok"
    except Exception:
        checks["services"]["redis"] = "error"
        checks["status"] = "degraded"

    # Orthanc
    try:
        resp = await app.state.http_client.get("/system")
        if resp.status_code == 200:
            orthanc_info = resp.json()
            checks["services"]["orthanc"] = {
                "status": "ok",
                "version": orthanc_info.get("Version", "unknown"),
                "dicom_aet": orthanc_info.get("DicomAet", "unknown"),
            }
        else:
            checks["services"]["orthanc"] = "error"
            checks["status"] = "degraded"
    except Exception:
        checks["services"]["orthanc"] = "error"
        checks["status"] = "degraded"

    # SSO status
    checks["services"]["sso"] = {
        "enabled": settings.his_sso_enabled,
        "method": "shared_secret" if settings.hospitalrun_auth_secret else "not_configured",
        "his_connected": bool(settings.hospitalrun_auth_secret),
    }

    return checks


@app.get("/api/v1/system/info")
async def system_info(user: User = Depends(get_current_user)):
    """Orthanc system info proxy. Requires authentication."""
    resp = await app.state.http_client.get("/system")
    return resp.json()


@app.get("/api/v1/studies")
async def list_studies(limit: int = 20, since: int = 0, user: User = Depends(get_current_user)):
    """List studies from Orthanc. Requires authentication."""
    resp = await app.state.http_client.get(
        "/studies", params={"limit": limit, "since": since}
    )
    return resp.json()


@app.get("/api/v1/studies/{study_id}")
async def get_study(study_id: str, user: User = Depends(get_current_user)):
    """Get study details from Orthanc. Requires authentication."""
    resp = await app.state.http_client.get(f"/studies/{study_id}")
    if resp.status_code == 404:
        raise NotFoundError(resource="Study", resource_id=study_id)
    return resp.json()


@app.get("/api/v1/statistics")
async def get_statistics(
    user: User = Depends(get_current_user),
    days: int = Query(default=7),
):
    """Get PACS + normalization statistics."""
    resp = await app.state.http_client.get("/statistics")
    orthanc = resp.json() if resp.status_code == 200 else {}

    return orthanc
