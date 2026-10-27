"""Dashboard statistics API."""
import asyncio
import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func, case, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import ClinicalPHIReadRoles, get_current_user
from app.models.ai import InferenceJob, JobStatus
from app.models.report import Report, ReportStatus
from app.models.user import User
from app.models.worklist import ProcedureStatus, WorklistItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/today")
async def today_stats(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Today's PACS statistics."""
    today = date.today()

    # Orthanc stats (single request)
    try:
        orthanc_resp = await request.app.state.http_client.get("/statistics")
        orthanc = orthanc_resp.json() if orthanc_resp.status_code == 200 else {}
    except Exception:
        logger.warning("Failed to fetch Orthanc statistics")
        orthanc = {}

    # Worklist today — DB aggregation
    wl_status = await db.execute(
        select(WorklistItem.status, func.count())
        .where(WorklistItem.scheduled_date == today)
        .group_by(WorklistItem.status)
    )
    wl_modality = await db.execute(
        select(WorklistItem.modality, func.count())
        .where(WorklistItem.scheduled_date == today)
        .group_by(WorklistItem.modality)
    )
    wl_by_status = dict(wl_status.all())
    wl_by_modality = dict(wl_modality.all())
    wl_total = sum(wl_by_status.values())

    # Reports — DB aggregation
    rpt_stats = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((Report.status.in_(["draft", ReportStatus.DRAFT.value]), 1), else_=0)).label("pending"),
            func.sum(case((Report.urgency == "urgent", 1), else_=0)).label("urgent"),
        )
    )
    rpt = rpt_stats.one()

    rpt_today = await db.execute(
        select(func.count())
        .where(Report.status.in_(["final", ReportStatus.FINAL.value]))
        .where(cast(Report.created_at, Date) == today)
    )
    completed_today = rpt_today.scalar() or 0

    # AI — DB aggregation
    ai_today = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((InferenceJob.status == JobStatus.COMPLETED.value, 1), else_=0)).label("completed"),
            func.sum(case((InferenceJob.is_critical.is_(True), 1), else_=0)).label("critical"),
        ).where(cast(InferenceJob.created_at, Date) == today)
    )
    ai = ai_today.one()

    return {
        "date": str(today),
        "pacs": {
            "total_patients": orthanc.get("CountPatients", 0),
            "total_studies": orthanc.get("CountStudies", 0),
            "total_instances": orthanc.get("CountInstances", 0),
            "disk_size_mb": orthanc.get("TotalDiskSizeMB", 0),
        },
        "worklist_today": {
            "total": wl_total,
            "by_status": wl_by_status,
            "by_modality": wl_by_modality,
        },
        "reading": {
            "pending": rpt.pending or 0,
            "completed_today": completed_today,
            "urgent": rpt.urgent or 0,
            "total_reports": rpt.total or 0,
        },
        "ai": {
            "jobs_today": ai.total or 0,
            "completed": ai.completed or 0,
            "critical_findings": ai.critical or 0,
        },
    }


