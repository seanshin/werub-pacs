"""Exam completion notification — technologist marks study as ready for reading."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/exam", tags=["촬영 관리"])


class ExamCompleteRequest(BaseModel):
    study_instance_uid: str
    technologist_note: str = ""
    quality_ok: bool = True


@router.post("/complete", summary="촬영 완료 알림", status_code=201)
async def mark_exam_complete(
    body: ExamCompleteRequest,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST)),
):
    """촬영 완료를 표시하고 판독의에게 알림을 보냅니다."""
    # Broadcast via WebSocket
    try:
        from app.api.websocket import manager as ws_manager
        await ws_manager.broadcast({
            "type": "exam_complete",
            "study_uid": body.study_instance_uid,
            "technologist": user.full_name if hasattr(user, 'full_name') else '',
            "note": body.technologist_note,
            "quality_ok": body.quality_ok,
        })
    except Exception:
        pass

    return {
        "status": "notified",
        "study_uid": body.study_instance_uid,
        "technologist": user.full_name if hasattr(user, 'full_name') else '',
    }
