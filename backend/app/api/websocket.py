"""WebSocket endpoint for real-time PACS notifications."""
import asyncio
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)

    async def broadcast(self, message: dict):
        dead = set()
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self.connections -= dead

    @property
    def count(self) -> int:
        return len(self.connections)


manager = ConnectionManager()


@router.websocket("/ws/notifications")
async def websocket_notifications(ws: WebSocket):
    """WebSocket endpoint for real-time notifications.

    Clients connect here to receive:
    - new_instance: when a new DICOM image arrives
    - new_study: when a new study is created
    - validation_alert: when non-standard DICOM is detected
    - stable_study: when a study becomes stable (no new images for a while)

    Authentication: JWT token required as query parameter ?token=
    """
    # Authenticate before accepting connection
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Authentication required")
        return

    try:
        from jose import jwt as jose_jwt, JWTError
        payload = jose_jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("type") != "access":
            await ws.close(code=4001, reason="Invalid token type")
            return
    except (JWTError, Exception):
        await ws.close(code=4001, reason="Invalid or expired token")
        return

    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive, receive client messages (heartbeat)
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(ws)


@router.get("/api/v1/ws/status")
async def websocket_status():
    """Get WebSocket connection count."""
    return {"active_connections": manager.count}


async def poll_orthanc_changes(app):
    """Background task: poll Orthanc /changes endpoint and broadcast via WebSocket.

    This runs as an asyncio task during app lifetime.
    """
    import httpx

    last_seq = 0
    client: httpx.AsyncClient = app.state.http_client

    while True:
        try:
            resp = await client.get("/changes", params={"since": last_seq, "limit": 10})
            if resp.status_code == 200:
                data = resp.json()
                for change in data.get("Changes", []):
                    change_type = change.get("ChangeType", "")
                    resource_type = change.get("ResourceType", "")
                    resource_id = change.get("ID", "")

                    if change_type == "NewInstance":
                        # Fetch instance details
                        inst_resp = await client.get(f"/instances/{resource_id}")
                        if inst_resp.status_code == 200:
                            inst = inst_resp.json()
                            tags = inst.get("MainDicomTags", {})
                            await manager.broadcast({
                                "type": "new_instance",
                                "orthanc_id": resource_id,
                                "sop_instance_uid": tags.get("SOPInstanceUID"),
                                "study_orthanc_id": inst.get("ParentStudy"),
                            })

                    elif change_type == "StableStudy":
                        study_resp = await client.get(f"/studies/{resource_id}")
                        if study_resp.status_code == 200:
                            study = study_resp.json()
                            main_tags = study.get("MainDicomTags", {})
                            patient_tags = study.get("PatientMainDicomTags", {})

                            # AI Auto-trigger: queue inference for stable study
                            await _auto_trigger_ai(app, resource_id, main_tags, patient_tags)
                            # AI Auto-draft: generate preliminary report
                            await _auto_draft_report(main_tags, patient_tags)
                            await manager.broadcast({
                                "type": "stable_study",
                                "orthanc_id": resource_id,
                                "study_instance_uid": main_tags.get("StudyInstanceUID"),
                                "patient_name": patient_tags.get("PatientName"),
                                "patient_id": patient_tags.get("PatientID"),
                                "study_description": main_tags.get("StudyDescription"),
                                "modality": study.get("RequestedTags", {}).get("ModalitiesInStudy", ""),
                                "series_count": len(study.get("Series", [])),
                            })

                    elif change_type == "NewStudy":
                        await manager.broadcast({
                            "type": "new_study",
                            "orthanc_id": resource_id,
                        })

                last_seq = data.get("Last", last_seq)
                if data.get("Done", True):
                    await asyncio.sleep(2)
            else:
                await asyncio.sleep(5)
        except Exception:
            await asyncio.sleep(5)


