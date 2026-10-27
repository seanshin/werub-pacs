"""Structured Report API — BI-RADS, K-TIRADS, LI-RADS standardized reporting."""
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.core.config import settings
from app.core.database import get_db
from app.api.report import ReportReadRoles, _can_read_study  # 리포트 계열 동일 게이트·PHYSICIAN 스코프
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.services.structured_report_schemas import get_schema, list_schemas, calculate_category

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["구조화 리포트"])


async def _store_text_sr_in_orthanc(study_uid: str, findings: str, impression: str) -> str | None:
    """Build a standards-compliant text SR from the reading and store it in Orthanc.

    Best-effort: the DB structured record is primary; a failure here never fails
    the save. Fetches a source instance of the study as the SR's evidence.
    """
    if not study_uid or (not findings and not impression):
        return None
    try:
        from app.services.dicom_ai_standard import build_text_sr

        async with httpx.AsyncClient(
            base_url=settings.orthanc_url,
            auth=(settings.orthanc_username, settings.orthanc_password),
            timeout=30,
        ) as c:
            found = await c.post("/tools/find", json={"Level": "Study", "Query": {"StudyInstanceUID": study_uid}})
            studies = found.json() if found.status_code == 200 else []
            if not studies:
                return None
            study = (await c.get(f"/studies/{studies[0]}")).json()
            inst_id = None
            for series_id in study.get("Series", []):
                sr = await c.get(f"/series/{series_id}")
                insts = sr.json().get("Instances", []) if sr.status_code == 200 else []
                if insts:
                    inst_id = insts[0]
                    break
            if not inst_id:
                return None
            dicom_bytes = (await c.get(f"/instances/{inst_id}/file")).content
            sr_bytes = build_text_sr([dicom_bytes], findings=findings, impression=impression)
            resp = await c.post("/instances", content=sr_bytes, headers={"Content-Type": "application/dicom"})
            if resp.status_code in (200, 409):
                orthanc_id = resp.json().get("ID")
                logger.info(f"Standard text SR stored in Orthanc: {orthanc_id}")
                return orthanc_id
    except Exception as e:
        logger.warning(f"Text SR storage failed (non-critical): {e}")
    return None


async def _fetch_instance_by_sop(c, sop_uid: str):
    """Look up a SOP Instance UID in Orthanc and return its DICOM bytes (or None)."""
    r = await c.post("/tools/lookup", content=sop_uid)
    if r.status_code != 200:
        return None
    for hit in r.json():
        if hit.get("Type") == "Instance":
            return (await c.get(f"/instances/{hit['ID']}/file")).content
    return None


class KeyImageCreate(BaseModel):
    study_instance_uid: str | None = None
    sop_instance_uids: list[str]
    description: str | None = None