@router.get("/reading-queue")
async def reading_queue(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalPHIReadRoles)],
    status_filter: str | None = Query(None),
    study_uid_q: str | None = Query(None, alias="study_uid"),
):
    """Reading queue — studies with reading status."""
    client = request.app.state.http_client

    # 성능: 전체 study 메타를 1콜로 조회(기존 1+N 개별 GET ~0.5s → /tools/find Expand ~11ms).
    # RequestedTags로 ModalitiesInStudy까지 포함 → 시리즈 폴백 N+1도 제거.
    try:
        resp = await client.post("/tools/find", json={
            "Level": "Study", "Query": {}, "Expand": True, "Limit": 100,
            "RequestedTags": ["ModalitiesInStudy"],
        })
        orthanc_studies = resp.json() if resp.status_code == 200 and isinstance(resp.json(), list) else []
    except Exception:
        logger.warning("Failed to fetch studies from Orthanc")
        orthanc_studies = []

    # 현재 윈도우 study UID만 — 전 테이블 풀로드 금지(reports/provenance는 5년 보존으로
    # 수만~수십만 행 성장, 핫패스에서 언바운드 SELECT는 메모리·p95 선형 악화)
    window_uids = [s.get("MainDicomTags", {}).get("StudyInstanceUID") for s in orthanc_studies]
    window_uids = [u for u in window_uids if u]
    from app.models.dicom_issue import StudyProvenance
    if window_uids:
        rpt_result = await db.execute(
            select(Report).where(Report.study_instance_uid.in_(window_uids)))
        reports = {r.study_instance_uid: r for r in rpt_result.scalars().all()}
        prov_result = await db.execute(
            select(StudyProvenance).where(StudyProvenance.study_instance_uid.in_(window_uids)))
        provenances = {p.study_instance_uid: p for p in prov_result.scalars().all()}
    else:
        reports, provenances = {}, {}

    ORIGIN_LABELS = {
        "internal": "원내", "external": "원외", "patient_upload": "환자",
        "kiosk": "키오스크", "test_data": "테스트", "research": "연구",
        "ai_generated": "AI", "migration": "이관", "unknown": "미분류",
    }

    AI_MODALITIES = {"CT", "CR", "DX", "MR", "US", "MG", "XA", "RF", "PT", "NM"}

    queue = []
    for study in orthanc_studies:
        main_tags = study.get("MainDicomTags", {})
        patient_tags = study.get("PatientMainDicomTags", {})
        study_uid = main_tags.get("StudyInstanceUID", "")
        # Single-study lookup (reading view fetches studyInfo by study_uid)
        if study_uid_q and study_uid != study_uid_q:
            continue

        # 성능: ModalitiesInStudy는 RequestedTags(Expand)에 포함 → 시리즈 폴백 N+1 제거
        modality = (study.get("RequestedTags", {}).get("ModalitiesInStudy", "")
                    or main_tags.get("ModalitiesInStudy", ""))

        report = reports.get(study_uid)
        read_status = report.status if report else "unread"
        urgency = report.urgency or "normal" if report else "normal"

        if status_filter and read_status != status_filter:
            continue

        # Calculate SLA elapsed time for unread studies
        study_date_str = main_tags.get("StudyDate", "")
        study_time_str = main_tags.get("StudyTime", "")
        sla_minutes = None
        sla_level = None  # normal, warning (30m), critical (60m)
        if read_status == "unread" and study_date_str:
            try:
                from datetime import datetime, timezone
                st = study_time_str[:6] if study_time_str else "000000"
                study_dt = datetime.strptime(f"{study_date_str}{st}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - study_dt).total_seconds() / 60
                if elapsed <= 1440:  # 24시간 이내만 SLA 표시
                    sla_minutes = int(elapsed)
                    if elapsed >= 60:
                        sla_level = "critical"
                    elif elapsed >= 30:
                        sla_level = "warning"
                    else:
                        sla_level = "normal"
            except Exception:
                pass

        queue.append({
            "orthanc_id": study.get("ID"),
            "study_instance_uid": study_uid,
            "patient_name": patient_tags.get("PatientName"),
            "patient_id": patient_tags.get("PatientID"),
            "study_date": main_tags.get("StudyDate"),
            "study_time": main_tags.get("StudyTime"),
            "study_description": main_tags.get("StudyDescription"),
            "modality": modality or None,
            "ai_available": any(m in AI_MODALITIES for m in modality.upper().replace("\\", ",").split(",")) if modality else False,
            "accession_number": main_tags.get("AccessionNumber"),
            "series_count": len(study.get("Series", [])),
            "read_status": read_status,
            "urgency": urgency,
            "report_id": str(report.id) if report else None,
            "reader": report.author_name if report else None,
            "viewer_url": f"/viewer/?StudyInstanceUIDs={study_uid}",
            "origin": provenances[study_uid].origin if study_uid in provenances else None,
            "origin_label": ORIGIN_LABELS.get(provenances[study_uid].origin, "") if study_uid in provenances else None,
            "source_institution": provenances[study_uid].source_institution if study_uid in provenances else None,
            "sla_minutes": sla_minutes,
            "sla_level": sla_level,
        })

    # Sort: urgent first, then unread
    priority_order = {"urgent": 0, "stat": 0, "unread": 1, "draft": 2, "preliminary": 3, "final": 4}
    queue.sort(key=lambda q: (
        priority_order.get(q["urgency"] if q["urgency"] in ("urgent", "stat") else q["read_status"], 5),
        q.get("study_date") or "",
    ))

    return {
        "total": len(queue),
        "unread": sum(1 for q in queue if q["read_status"] == "unread"),
        "queue": queue,
    }