async def _auto_trigger_ai(app, orthanc_study_id: str, main_tags: dict, patient_tags: dict):
    """Auto-trigger AI inference when a study becomes stable.

    Matches active AI models by modality and queues inference jobs.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        from app.core.database import async_session
        if async_session is None:
            return

        from app.models.ai import AIModel, InferenceJob, JobStatus, ModelStatus

        async with async_session() as db:
            from sqlalchemy import select

            # Find active models
            result = await db.execute(
                select(AIModel).where(AIModel.is_active.is_(True))
            )
            models = result.scalars().all()

            study_uid = main_tags.get("StudyInstanceUID", "")
            modality = main_tags.get("ModalitiesInStudy", "")
            patient_id = patient_tags.get("PatientID", "")

            for model in models:
                # Check modality match
                model_modalities = [m.strip() for m in model.modalities.split(",")]
                if not any(m in modality for m in model_modalities):
                    continue

                # Check if already queued for this study
                existing = await db.execute(
                    select(InferenceJob).where(
                        InferenceJob.study_instance_uid == study_uid,
                        InferenceJob.model_id == model.id,
                        InferenceJob.status.in_([JobStatus.QUEUED.value, JobStatus.COMPLETED.value]),
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                # Create inference job
                job = InferenceJob(
                    model_id=model.id,
                    model_name=model.name,
                    study_instance_uid=study_uid,
                    orthanc_study_id=orthanc_study_id,
                    patient_id=patient_id,
                    modality=modality,
                    status=JobStatus.QUEUED,
                    trigger_type="auto",
                    requested_by="system",
                )
                db.add(job)
                await db.commit()
                await db.refresh(job)

                # Queue to Celery
                try:
                    from app.services.ai_worker import run_inference
                    run_inference.delay(str(job.id))
                    logger.info(f"AI auto-trigger: {model.name} for study {study_uid[:30]}...")
                except Exception:
                    pass

                # Broadcast notification
                await manager.broadcast({
                    "type": "ai_triggered",
                    "model_name": model.name,
                    "study_uid": study_uid,
                    "patient_id": patient_id,
                })

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI auto-trigger error: {e}")


async def _auto_draft_report(main_tags: dict, patient_tags: dict):
    """Auto-generate AI preliminary draft report when a study becomes stable.

    Calls MedGemma to analyze study metadata and create a draft report.
    Only creates if no report exists yet for this study.
    """
    import logging
    import httpx
    logger = logging.getLogger(__name__)

    study_uid = main_tags.get("StudyInstanceUID", "")
    patient_id = patient_tags.get("PatientID", "")
    patient_name = patient_tags.get("PatientName", "")
    modality = main_tags.get("ModalitiesInStudy", "")
    study_desc = main_tags.get("StudyDescription", "")

    if not study_uid:
        return

    try:
        # Check if auto-draft is enabled in config
        from app.core.database import async_session
        if async_session is None:
            return

        from sqlalchemy import text

        async with async_session() as db:
            # Check config
            config_result = await db.execute(
                text("SELECT value FROM openpacs_config WHERE key = 'ai_auto_draft'")
            )
            config_row = config_result.scalar_one_or_none()
            if config_row:
                import json
                config = json.loads(config_row) if isinstance(config_row, str) else config_row
                if not config.get("enabled", False):
                    return
            else:
                # Auto-draft disabled by default — admin must enable
                return

            # Check if report already exists
            existing = await db.execute(
                text("SELECT id FROM reports WHERE study_instance_uid = :uid LIMIT 1"),
                {"uid": study_uid},
            )
            if existing.scalar_one_or_none():
                return

            # Call MedGemma for analysis
            AI_SERVER_URL = settings.ai_server_url
            AI_API_KEY = settings.ai_api_key

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{AI_SERVER_URL}/api/vision/medical/report",
                    headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
                    json={
                        # patient_id intentionally omitted — not needed for
                        # inference (data minimization; arch-invariants audit)
                        "study_uid": study_uid,
                        "modality": modality,
                        "study_description": study_desc,
                        "task": "auto_draft",
                    },
                )

                if resp.status_code != 200:
                    logger.debug("AI auto-draft: API returned %d for %s", resp.status_code, study_uid[:30])
                    return

                data = resp.json()
                findings = data.get("findings", data.get("analysis", {}).get("findings", ""))
                impression = data.get("impression", data.get("analysis", {}).get("impression", ""))
                recommendation = data.get("recommendation", data.get("analysis", {}).get("recommendations", ""))

                if not findings and not impression:
                    logger.debug("AI auto-draft: empty result for %s", study_uid[:30])
                    return

            # Create draft report
            import uuid
            report_id = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO reports (id, study_instance_uid, patient_id, patient_name,
                    modality, study_description, findings, impression, recommendation,
                    status, urgency, author_name, created_at)
                VALUES (:id, :study_uid, :pid, :pname, :mod, :desc,
                    :findings, :impression, :rec, 'draft', 'normal',
                    :author, NOW())
            """), {
                "id": report_id, "study_uid": study_uid, "pid": patient_id,
                "pname": patient_name, "mod": modality, "desc": study_desc,
                "findings": findings, "impression": impression,
                "rec": recommendation, "author": "AI-MedGemma (auto-draft)",
            })
            await db.commit()

            logger.info("AI auto-draft created: %s for study %s", report_id[:8], study_uid[:30])

            # Broadcast notification
            await manager.broadcast({
                "type": "ai_draft_created",
                "study_uid": study_uid,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "report_id": report_id,
            })

            # Create notification
            try:
                from app.services.alert_service import send_alert
                await send_alert(
                    event_type="ai_draft",
                    title=f"AI 초안 생성: {patient_name or patient_id}",
                    message=f"MedGemma가 {modality} {study_desc} 검사의 판독 초안을 자동 생성했습니다.",
                    urgency="normal",
                    target_role="radiologist",
                    study_instance_uid=study_uid,
                    patient_id=patient_id,
                    action_url=f"/pacs-admin/reading/view?study={study_uid}",
                    patient_name=patient_name,
                )
            except Exception:
                pass

    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"AI auto-draft error: {e}")
