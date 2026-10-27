"""External PACS (Peer/Modality) management + Query/Retrieve API."""
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.dicom_issue import DicomRemote, DicomTransferHistory
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/remotes", tags=["remotes"])


class RemoteCreate(BaseModel):
    name: str
    remote_type: str  # peer, modality
    url: str | None = None
    username: str | None = None
    password: str | None = None
    ae_title: str | None = None
    host: str | None = None
    port: int | None = None
    description: str | None = None


@router.get("")
async def list_remotes(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """List all configured peers/modalities."""
    result = await db.execute(select(DicomRemote).order_by(DicomRemote.name))
    remotes = result.scalars().all()
    return {
        "remotes": [
            {
                "id": str(r.id), "name": r.name, "remote_type": r.remote_type,
                "url": r.url, "ae_title": r.ae_title, "host": r.host, "port": r.port,
                "enabled": r.enabled, "description": r.description,
                "last_echo_at": r.last_echo_at.isoformat() if r.last_echo_at else None,
                "last_echo_status": r.last_echo_status,
            }
            for r in remotes
        ]
    }


@router.post("")
@AuditLogger.log("REMOTE_CREATED", "DicomRemote")
async def create_remote(
    body: RemoteCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Register a new peer or modality."""
    remote = DicomRemote(
        name=body.name, remote_type=body.remote_type,
        url=body.url, username=body.username,
        password_encrypted=encrypt_secret(body.password),
        ae_title=body.ae_title, host=body.host, port=body.port,
        description=body.description,
    )
    db.add(remote)
    await db.commit()
    return {"ok": True, "id": str(remote.id)}


@router.put("/{remote_id}")
@AuditLogger.log("REMOTE_UPDATED", "DicomRemote")
async def update_remote(
    remote_id: str,
    body: RemoteCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Update a remote."""
    result = await db.execute(select(DicomRemote).where(DicomRemote.id == remote_id))
    remote = result.scalar_one_or_none()
    if not remote:
        return {"error": "Remote not found"}

    remote.name = body.name
    remote.remote_type = body.remote_type
    remote.url = body.url
    remote.username = body.username
    if body.password:
        remote.password_encrypted = encrypt_secret(body.password)
    remote.ae_title = body.ae_title
    remote.host = body.host
    remote.port = body.port
    remote.description = body.description
    await db.commit()
    return {"ok": True}


@router.delete("/{remote_id}")
@AuditLogger.log("REMOTE_DELETED", "DicomRemote")
async def delete_remote(
    remote_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Delete a remote."""
    result = await db.execute(select(DicomRemote).where(DicomRemote.id == remote_id))
    remote = result.scalar_one_or_none()
    if not remote:
        return {"error": "Remote not found"}
    await db.delete(remote)
    await db.commit()
    return {"ok": True}


@router.post("/{remote_id}/echo")
async def echo_remote(
    remote_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Test connectivity via C-ECHO or HTTP ping."""
    result = await db.execute(select(DicomRemote).where(DicomRemote.id == remote_id))
    remote = result.scalar_one_or_none()
    if not remote:
        return {"error": "Remote not found"}

    client = request.app.state.http_client
    success = False
    message = ""

    try:
        if remote.remote_type == "peer":
            # HTTP ping to peer Orthanc
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.get(f"{remote.url}/system",
                                   auth=(remote.username, decrypt_secret(remote.password_encrypted)) if remote.username else None)
                success = resp.status_code == 200
                message = f"HTTP {resp.status_code}"
        else:
            # C-ECHO via Orthanc
            # First register modality in Orthanc if needed
            await client.put(f"/modalities/{remote.ae_title}", json={
                "AET": remote.ae_title, "Host": remote.host, "Port": remote.port,
            })
            resp = await client.post(f"/modalities/{remote.ae_title}/echo")
            success = resp.status_code == 200
            message = "C-ECHO OK" if success else f"C-ECHO failed: {resp.status_code}"
    except Exception as e:
        message = str(e)

    remote.last_echo_at = datetime.now(timezone.utc)
    remote.last_echo_status = "ok" if success else "failed"
    await db.commit()

    return {"ok": success, "message": message}


@router.post("/{remote_id}/query")
async def query_remote(
    remote_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    patient_name: str = Query("", description="Patient name filter"),
    patient_id: str = Query("", description="Patient ID filter"),
    study_date: str = Query("", description="Study date YYYYMMDD or range"),
    modality: str = Query("", description="Modality filter"),
):
    """C-FIND query to remote modality."""
    result = await db.execute(select(DicomRemote).where(DicomRemote.id == remote_id))
    remote = result.scalar_one_or_none()
    if not remote:
        return {"error": "Remote not found"}
    if remote.remote_type != "modality":
        return {"error": "Query is only supported for DICOM modalities"}

    client = request.app.state.http_client

    # Register modality
    await client.put(f"/modalities/{remote.ae_title}", json={
        "AET": remote.ae_title, "Host": remote.host, "Port": remote.port,
    })

    # Build query
    query = {}
    if patient_name:
        query["PatientName"] = f"*{patient_name}*"
    if patient_id:
        query["PatientID"] = patient_id
    if study_date:
        query["StudyDate"] = study_date
    if modality:
        query["ModalitiesInStudy"] = modality

    try:
        resp = await client.post(f"/modalities/{remote.ae_title}/query", json={
            "Level": "Study",
            "Query": query,
        })
        if resp.status_code != 200:
            return {"error": f"Query failed: {resp.status_code}"}

        query_id = resp.json().get("ID")
        # Get answers
        answers_resp = await client.get(f"/queries/{query_id}/answers")
        if answers_resp.status_code != 200:
            return {"results": [], "total": 0}

        answer_ids = answers_resp.json()
        studies = []
        for aid in answer_ids[:50]:  # Limit to 50 results
            detail = await client.get(f"/queries/{query_id}/answers/{aid}/content")
            if detail.status_code == 200:
                d = detail.json()
                studies.append({
                    "answer_id": aid,
                    "query_id": query_id,
                    "patient_name": d.get("0010,0010", {}).get("Value", ""),
                    "patient_id": d.get("0010,0020", {}).get("Value", ""),
                    "study_date": d.get("0008,0020", {}).get("Value", ""),
                    "study_description": d.get("0008,1030", {}).get("Value", ""),
                    "modality": d.get("0008,0061", {}).get("Value", ""),
                    "study_uid": d.get("0020,000d", {}).get("Value", ""),
                })

        return {"results": studies, "total": len(studies), "query_id": query_id}
    except Exception as e:
        return {"error": f"Query failed: {str(e)}"}


@router.post("/{remote_id}/retrieve")
@AuditLogger.log("DICOM_RETRIEVE", "DicomTransferHistory")
async def retrieve_from_remote(
    remote_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    query_id: str = Query(...),
    answer_id: str = Query(...),
):
    """C-MOVE retrieve from remote modality."""
    result = await db.execute(select(DicomRemote).where(DicomRemote.id == remote_id))
    remote = result.scalar_one_or_none()
    if not remote:
        return {"error": "Remote not found"}

    client = request.app.state.http_client

    # Record transfer
    transfer = DicomTransferHistory(
        remote_id=remote.id, direction="receive", status="in_progress",
    )
    db.add(transfer)
    await db.flush()

    try:
        resp = await client.post(
            f"/queries/{query_id}/answers/{answer_id}/retrieve",
            json={"TargetAet": settings.orthanc_aet},
        )
        if resp.status_code == 200:
            transfer.status = "completed"
            transfer.completed_at = datetime.now(timezone.utc)
        else:
            transfer.status = "failed"
            transfer.error_message = f"HTTP {resp.status_code}"
    except Exception as e:
        transfer.status = "failed"
        transfer.error_message = str(e)

    await db.commit()
    return {"ok": transfer.status == "completed", "transfer_id": str(transfer.id), "status": transfer.status}


@router.post("/{remote_id}/send")
@AuditLogger.log("DICOM_SEND", "DicomTransferHistory")
async def send_to_remote(
    remote_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    study_uid: str = Query(...),
):
    """Send a study to remote peer/modality."""
    result = await db.execute(select(DicomRemote).where(DicomRemote.id == remote_id))
    remote = result.scalar_one_or_none()
    if not remote:
        return {"error": "Remote not found"}

    client = request.app.state.http_client

    # Find study in Orthanc
    find_resp = await client.post("/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": study_uid},
    })
    study_ids = find_resp.json() if find_resp.status_code == 200 else []
    if not study_ids:
        return {"error": "Study not found in Orthanc"}

    transfer = DicomTransferHistory(
        remote_id=remote.id, direction="send",
        study_instance_uid=study_uid, status="in_progress",
    )
    db.add(transfer)
    await db.flush()

    try:
        if remote.remote_type == "peer":
            resp = await client.post(f"/peers/{remote.name}/store", json=study_ids)
        else:
            await client.put(f"/modalities/{remote.ae_title}", json={
                "AET": remote.ae_title, "Host": remote.host, "Port": remote.port,
            })
            resp = await client.post(f"/modalities/{remote.ae_title}/store", json=study_ids)

        if resp.status_code == 200:
            transfer.status = "completed"
            transfer.completed_at = datetime.now(timezone.utc)
        else:
            transfer.status = "failed"
            transfer.error_message = f"HTTP {resp.status_code}"
    except Exception as e:
        transfer.status = "failed"
        transfer.error_message = str(e)

    await db.commit()
    return {"ok": transfer.status == "completed", "transfer_id": str(transfer.id)}


@router.get("/transfer-history")
async def list_transfer_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
):
    """Transfer history."""
    q = select(DicomTransferHistory).order_by(DicomTransferHistory.started_at.desc())
    total_q = await db.execute(select(func.count()).select_from(DicomTransferHistory))
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    rows = result.scalars().all()

    return {
        "total": total_q.scalar() or 0,
        "history": [
            {
                "id": str(h.id), "direction": h.direction,
                "study_instance_uid": h.study_instance_uid,
                "patient_name": h.patient_name, "modality": h.modality,
                "status": h.status, "error_message": h.error_message,
                "started_at": h.started_at.isoformat() if h.started_at else None,
                "completed_at": h.completed_at.isoformat() if h.completed_at else None,
            }
            for h in rows
        ],
    }
