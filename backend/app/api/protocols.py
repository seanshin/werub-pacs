"""Imaging protocol management API for technologists.

CRUD for modality-specific imaging protocols (e.g., CT Chest, MR Brain).
Used by technologists to standardize imaging parameters.
"""
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/protocols", tags=["촬영 프로토콜"])


class ProtocolCreate(BaseModel):
    name: str
    modality: str
    body_part: str = ""
    description: str = ""
    parameters: dict = {}  # kVp, mAs, slice thickness, etc.
    is_default: bool = False


class ProtocolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parameters: dict | None = None
    is_default: bool | None = None


# In-memory protocol storage (simple — production would use DB table)
_protocols: list[dict] = [
    {"id": "p1", "name": "Chest CT (Standard)", "modality": "CT", "body_part": "Chest",
     "description": "일반 흉부 CT", "parameters": {"kVp": 120, "mAs": 200, "slice_mm": 5, "recon_mm": 1.25}, "is_default": True},
    {"id": "p2", "name": "Chest CT (Low Dose)", "modality": "CT", "body_part": "Chest",
     "description": "저선량 흉부 CT (폐암 검진)", "parameters": {"kVp": 100, "mAs": 30, "slice_mm": 5, "recon_mm": 1}, "is_default": False},
    {"id": "p3", "name": "Brain CT", "modality": "CT", "body_part": "Head",
     "description": "뇌 CT", "parameters": {"kVp": 120, "mAs": 300, "slice_mm": 5, "recon_mm": 2.5}, "is_default": True},
    {"id": "p4", "name": "Abdomen CT", "modality": "CT", "body_part": "Abdomen",
     "description": "복부 CT (조영)", "parameters": {"kVp": 120, "mAs": 250, "slice_mm": 5, "recon_mm": 3, "contrast": True}, "is_default": True},
    {"id": "p5", "name": "Brain MRI", "modality": "MR", "body_part": "Head",
     "description": "뇌 MRI", "parameters": {"sequences": ["T1", "T2", "FLAIR", "DWI"], "slice_mm": 5}, "is_default": True},
    {"id": "p6", "name": "Spine MRI", "modality": "MR", "body_part": "Spine",
     "description": "척추 MRI", "parameters": {"sequences": ["T1", "T2", "STIR"], "slice_mm": 4}, "is_default": True},
    {"id": "p7", "name": "Chest PA", "modality": "CR", "body_part": "Chest",
     "description": "흉부 단순 촬영", "parameters": {"kVp": 120, "mAs": 2.5, "distance_cm": 180}, "is_default": True},
    {"id": "p8", "name": "Abdomen US", "modality": "US", "body_part": "Abdomen",
     "description": "복부 초음파", "parameters": {"probe": "Convex", "frequency_mhz": 3.5}, "is_default": True},
]


@router.get("", summary="프로토콜 목록")
async def list_protocols(
    modality: str | None = Query(None),
    body_part: str | None = Query(None),
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST)),
):
    """촬영 프로토콜 목록을 조회합니다."""
    result = _protocols
    if modality:
        result = [p for p in result if p["modality"] == modality]
    if body_part:
        result = [p for p in result if p["body_part"] == body_part]
    return {"protocols": result, "total": len(result)}


@router.get("/{protocol_id}", summary="프로토콜 상세")
async def get_protocol(
    protocol_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST)),
):
    """프로토콜 상세 정보를 조회합니다."""
    for p in _protocols:
        if p["id"] == protocol_id:
            return p
    return {"error": "Protocol not found"}


@router.post("", summary="프로토콜 생성", status_code=201)
async def create_protocol(
    body: ProtocolCreate,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False)),
):
    """새 촬영 프로토콜을 생성합니다."""
    import uuid
    new_id = f"p{len(_protocols)+1}_{uuid.uuid4().hex[:6]}"
    protocol = {"id": new_id, **body.model_dump()}
    _protocols.append(protocol)
    return protocol


@router.patch("/{protocol_id}", summary="프로토콜 수정")
async def update_protocol(
    protocol_id: str,
    body: ProtocolUpdate,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False)),
):
    """프로토콜을 수정합니다."""
    for p in _protocols:
        if p["id"] == protocol_id:
            for key, value in body.model_dump(exclude_unset=True).items():
                p[key] = value
            return p
    return {"error": "Protocol not found"}


@router.delete("/{protocol_id}", summary="프로토콜 삭제")
async def delete_protocol(
    protocol_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """프로토콜을 삭제합니다."""
    global _protocols
    _protocols = [p for p in _protocols if p["id"] != protocol_id]
    return {"status": "deleted"}
