"""AI inference worker using Celery.

Handles async inference jobs:
1. Fetch DICOM from Orthanc
2. Preprocess (DICOM → numpy)
3. Run inference (ONNX / external API / Docker)
4. Store results
5. Send alerts for critical findings
"""
import io
import logging
import time
from datetime import datetime, timezone

import httpx
import numpy as np
import pydicom
from pydicom.uid import generate_uid
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

# A5 fix: `logger` was used on the SR/SEG "non-critical" failure path but never
# defined → NameError escaped to the outer except, flipping a completed inference
# to FAILED + retry on a transient Orthanc store hiccup.
logger = logging.getLogger(__name__)

celery_app = Celery(
    "openpacs",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.services.ai_worker.run_inference": {"queue": "ai_inference"},
        "app.services.sla_scheduler.check_sla": {"queue": "default"},
        "app.services.sla_scheduler.auto_resolve_escalations": {"queue": "default"},
        # Low-priority cache warming — separate queue so it never competes with
        # inference/default work; worker must consume with -Q ...,prefetch
        "app.services.prefetch_worker.plan_prefetch": {"queue": "prefetch"},
        "app.services.prefetch_worker.warm_study": {"queue": "prefetch"},
        # Unrouted tasks land in the unconsumed "celery" queue (worker runs with
        # explicit -Q): auto_validate piled up 1,652 deep before this route existed.
        # Every task here MUST have an explicit route.
        "app.services.dicom_auto_validate.auto_validate_new_studies": {"queue": "default"},
        "app.services.backup_monitor.check_backup_freshness": {"queue": "default"},
        "app.services.storage_monitor.check_host_disk": {"queue": "default"},
        "app.services.storage_monitor.check_retention_candidates": {"queue": "default"},
        "app.services.vrt_capability.vrt_network_check": {"queue": "default"},
        # Patient export packaging — its own queue (DICOM archive fetch can be
        # large); worker must list it in -Q (v11.5 unrouted-queue lesson)
        "app.services.patient_export_worker.build_patient_export": {"queue": "export"},
        "app.services.patient_export_worker.cleanup_patient_exports": {"queue": "default"},
        "app.services.opportunistic_screener.scan_and_collect": {"queue": "default"},
        "app.services.governance_monitor.rollup_and_assess": {"queue": "default"},
        "app.services.bi_report.monthly_bi_report": {"queue": "default"},
        # K3 해결: batch_normalizer_task가 websocket import 대신 Redis pub/sub(batch_progress)
        # 사용 → 워커 import 가능. 등록.
        "app.services.batch_normalizer_task.process_batch_normalization": {"queue": "default"},
        "app.services.xds_export_worker.build_xds_export": {"queue": "export"},
        "app.services.pathology_arrival.check_pathology_arrivals": {"queue": "default"},
        "app.services.ai_health_monitor.check_ai_server": {"queue": "default"},
    },
    beat_schedule={
        "sla-check-every-5min": {
            "task": "app.services.sla_scheduler.check_sla",
            "schedule": 300.0,  # 5 minutes
        },
        "sla-auto-resolve-every-10min": {
            "task": "app.services.sla_scheduler.auto_resolve_escalations",
            "schedule": 600.0,  # 10 minutes
        },
        "dicom-auto-validate-every-5min": {
            "task": "app.services.dicom_auto_validate.auto_validate_new_studies",
            "schedule": 300.0,  # 5 minutes
        },
        "backup-freshness-every-30min": {
            "task": "app.services.backup_monitor.check_backup_freshness",
            "schedule": 1800.0,  # 30 minutes
        },
        "vrt-network-check-daily": {
            "task": "app.services.vrt_capability.vrt_network_check",
            "schedule": 86400.0,  # daily — auto-detects the planned direct GPU link
        },
        "patient-export-cleanup-hourly": {
            "task": "app.services.patient_export_worker.cleanup_patient_exports",
            "schedule": 3600.0,  # purge staged packages past TTL
        },
        "opportunistic-screening-every-5min": {
            "task": "app.services.opportunistic_screener.scan_and_collect",
            "schedule": 300.0,  # proactive AI screening of new studies
        },
        "ai-governance-rollup-daily": {
            "task": "app.services.governance_monitor.rollup_and_assess",
            "schedule": 86400.0,  # daily model performance rollup + drift/compliance
        },
        "bi-monthly-report": {
            "task": "app.services.bi_report.monthly_bi_report",
            "schedule": crontab(day_of_month=1, hour=6, minute=0),  # 매월 1일 06:00 KST
        },
        "host-disk-watch-every-30min": {
            "task": "app.services.storage_monitor.check_host_disk",
            "schedule": 1800.0,  # 호스트 fs 워터마크 감시 (85/95%)
        },
        "retention-candidates-monthly": {
            "task": "app.services.storage_monitor.check_retention_candidates",
            "schedule": crontab(day_of_month=2, hour=5, minute=0),  # 매월 2일 05:00 KST
        },
        "pathology-arrival-every-5min": {
            "task": "app.services.pathology_arrival.check_pathology_arrivals",
            "schedule": 300.0,  # SM WSI 도착 감지·워크리스트 정합 (v13.34, LIS 역할분담)
        },
        "ai-server-health-every-30min": {
            "task": "app.services.ai_health_monitor.check_ai_server",
            "schedule": 1800.0,  # 전 AI 기능이 공유하는 단일 의존성 — 무감시로 2주+ 방치된 이력
        },
    },
    imports=["app.services.sla_scheduler", "app.services.dicom_auto_validate",
             "app.services.prefetch_worker", "app.services.backup_monitor",
             "app.services.storage_monitor",
             "app.services.vrt_capability", "app.services.patient_export_worker",
             "app.services.opportunistic_screener", "app.services.governance_monitor",
             "app.services.bi_report", "app.services.xds_export_worker",
             "app.services.batch_normalizer_task", "app.services.pathology_arrival",
             "app.services.ai_health_monitor"],
)