@router.post("/key-images", summary="핵심영상(Key Object Selection) 저장", status_code=201)
async def create_key_images(
    body: KeyImageCreate,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """판독의가 마킹한 핵심영상을 표준 KOS(88.59) 문서로 생성해 Orthanc에 저장."""
    from app.services.kos_service import build_kos

    if not body.sop_instance_uids:
        raise HTTPException(400, "핵심영상 SOP Instance UID가 필요합니다.")
    async with httpx.AsyncClient(
        base_url=settings.orthanc_url,
        auth=(settings.orthanc_username, settings.orthanc_password),
        timeout=30,
    ) as c:
        ref_bytes, missing = [], []
        for sop in body.sop_instance_uids:
            data = await _fetch_instance_by_sop(c, sop)
            (ref_bytes if data else missing).append(data if data else sop)
        if not ref_bytes:
            raise HTTPException(404, "참조 영상을 Orthanc에서 찾지 못했습니다.")
        kos_bytes = build_kos(
            ref_bytes, description=body.description or f"Key images selected by {user.username}"
        )
        resp = await c.post(
            "/instances", content=kos_bytes, headers={"Content-Type": "application/dicom"}
        )
        if resp.status_code not in (200, 409):
            raise HTTPException(502, "KOS 저장 실패")
        orthanc_id = resp.json().get("ID")
        logger.info(f"KOS stored in Orthanc: {orthanc_id} ({len(ref_bytes)} key images)")
        return {
            "orthanc_id": orthanc_id,
            "key_image_count": len(ref_bytes),
            "missing": missing,
        }


@router.get("/structured-schemas", summary="구조화 리포트 스키마 목록")
async def get_structured_schemas(
    user: User = Depends(get_current_user),
):
    """사용 가능한 구조화 리포트 스키마 목록 (BI-RADS, K-TIRADS, LI-RADS 등)."""
    return {"schemas": list_schemas()}


@router.get("/structured-schemas/{schema_type}", summary="구조화 리포트 스키마 상세")
async def get_structured_schema_detail(
    schema_type: str,
    user: User = Depends(get_current_user),
):
    """스키마 상세 (필드 정의, 카테고리 로직)."""
    schema = get_schema(schema_type)
    if not schema:
        raise HTTPException(404, f"Schema '{schema_type}' not found")
    return {"type": schema_type, **schema}


class StructuredReportCreate(BaseModel):
    report_id: str | None = None
    study_instance_uid: str | None = None
    schema_type: str  # bi-rads, k-tirads, li-rads, basic_diagnostic
    data: dict | None = None
    structured_data: dict | None = None  # alias for data (viewer compat)
    source: str | None = None


@router.post("/structured", summary="구조화 리포트 저장", status_code=201)
async def save_structured_report(
    body: StructuredReportCreate,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """구조화 데이터 저장 + 카테고리 자동 산출.

    기존 리포트(report_id)에 구조화 데이터를 연결합니다.
    report_id가 없으면 study_instance_uid로 리포트를 탐색합니다.
    """
    # Resolve data field (viewer sends structured_data, admin sends data)
    report_data = body.data or body.structured_data or {}

    # Resolve report_id from study_instance_uid if not provided
    report_id = body.report_id
    if not report_id and body.study_instance_uid:
        result = await db.execute(text(
            "SELECT id FROM reports WHERE study_instance_uid = :uid ORDER BY created_at DESC LIMIT 1"
        ), {"uid": body.study_instance_uid})
        row = result.first()
        if row:
            report_id = str(row[0])
        else:
            # Create a placeholder report for this study
            new_rid = str(uuid4())
            await db.execute(text("""
                INSERT INTO reports (id, study_instance_uid, patient_id, author_id, author_name, status, created_at, updated_at)
                VALUES (:id, :uid, '-', :author_id, :author_name, 'DRAFT', NOW(), NOW())
            """), {
                "id": new_rid, "uid": body.study_instance_uid,
                "author_id": str(user.id), "author_name": f"AI (SR)",
            })
            report_id = new_rid

    if not report_id:
        raise HTTPException(400, "report_id or study_instance_uid required")

    # For basic_diagnostic (AI analysis SR), skip schema validation
    if body.schema_type == "basic_diagnostic":
        narrative = ""
        if report_data.get("findings"):
            narrative += f"소견: {report_data['findings']}\n"
        if report_data.get("impression"):
            narrative += f"결론: {report_data['impression']}\n"

        now = datetime.now(timezone.utc)
        sr_id = str(uuid4())

        await db.execute(text("""
            INSERT INTO structured_report_data (id, report_id, schema_type, data, category, narrative, created_by, created_at)
            VALUES (:id, :rid, :schema, CAST(:data AS jsonb), :cat, :narrative, :user, :now)
            ON CONFLICT (report_id, schema_type) DO UPDATE
            SET data = CAST(:data AS jsonb), narrative = :narrative, updated_at = :now
        """), {
            "id": sr_id, "rid": report_id, "schema": body.schema_type,
            "data": json.dumps(report_data, ensure_ascii=False),
            "cat": "AI",
            "narrative": narrative.strip(),
            "user": str(user.id) if hasattr(user, 'id') else "",
            "now": now,
        })
        await db.commit()

        # Also persist a standards-compliant DICOM SR in Orthanc (F9 — the viewer's
        # "save as SR" now produces a real DICOM object, not just a DB record).
        sr_orthanc_id = await _store_text_sr_in_orthanc(
            body.study_instance_uid or "",
            report_data.get("findings", ""),
            report_data.get("impression", ""),
        )

        return {
            "id": sr_id,
            "schema_type": body.schema_type,
            "category": "AI",
            "narrative": narrative.strip(),
            "data": report_data,
            "source": body.source,
            "dicom_sr_orthanc_id": sr_orthanc_id,
        }

    schema = get_schema(body.schema_type)
    if not schema:
        raise HTTPException(400, f"Unknown schema: {body.schema_type}")

    # Calculate category
    result = calculate_category(body.schema_type, report_data)
    enriched_data = {**report_data, **result}

    # Generate narrative text from structured data
    narrative = _generate_narrative(body.schema_type, enriched_data, schema)

    now = datetime.now(timezone.utc)
    sr_id = str(uuid4())

    await db.execute(text("""
        INSERT INTO structured_report_data (id, report_id, schema_type, data, category, narrative, created_by, created_at)
        VALUES (:id, :rid, :schema, CAST(:data AS jsonb), :cat, :narrative, :user, :now)
        ON CONFLICT (report_id, schema_type) DO UPDATE
        SET data = CAST(:data AS jsonb), category = :cat, narrative = :narrative, updated_at = :now
    """), {
        "id": sr_id, "rid": report_id, "schema": body.schema_type,
        "data": json.dumps(enriched_data, ensure_ascii=False),
        "cat": result.get("category", ""),
        "narrative": narrative,
        "user": str(user.id) if hasattr(user, 'id') else "",
        "now": now,
    })
    await db.commit()

    logger.info(f"Structured report saved: {body.schema_type} → {result.get('category')}")

    return {
        "id": sr_id,
        "schema_type": body.schema_type,
        "category": result.get("category"),
        "recommendation": result.get("recommendation") or result.get("fna_recommendation") or result.get("management"),
        "narrative": narrative,
        "data": enriched_data,
    }


@router.get("/{report_id}/structured-data", summary="구조화 리포트 데이터 조회")
async def get_structured_data(
    report_id: str,
    user: User = Depends(ReportReadRoles),
    db: AsyncSession = Depends(get_db),
):
    """리포트에 연결된 구조화 데이터 조회.

    ★2026-08-03: 여기가 `get_current_user`뿐이라 **v13.8의 리포트 보호를 우회**했다 —
    `/reports`는 RESEARCHER에게 403인데 `/reports/{id}/structured-data`는 200이었다.
    구조화 데이터는 리포트 소견(BI-RADS 등)이므로 리포트 본문과 같은 게이트를 쓴다:
    ReportReadRoles + PHYSICIAN은 본인 의뢰 study만(`_can_read_study`, report_pdf와 동일).
    """
    # 소속 study를 찾아 스코프 검사 — 리포트가 없으면 노출할 것도 없다
    rep = (await db.execute(text(
        "SELECT study_instance_uid FROM reports WHERE id = :rid"
    ), {"rid": report_id})).mappings().first()
    if not rep:
        raise HTTPException(404, "리포트를 찾을 수 없습니다.")
    if not await _can_read_study(db, user, rep["study_instance_uid"]):
        raise HTTPException(403, "본인이 의뢰한 환자의 리포트만 열람할 수 있습니다.")

    result = await db.execute(text("""
        SELECT id, schema_type, data, category, narrative, created_at
        FROM structured_report_data
        WHERE report_id = :rid
        ORDER BY created_at DESC
    """), {"rid": report_id})
    rows = [dict(r._mapping) for r in result]

    return {"report_id": report_id, "structured_reports": rows}


def _generate_narrative(schema_type: str, data: dict, schema: dict) -> str:
    """Generate Korean narrative text from structured data."""
    if schema_type == "bi-rads":
        parts = [f"측: {data.get('side', '-')}"]
        if data.get("mass_present") == "있음":
            parts.append(f"종괴: {data.get('mass_shape', '-')}, 경계 {data.get('mass_margin', '-')}, {data.get('mass_size_mm', '?')}mm")
        else:
            parts.append("종괴: 없음")
        parts.append(f"석회화: {data.get('calcification', '없음')}")
        if data.get("axillary_ln") == "비대":
            parts.append("액와 림프절 비대")
        parts.append(f"\nBI-RADS Category {data.get('category', '?')}")
        parts.append(f"권고: {data.get('recommendation', '-')}")
        return "\n".join(parts)

    elif schema_type == "k-tirads":
        parts = [f"위치: {data.get('side', '-')}"]
        parts.append(f"크기: {data.get('nodule_size_mm', '?')}mm")
        parts.append(f"구성: {data.get('composition', '-')}, 에코: {data.get('echogenicity', '-')}")
        parts.append(f"모양: {data.get('shape', '-')}, 경계: {data.get('margin', '-')}")
        parts.append(f"석회화: {data.get('calcification', '없음')}")
        parts.append(f"\nK-TIRADS {data.get('category', '?')}")
        parts.append(f"FNA: {data.get('fna_recommendation', '-')}")
        return "\n".join(parts)

    elif schema_type == "li-rads":
        parts = [f"크기: {data.get('observation_size_mm', '?')}mm"]
        parts.append(f"동맥기 과조영증강: {data.get('arterial_hyperenhancement', '-')}")
        parts.append(f"비변연부 씻김: {data.get('nonperipheral_washout', '-')}")
        parts.append(f"조영증강 캡슐: {data.get('enhancing_capsule', '-')}")
        parts.append(f"\n{data.get('category', '?')}")
        parts.append(f"관리: {data.get('management', '-')}")
        return "\n".join(parts)

    return json.dumps(data, ensure_ascii=False, indent=2)
