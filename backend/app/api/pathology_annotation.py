"""병리 WSI 벌크 주석 API (DICOM Sup 222). G1 — v13.19 후속.

WSI(SM) 스터디에 폴리곤/포인트 등 주석을 표준 DICOM ANN(SOPClass …91.1)으로 생성·저장.
뷰어 DicomMicroscopyANN 핸들러가 표시. 계산병리 AI 출력/병리의 수기 마킹 저장용.
"""
import asyncio
import io
import logging
from typing import Annotated

import pydicom
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import _log_audit_entry
from app.core.database import get_db
from app.core.exceptions import AppException, NotFoundError, DicomUploadError
from app.core.security import RequireRole
from app.models.user import Role, User
from app.services.microscopy_annotation import build_bulk_annotations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pathology", tags=["pathology"])

# 병리 판독 쓰기 역할 — 임상 판독의(RESIDENT는 RADIOLOGIST로 승격). RESEARCHER/SERVICE/TECH 제외.
PathologyWriteRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN, allow_btg=False)

# 입력 상한 — 계산병리 AI의 슬라이드당 대량 주석은 수용하되 단일 요청 OOM은 차단.
MAX_GROUPS = 100
MAX_ANNOTATIONS_PER_GROUP = 50_000
MAX_POINTS_PER_ANNOTATION = 100_000

_Point = Annotated[list[float], Field(min_length=2, max_length=3)]
_AnnCoords = Annotated[list[_Point], Field(min_length=1, max_length=MAX_POINTS_PER_ANNOTATION)]


class AnnotationGroupIn(BaseModel):
    label: str = Field(..., max_length=64)   # DICOM VR=LO
    graphic_type: str = "POLYGON"        # POLYGON/POINT/POLYLINE/ELLIPSE/RECTANGLE
    coordinates: list[_AnnCoords] = Field(
        ..., min_length=1, max_length=MAX_ANNOTATIONS_PER_GROUP,
        description="주석별 [[x,y(,z)],...] 배열의 리스트 (2D=col,row / 3D=슬라이드 x,y,z)")
    algorithm_type: str = "MANUAL"       # MANUAL/AUTOMATIC/SEMIAUTOMATIC
    category: dict | None = None         # {value,scheme,meaning} SNOMED 등, 선택
    type: dict | None = None


class AnnotationsIn(BaseModel):
    groups: list[AnnotationGroupIn] = Field(..., min_length=1, max_length=MAX_GROUPS)
    coordinate_type: str = "2D"          # 2D(픽셀 col,row) | 3D(슬라이드 x,y,z mm — 뷰어 드로잉 ROI)
    series_uid: str | None = None        # 다중 슬라이드 study에서 대상 SM 시리즈 지정(미지정=첫 SM)
    content_description: str | None = None


async def _find_sm_instance(orthanc, study_uid: str, series_uid: str | None = None) -> tuple[str, str]:
    """study의 SM(WSI) 시리즈 첫 인스턴스 → (orthanc instance id, SeriesInstanceUID).

    series_uid 지정 시 해당 시리즈만 — 다중 슬라이드 study에서 주석이 엉뚱한
    슬라이드에 결합되는 것을 방지(뷰어는 활성 슬라이드의 시리즈를 보냄).
    """
    studies = (await orthanc.post(
        "/tools/find",
        json={"Level": "Study", "Query": {"StudyInstanceUID": study_uid}, "Expand": True},
    )).json()
    if not studies:
        raise NotFoundError("Study", study_uid)
    for series_id in studies[0].get("Series", []):
        sr = (await orthanc.get(f"/series/{series_id}")).json()
        tags = sr.get("MainDicomTags", {})
        if tags.get("Modality") != "SM" or not sr.get("Instances"):
            continue
        if series_uid and tags.get("SeriesInstanceUID") != series_uid:
            continue
        return sr["Instances"][0], tags.get("SeriesInstanceUID", "")
    raise NotFoundError("WSI(SM) series", series_uid or study_uid)


def _build_ann_bytes(source_json: dict, groups: list[dict], coordinate_type: str,
                     content_description: str, creator: str | None) -> tuple[bytes, dict]:
    """DICOM JSON 메타 → highdicom ANN 직렬화. CPU 바운드 — 스레드에서 실행."""
    # bulkdata(ICC 프로파일 등)는 주석 생성에 불필요 — 빈 값으로 대체(추가 fetch 없음)
    source = pydicom.Dataset.from_json(source_json, bulk_data_uri_handler=lambda *_a: b"")
    ann = build_bulk_annotations(
        source, groups,
        coordinate_type=coordinate_type,
        content_description=content_description,
        content_creator_name=creator,
    )
    buf = io.BytesIO()
    ann.save_as(buf, write_like_original=False)
    return buf.getvalue(), {
        "sop_instance_uid": str(ann.SOPInstanceUID),
        "series_instance_uid": str(ann.SeriesInstanceUID),
        "sop_class_uid": str(ann.SOPClassUID),   # 1.2.840.10008.5.1.4.1.1.91.1
    }


@router.post("/{study_uid}/annotations", summary="병리 WSI 벌크 주석 생성(DICOM ANN, Sup222)")
async def create_annotations(
    request: Request,
    study_uid: str,
    body: AnnotationsIn,
    user: Annotated[User, Depends(PathologyWriteRoles)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    orthanc = request.app.state.http_client
    inst_id, sm_series_uid = await _find_sm_instance(orthanc, study_uid, body.series_uid)

    # 소스 WSI 메타만 DICOMweb으로 로드 — /file 전체(픽셀 포함, 실 WSI는 GB급) 다운로드 금지
    inst = (await orthanc.get(f"/instances/{inst_id}")).json()
    sop_uid = inst.get("MainDicomTags", {}).get("SOPInstanceUID", "")
    meta_resp = await orthanc.get(
        f"/dicom-web/studies/{study_uid}/series/{sm_series_uid}/instances/{sop_uid}/metadata"
    )
    if meta_resp.status_code != 200:
        raise DicomUploadError(f"소스 WSI 메타 조회 실패: {meta_resp.status_code}")
    source_json = meta_resp.json()[0]

    try:
        ann_bytes, uids = await asyncio.to_thread(
            _build_ann_bytes,
            source_json,
            [g.model_dump() for g in body.groups],
            body.coordinate_type,
            body.content_description or "WeRU.B pathology annotations",
            user.full_name,
        )
    except ValueError as e:
        # 클라이언트 입력 오류 — 502(게이트웨이)가 아니라 400
        raise AppException(code="INVALID_ANNOTATION", message=str(e), status_code=400)

    resp = await orthanc.post(
        "/instances", content=ann_bytes, headers={"Content-Type": "application/dicom"}
    )
    if resp.status_code not in (200, 201):
        raise DicomUploadError(f"Orthanc 저장 실패: {resp.status_code}")

    logger.info("병리 ANN 생성: study=%s groups=%d sop=%s by=%s",
                study_uid, len(body.groups), uids["sop_instance_uid"], user.username)
    await _log_audit_entry(
        db, "PATHOLOGY_ANN_CREATED", "DicomStudy", "SUCCESS",
        str(user.id), user.full_name or user.username,   # audit_logs.user_id는 VARCHAR — str 필수
        {"study_instance_uid": study_uid, "sm_series_uid": sm_series_uid,
         "ann_sop_uid": uids["sop_instance_uid"], "groups": len(body.groups),
         "coordinate_type": body.coordinate_type},
    )
    return {**uids, "groups": len(body.groups), "orthanc": resp.json()}