def _get_orthanc_client():
    return httpx.Client(
        base_url=settings.orthanc_url,
        auth=(settings.orthanc_username, settings.orthanc_password),
        timeout=60.0,
    )


# Module-level sync engine, created once per Celery process and reused across
# tasks. Creating a new engine on every call (the previous behavior) leaked a
# connection pool per invocation, exhausting the shared postgres over time.
_sync_engine = None


def _get_db_session():
    """Synchronous DB session for Celery tasks (shared, bounded-pool engine)."""
    global _sync_engine
    from sqlalchemy.orm import Session
    try:
        if _sync_engine is None:
            from sqlalchemy import create_engine
            sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
            # Small pool per process; db.close() returns connections here for reuse.
            _sync_engine = create_engine(
                sync_url,
                pool_size=2,
                max_overflow=3,
                pool_pre_ping=True,
                pool_recycle=1800,
            )
        return Session(_sync_engine)
    except Exception:
        return None


def _preprocess_dicom(dicom_bytes: bytes, config: dict | None = None) -> dict:
    """Convert DICOM to numpy array with metadata."""
    ds = pydicom.dcmread(io.BytesIO(dicom_bytes), force=True)

    # 압축 TS(JPEG/JPEG2000/RLE)는 pylibjpeg/gdcm 핸들러 부재 시 pixel_array가
    # NotImplementedError 등을 던짐 → 명확한 사유로 변환(추론 워커 크래시 방지)
    try:
        pixel_array = ds.pixel_array.astype(np.float32)
    except Exception as e:
        ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", "?")
        raise ValueError(f"픽셀 디코딩 실패(TransferSyntax={ts}) — 코덱 미설치 가능: {e}")

    # Apply rescale if available
    slope = getattr(ds, "RescaleSlope", 1)
    intercept = getattr(ds, "RescaleIntercept", 0)
    pixel_array = pixel_array * float(slope) + float(intercept)

    # Normalize to 0-1
    p_min, p_max = pixel_array.min(), pixel_array.max()
    if p_max > p_min:
        pixel_array = (pixel_array - p_min) / (p_max - p_min)

    return {
        "pixel_array": pixel_array,
        "rows": int(ds.Rows),
        "columns": int(ds.Columns),
        "modality": str(getattr(ds, "Modality", "")),
        "patient_id": str(getattr(ds, "PatientID", "")),
        "study_uid": str(getattr(ds, "StudyInstanceUID", "")),
        "pixel_spacing": [float(x) for x in getattr(ds, "PixelSpacing", [1.0, 1.0])],
    }


def _run_mock_inference(preprocessed: dict, model_name: str) -> dict:
    """Mock inference for testing — simulates AI analysis.

    In production, this would call ONNX Runtime, Triton, or external API.
    """
    pixel_array = preprocessed["pixel_array"]
    modality = preprocessed["modality"]

    # Simulate analysis based on modality
    mean_val = float(pixel_array.mean())
    std_val = float(pixel_array.std())

    findings = []
    is_critical = False
    max_confidence = 0.0

    # Simulate detection based on pixel statistics
    if std_val > 0.3:
        confidence = min(0.95, std_val * 1.5)
        max_confidence = max(max_confidence, confidence)
        findings.append({
            "type": "abnormality_detected",
            "description": f"Potential abnormality detected in {modality} image",
            "confidence": round(confidence, 3),
            "location": {"x": preprocessed["columns"] // 2, "y": preprocessed["rows"] // 2},
            "severity": "warning",
        })

    if mean_val > 0.7:
        confidence = 0.85
        max_confidence = max(max_confidence, confidence)
        is_critical = True
        findings.append({
            "type": "critical_finding",
            "description": "High-density region detected — requires urgent review",
            "confidence": confidence,
            "severity": "critical",
        })

    if not findings:
        findings.append({
            "type": "normal",
            "description": "No significant abnormalities detected",
            "confidence": 0.92,
            "severity": "normal",
        })
        max_confidence = 0.92

    return {
        "model_name": model_name,
        "findings": findings,
        "findings_count": len(findings),
        "max_confidence": round(max_confidence, 3),
        "is_critical": is_critical,
        "image_stats": {
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "shape": [preprocessed["rows"], preprocessed["columns"]],
        },
        "disclaimer": "AI results are for diagnostic assistance only. Final judgment is the responsibility of the medical professional.",
    }


def _endpoint_allowed(endpoint_url: str) -> bool:
    """external_api 모델 endpoint host 화이트리스트 (arch-invariants INV-PHI-03 유지 가드).

    추론 페이로드(픽셀)는 원내 AI 서버로만 나가야 한다 — 모델 등록으로 임의 원외
    URL이 들어와도 여기서 차단. 허용: 기본 ai_server_url host, localhost,
    settings.ai_endpoint_allowlist(콤마 구분 추가 host).
    """
    from urllib.parse import urlparse
    try:
        host = (urlparse(endpoint_url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    allowed = {"localhost", "127.0.0.1"}
    try:
        default_host = (urlparse(settings.ai_server_url).hostname or "").lower()
        if default_host:
            allowed.add(default_host)
    except Exception:
        pass
    extra = getattr(settings, "ai_endpoint_allowlist", "") or ""
    allowed.update(h.strip().lower() for h in extra.split(",") if h.strip())
    return host in allowed


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_inference(self, job_id: str):
    """Execute AI inference job."""
    db = _get_db_session()
    if db is None:
        return {"error": "DB connection failed"}

    try:
        from app.models.ai import InferenceJob, AIModel, JobStatus

        # H2: 멱등 — QUEUED/FAILED일 때만 원자적으로 선점(acks_late 재전달 시 처음부터
        # 재실행되어 카운터/SR 중복되는 것 방지). 0행이면 이미 처리중/완료 → no-op.
        claimed = db.query(InferenceJob).filter(
            InferenceJob.id == job_id,
            InferenceJob.status.in_([JobStatus.QUEUED.value, JobStatus.FAILED.value]),
        ).update(
            {InferenceJob.status: JobStatus.PREPROCESSING.value,
             InferenceJob.started_at: datetime.now(timezone.utc),
             InferenceJob.progress: 10},
            synchronize_session=False)
        db.commit()
        if not claimed:
            return {"skipped": "already_processing_or_done", "job_id": job_id}

        job = db.query(InferenceJob).filter(InferenceJob.id == job_id).first()
        if not job:
            return {"error": "Job not found"}

        # Get model
        model = db.query(AIModel).filter(AIModel.id == job.model_id).first()
        if not model:
            job.status = JobStatus.FAILED.value
            job.error_message = "Model not found"
            db.commit()
            return {"error": "Model not found"}

        client = _get_orthanc_client()

        # Find study in Orthanc
        if job.orthanc_study_id:
            study_resp = client.get(f"/studies/{job.orthanc_study_id}")
        else:
            find_resp = client.post("/tools/find", json={
                "Level": "Study",
                "Query": {"StudyInstanceUID": job.study_instance_uid},
            })
            studies = find_resp.json()
            if not studies:
                job.status = JobStatus.FAILED.value
                job.error_message = "Study not found in Orthanc"
                db.commit()
                return {"error": "Study not found"}
            study_resp = client.get(f"/studies/{studies[0]}")

        study = study_resp.json()
        patient_tags = study.get("PatientMainDicomTags", {})
        job.patient_id = patient_tags.get("PatientID")
        job.modality = study.get("MainDicomTags", {}).get("ModalitiesInStudy", "")

        # Get first instance for analysis
        instances = []
        for series_id in study.get("Series", []):
            sr = client.get(f"/series/{series_id}")
            if sr.status_code == 200:
                for inst_id in sr.json().get("Instances", []):
                    instances.append(inst_id)
                    break
            if instances:
                break

        if not instances:
            job.status = JobStatus.FAILED.value
            job.error_message = "No instances found in study"
            db.commit()
            return {"error": "No instances"}

        # Download DICOM
        job.progress = 30
        job.status = JobStatus.INFERRING.value
        db.commit()

        dicom_resp = client.get(f"/instances/{instances[0]}/file")
        dicom_bytes = dicom_resp.content

        # Preprocess
        job.progress = 50
        db.commit()

        start_time = time.time()
        preprocessed = _preprocess_dicom(dicom_bytes, model.input_config)

        # Run inference
        job.progress = 70
        db.commit()

        # Select inference engine based on model type
        meta = {"modality": preprocessed["modality"], "rows": preprocessed["rows"],
                "columns": preprocessed["columns"], "pixel_spacing": preprocessed["pixel_spacing"]}

        use_external = model.model_type in ("external_api",) and model.endpoint_url
        if use_external and not _endpoint_allowed(model.endpoint_url):
            job.status = JobStatus.FAILED.value
            job.error_message = f"endpoint host not allowlisted: {model.endpoint_url[:100]}"
            db.commit()
            logger.error("inference blocked — endpoint not allowlisted: model=%s url=%s",
                         model.name, model.endpoint_url[:100])
            return {"error": "endpoint not allowlisted"}

        # AI 추론 건별 감사 (arch-invariants INV-AUDIT-01): 어떤 study가 어느
        # 모델/host로 갔는지 append-only audit_logs로 추적. 전송 직전에 기록해
        # 실패/행 상태에서도 경계 통과 사실이 남는다. best-effort — 주 동작 불침해.
        try:
            from urllib.parse import urlparse
            from app.models.audit import AuditLog
            endpoint_host = (urlparse(model.endpoint_url).hostname or "?") if use_external else "local"
            db.add(AuditLog(
                username="celery-ai-worker",
                action="AI_INFERENCE",   # 대문자 NAME 통일(v13.47)
                resource_type="InferenceJob",
                resource_id=str(job.id),
                study_instance_uid=job.study_instance_uid,
                patient_id=job.patient_id,
                details={"model": model.name, "version": model.version,
                         "engine": "external_api" if use_external else "onnx_local",
                         "endpoint_host": endpoint_host},
            ))
            db.commit()
        except Exception as audit_err:
            db.rollback()
            logger.error("ai_inference audit write failed: %s", audit_err)

        if use_external:
            # Ollama / external vision API
            from app.services.ollama_inference import OllamaInferenceEngine
            ollama_model = model.docker_image or model.name  # docker_image field stores ollama model name
            engine = OllamaInferenceEngine(model_name=ollama_model, endpoint_url=model.endpoint_url)
            results = engine.run(preprocessed["pixel_array"], meta)
        else:
            # ONNX Runtime or statistical fallback
            from app.services.onnx_inference import OnnxInferenceEngine
            engine = OnnxInferenceEngine(
                model_path=model.model_path,
                checksum_sha256=getattr(model, "checksum_sha256", None))
            results = engine.run(preprocessed["pixel_array"], meta)

        results["model_name"] = model.name

        inference_ms = int((time.time() - start_time) * 1000)

        # Postprocess & store results
        job.status = JobStatus.POSTPROCESSING.value
        job.progress = 90
        db.commit()

        # Update job with results
        job.status = JobStatus.COMPLETED.value
        job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        job.inference_time_ms = inference_ms
        job.results = results
        job.findings_count = results["findings_count"]
        job.max_confidence = results["max_confidence"]
        job.is_critical = results["is_critical"]

        # Store results as standards-compliant DICOM (TID 1500 SR + optional SEG).
        # The analyzed source instance is the evidence the standard objects link to.
        from app.services.dicom_ai_standard import build_ai_sr, build_ai_seg
        result_uids = {}
        try:
            sr_bytes = build_ai_sr(
                source_images=[dicom_bytes],
                model_name=model.name,
                model_version=model.version,
                findings=results.get("findings", []),
                inference_time_ms=inference_ms,
                is_critical=results.get("is_critical", False),
                # Deterministic UIDs from the job id (H2c): an acks_late retry
                # re-creates the same SR → Orthanc dedups instead of duplicating.
                sop_instance_uid=generate_uid(entropy_srcs=[str(job_id), "ai-sr-sop"]),
                series_instance_uid=generate_uid(entropy_srcs=[str(job_id), "ai-sr-series"]),
            )
            sr_resp = client.post("/instances", content=sr_bytes,
                                  headers={"Content-Type": "application/dicom"})
            if sr_resp.status_code in (200, 409):
                sr_result = sr_resp.json()
                result_uids["sr_orthanc_id"] = sr_result.get("ID")
                result_uids["sr_sop_uid"] = sr_result.get("ID")
        except Exception as e:
            logger.warning(f"AI SR storage failed (non-critical): {e}")

        # SEG: only when the inference engine produced a segmentation mask
        mask = results.get("mask")
        if mask is not None:
            try:
                import numpy as _np
                seg_bytes = build_ai_seg(
                    source_images=[dicom_bytes],
                    mask=_np.asarray(mask),
                    model_name=model.name,
                    model_version=model.version,
                    segment_label=results.get("segment_label", "AI Segmentation"),
                )
                seg_resp = client.post("/instances", content=seg_bytes,
                                       headers={"Content-Type": "application/dicom"})
                if seg_resp.status_code in (200, 409):
                    result_uids["seg_orthanc_id"] = seg_resp.json().get("ID")
            except Exception as e:
                logger.warning(f"AI SEG storage failed (non-critical): {e}")

        if result_uids:
            job.result_dicom_uids = result_uids

        # H2: 원자적 카운터 UPDATE — read-modify-write는 동시/재전달 시 lost update.
        from sqlalchemy import func as _func
        db.query(AIModel).filter(AIModel.id == model.id).update(
            {AIModel.total_runs: AIModel.total_runs + 1,
             AIModel.successful_runs: AIModel.successful_runs + 1,
             AIModel.avg_inference_time: _func.coalesce(
                 (AIModel.avg_inference_time + inference_ms) / 2, inference_ms)},
            synchronize_session=False)

        db.commit()
        client.close()

        return {
            "job_id": job_id,
            "status": "completed",
            "inference_time_ms": inference_ms,
            "findings_count": results["findings_count"],
            "is_critical": results["is_critical"],
        }

    except Exception as e:
        if db:
            from app.models.ai import InferenceJob, JobStatus
            job = db.query(InferenceJob).filter(InferenceJob.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED.value
                job.error_message = str(e)
                job.retry_count += 1
                db.commit()
        raise self.retry(exc=e)

    finally:
        if db:
            db.close()
