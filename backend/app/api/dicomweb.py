"""DICOMweb API wrapper with validation and normalization integration."""
import asyncio
import io
import os
from typing import Annotated

import pydicom
from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger, _log_audit_entry
from app.core.cache import invalidate_on_write, cached
from app.core.cache_config import CACHE_PATTERN_WORKLIST, CACHE_PATTERN_ORTHANC, CACHE_TTL_ORTHANC
from app.core.database import get_db
from app.core.exceptions import (
    DicomUploadError,
    DicomValidationError,
    DicomNormalizationError,
    NormalizationFailedError,
    RevalidationFailedError,
    NotFoundError,
)
from app.core.security import get_current_user, RequireRole, decode_token, decode_hospitalrun_token
from app.models.audit import AuditAction
from app.models.user import User, Role
from app.services.dicom_validator import DicomValidator
from app.services.dicom_normalizer import DicomNormalizer
from app.services.korean_search import is_chosung_query, filter_by_chosung

# Map normalizer category strings to audit action constants
_CATEGORY_TO_AUDIT_ACTION: dict[str, str] = {
    "pixel_spacing": AuditAction.DICOM_NORMALIZED_PIXEL_SPACING,
    "tag": AuditAction.DICOM_NORMALIZED_TAGS,
    "photometric": AuditAction.DICOM_NORMALIZED_PHOTOMETRIC,
    "charset": AuditAction.DICOM_NORMALIZED_CHARSET,
}

router = APIRouter(prefix="/api/v1/dicomweb", tags=["dicomweb"])

# 스터디/이미지 조회(QIDO/WADO)는 RESEARCHER(비임상·연구용, PHI 열거 금지)를 제외 —
# 리포트 ReportReadRoles(v13.8)와 동일 취지. SERVICE(LIS 연동)·임상 역할만.
# RESIDENT는 RequireRole이 RADIOLOGIST로 승격. (M3: 저권한 역할의 MRN/이름/DOB 열거 차단)
StudyReadRoles = RequireRole(
    Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN, Role.TECHNOLOGIST, Role.SERVICE
)

validator = DicomValidator()
normalizer = DicomNormalizer()


@router.get("/studies")
@cached(ttl=CACHE_TTL_ORTHANC, key_prefix="pacs:orthanc:studies")
async def qido_studies(
    request: Request,
    user: Annotated[User, Depends(StudyReadRoles)],
    PatientID: str | None = Query(None),
    PatientName: str | None = Query(None),
    StudyDate: str | None = Query(None),
    ModalitiesInStudy: str | None = Query(None),
    AccessionNumber: str | None = Query(None),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """QIDO-RS: Query studies with filters using Orthanc server-side search."""
    # Build Orthanc /tools/find query for server-side filtering
    query = {}
    if PatientID:
        query["PatientID"] = PatientID
    chosung_filter = None
    if PatientName:
        if is_chosung_query(PatientName):
            chosung_filter = PatientName  # Handle after fetch
        else:
            query["PatientName"] = f"*{PatientName}*"
    if StudyDate:
        query["StudyDate"] = StudyDate
    if ModalitiesInStudy:
        query["ModalitiesInStudy"] = ModalitiesInStudy
    if AccessionNumber:
        query["AccessionNumber"] = AccessionNumber

    if query:
        resp = await request.app.state.http_client.post(
            "/tools/find",
            json={"Level": "Study", "Query": query, "Expand": True, "Limit": limit,
                  "RequestedTags": ["ModalitiesInStudy"]},  # QIDO modalities — RequestedTags로만 채워짐
        )
    else:
        # No filters — get all study IDs and expand individually
        id_resp = await request.app.state.http_client.get("/studies", params={"since": offset, "limit": limit})
        study_ids = id_resp.json() if id_resp.status_code == 200 and isinstance(id_resp.json(), list) else []
        studies_data = []
        for sid in study_ids:
            sr = await request.app.state.http_client.get(f"/studies/{sid}", params={"requestedTags": "ModalitiesInStudy"})
            if sr.status_code == 200:
                studies_data.append(sr.json())
        resp = None

    studies = resp.json() if resp and resp.status_code == 200 else (studies_data if not query else [])

    # Apply chosung filter if needed
    if chosung_filter and studies:
        studies = [s for s in studies if filter_by_chosung(
            [{"PatientName": s.get("PatientMainDicomTags", {}).get("PatientName", "")}],
            chosung_filter
        )]

    filtered = []
    for study in studies:
        main_tags = study.get("MainDicomTags", {})
        patient_tags = study.get("PatientMainDicomTags", {})

        filtered.append({
            "orthanc_id": study.get("ID"),
            "study_instance_uid": main_tags.get("StudyInstanceUID"),
            "study_date": main_tags.get("StudyDate"),
            "study_time": main_tags.get("StudyTime"),
            "study_description": main_tags.get("StudyDescription"),
            "accession_number": main_tags.get("AccessionNumber"),
            "referring_physician": main_tags.get("ReferringPhysicianName"),
            "patient_id": patient_tags.get("PatientID"),
            "patient_name": patient_tags.get("PatientName"),
            "patient_birth_date": patient_tags.get("PatientBirthDate"),
            "patient_sex": patient_tags.get("PatientSex"),
            "series_count": len(study.get("Series", [])),
            "modalities": study.get("RequestedTags", {}).get("ModalitiesInStudy", ""),
            "is_stable": study.get("IsStable"),
        })

    return {"count": len(filtered), "results": filtered}


@router.get("/studies/{study_uid}/series")
@cached(ttl=CACHE_TTL_ORTHANC, key_prefix="pacs:orthanc:series")
async def qido_series(request: Request, study_uid: str, user: Annotated[User, Depends(StudyReadRoles)]):
    """QIDO-RS: List series for a study."""
    # Find study by UID
    resp = await request.app.state.http_client.post(
        "/tools/find",
        json={"Level": "Study", "Query": {"StudyInstanceUID": study_uid}, "Expand": True},
    )
    studies = resp.json()
    if not studies:
        raise NotFoundError("Study", study_uid)

    study = studies[0]
    series_list = []
    for series_id in study.get("Series", []):
        sr = await request.app.state.http_client.get(f"/series/{series_id}")
        if sr.status_code == 200:
            s = sr.json()
            tags = s.get("MainDicomTags", {})
            series_list.append({
                "orthanc_id": s.get("ID"),
                "series_instance_uid": tags.get("SeriesInstanceUID"),
                "series_number": tags.get("SeriesNumber"),
                "series_description": tags.get("SeriesDescription"),
                "modality": tags.get("Modality"),
                "body_part": tags.get("BodyPartExamined"),
                "instance_count": len(s.get("Instances", [])),
            })

    return {"study_uid": study_uid, "count": len(series_list), "series": series_list}


@router.get("/studies/{study_uid}/series/{series_uid}")
@cached(ttl=CACHE_TTL_ORTHANC, key_prefix="pacs:orthanc:series:detail")
async def qido_series_detail(
    request: Request,
    study_uid: str,
    series_uid: str,
    user: Annotated[User, Depends(StudyReadRoles)],
):
    """QIDO-RS: Get metadata for a specific series."""
    resp = await request.app.state.http_client.post(
        "/tools/find",
        json={"Level": "Series", "Query": {"SeriesInstanceUID": series_uid}, "Expand": True},
    )
    series_list = resp.json()
    if not series_list:
        raise NotFoundError("Series", series_uid)

    s = series_list[0]
    tags = s.get("MainDicomTags", {})
    return {
        "orthanc_id": s.get("ID"),
        "study_uid": study_uid,
        "series_instance_uid": tags.get("SeriesInstanceUID"),
        "series_number": tags.get("SeriesNumber"),
        "series_description": tags.get("SeriesDescription"),
        "modality": tags.get("Modality"),
        "body_part": tags.get("BodyPartExamined"),
        "instance_count": len(s.get("Instances", [])),
    }


@router.get("/studies/{study_uid}/series/{series_uid}/instances")
@cached(ttl=CACHE_TTL_ORTHANC, key_prefix="pacs:orthanc:instances")
async def qido_instances(
    request: Request,
    study_uid: str,
    series_uid: str,
    user: Annotated[User, Depends(StudyReadRoles)],
):
    """QIDO-RS: List instances (SOP instances) for a series."""
    resp = await request.app.state.http_client.post(
        "/tools/find",
        json={"Level": "Series", "Query": {"SeriesInstanceUID": series_uid}, "Expand": True},
    )
    series_list = resp.json()
    if not series_list:
        raise NotFoundError("Series", series_uid)

    s = series_list[0]
    instances_data = []
    for instance_id in s.get("Instances", []):
        ir = await request.app.state.http_client.get(f"/instances/{instance_id}")
        if ir.status_code == 200:
            inst = ir.json()
            inst_tags = inst.get("MainDicomTags", {})
            instances_data.append({
                "orthanc_id": inst.get("ID"),
                "sop_instance_uid": inst_tags.get("SOPInstanceUID"),
                "instance_number": inst_tags.get("InstanceNumber"),
                "sop_class_uid": inst_tags.get("SOPClassUID"),
            })

    return {
        "study_uid": study_uid,
        "series_uid": series_uid,
        "count": len(instances_data),
        "instances": instances_data,
    }


# ---------------------------------------------------------------------------
# QIDO-RS 표준 DICOMweb passthrough (인증 게이트) — LIS 등 표준 DICOMweb 커넥터용.
# 위의 /studies 등은 admin UI용 커스텀 JSON({count,results}). 표준 태그키 응답이
# 필요한 외부 연동은 이 /rs/* 를 쓴다: svc-lis JWT로 인증 → Orthanc DICOMweb 표준
# 응답(application/dicom+json)을 그대로 전달. 무인증 edge /dicom-web을 우회 불필요.
# ---------------------------------------------------------------------------
async def _dicomweb_passthrough(request: Request, orthanc_path: str) -> Response:
    # multi_items(): 표준 QIDO는 includefield 등을 반복 키로 보냄 — dict()는 마지막 값만 남겨
    # 태그 누락. 반복 파라미터를 그대로 전달.
    resp = await request.app.state.http_client.get(
        f"/dicom-web/{orthanc_path}", params=list(request.query_params.multi_items())
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/dicom+json"),
    )


@router.get("/_authcheck", include_in_schema=False)
async def dicomweb_authcheck(request: Request):
    """nginx `auth_request` 대상 — 무인증 `/dicom-web` edge를 토큰 게이트로 보호(P1).
    프레임 로딩마다 호출되므로 **경량**: JWT 서명+만료만 검증(DB 미조회). 유효 토큰이면
    200, 아니면 401. Bearer 토큰은 뷰어 userAuthenticationService가 주입."""
    auth = request.headers.get("authorization") or ""
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return Response(status_code=401)
    token = parts[1]
    # get_current_user가 수용하는 토큰과 동일 집합을 수용(단, per-frame이라 DB/blacklist/idle 생략).
    # ① OpenPACS 네이티브 HS256 — type=="access"만(refresh 토큰 7일 배제, get_current_user와 동일)
    try:
        payload = decode_token(token)
        if payload and payload.get("type") == "access" and "sub" in payload:
            # RESEARCHER(native-only 역할)는 PHI-bearing 이미지 edge 접근 금지 — 백엔드
            # StudyReadRoles와 일관(M3). SSO 토큰은 HIS_ROLE_MAP상 researcher가 될 수 없음.
            if str(payload.get("role", "")).lower() == "researcher":
                return Response(status_code=401)
            return Response(status_code=200)
    except Exception:
        pass
    # ② HIS 공통 SSO(RS256/JWKS 또는 레거시 HS256) — ★뷰어가 SSO 로그인 시 pacs_token에 이 토큰을
    #    넣으므로(admin/page.tsx) 이걸 빠뜨리면 SSO 사용자의 프레임이 전부 401→뷰어 블랙. JWKS는
    #    캐시되나 cold 시 동기 httpx라 스레드 오프로딩(이벤트루프 블로킹 방지, get_current_user와 동일).
    try:
        his = await asyncio.to_thread(decode_hospitalrun_token, token)
        if his and his.get("sub"):
            return Response(status_code=200)
    except Exception:
        pass
    # 성능 주석: blacklist(로그아웃)/idle 생략은 의도된 트레이드오프 — access 60분 만료 + nginx
    # auth_request 캐시(≤60s)가 노출창 상한. 강한 폐기 필요 시 nginx 캐시 TTL을 줄일 것.
    return Response(status_code=401)


@router.get("/rs/studies", summary="QIDO-RS 표준(태그키) — 인증 스터디 검색")
async def qido_rs_studies(request: Request, user: Annotated[User, Depends(StudyReadRoles)]):
    """표준 DICOMweb QIDO-RS. 쿼리 파라미터(AccessionNumber·PatientID·limit·includefield…)를
    Orthanc DICOMweb으로 전달하고 표준 응답을 그대로 반환."""
    return await _dicomweb_passthrough(request, "studies")


@router.get("/rs/studies/{study_uid}/series", summary="QIDO-RS 표준 — 시리즈 목록")
async def qido_rs_series(request: Request, study_uid: str,
                         user: Annotated[User, Depends(StudyReadRoles)]):
    return await _dicomweb_passthrough(request, f"studies/{study_uid}/series")


@router.get("/rs/studies/{study_uid}/series/{series_uid}/instances",
            summary="QIDO-RS 표준 — 인스턴스 목록")
async def qido_rs_instances(request: Request, study_uid: str, series_uid: str,
                            user: Annotated[User, Depends(StudyReadRoles)]):
    return await _dicomweb_passthrough(request, f"studies/{study_uid}/series/{series_uid}/instances")


@router.post("/studies")
@invalidate_on_write(CACHE_PATTERN_WORKLIST, CACHE_PATTERN_ORTHANC)
@AuditLogger.log("DICOM_UPLOAD", "DicomStudy")
async def stow_rs(
    request: Request,
    # STOW-RS 아카이브 쓰기 — 임상 수집 역할만(RESEARCHER/PHYSICIAN 주입 차단, S9)
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False))],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    validate: str = Query("warn", regex="^(strict|warn|off)$"),
    auto_normalize: bool = Query(False),
):
    """STOW-RS: Upload DICOM file with automatic validation and optional auto-normalization.

    Invalidates worklist and Orthanc metadata caches.

    Query parameters:
    - validate: Validation mode (strict|warn|off). Default: warn
      - strict: reject if any critical or error findings
      - warn: accept with warnings logged
      - off: skip validation
    - auto_normalize: Automatically correct safe DICOM issues. Default: false
      - true: apply safe corrections (Pixel Spacing, missing recommended tags)
      - false: skip normalization
    """
    data = await file.read()
    original_data = data  # Keep original for potential re-use

    report = None
    normalization_result = None

    # Phase 2: Validate before normalization
    if validate != "off":
        report = validator.validate(data)

        if validate == "strict" and not report.accepted:
            raise DicomValidationError(
                message="DICOM validation failed",
                details={
                    "sop_instance_uid": report.sop_instance_uid,
                    "max_severity": report.max_severity.value if report.max_severity else None,
                    "findings": [
                        {"severity": f.severity.value, "rule_code": f.rule_code, "message": f.message}
                        for f in report.findings
                        if f.severity.value in ("critical", "error")
                    ],
                },
            )
        elif validate == "warn" and not report.accepted:
            raise DicomValidationError(
                message="DICOM validation failed",
                details={
                    "sop_instance_uid": report.sop_instance_uid,
                    "max_severity": report.max_severity.value if report.max_severity else None,
                    "findings": [
                        {"severity": f.severity.value, "rule_code": f.rule_code, "message": f.message}
                        for f in report.findings
                        if f.severity.value in ("critical", "error")
                    ],
                },
            )

    # Phase 3: Normalize (optional)
    # Respect DICOM_NORMALIZATION_ENABLED env var (default: enabled)
    normalization_enabled = os.environ.get("DICOM_NORMALIZATION_ENABLED", "true").lower() != "false"
    if auto_normalize and normalization_enabled and report is not None:
        try:
            ds = pydicom.dcmread(io.BytesIO(data), force=True)
            normalization_result = await normalizer.normalize(ds, report, original_data)

            if normalization_result.error:
                raise NormalizationFailedError(
                    message="DICOM normalization failed",
                    details={"error": normalization_result.error},
                )

            # Re-serialize normalized dataset
            buf = io.BytesIO()
            ds.save_as(buf)
            data = buf.getvalue()

            # Re-validate post-normalization
            report = validator.validate(data)
            if not report.accepted:
                raise RevalidationFailedError(
                    message="DICOM still invalid after normalization",
                    details={
                        "sop_instance_uid": report.sop_instance_uid,
                        "findings": [
                            {"severity": f.severity.value, "rule_code": f.rule_code, "message": f.message}
                            for f in report.findings
                            if f.severity.value in ("critical", "error")
                        ]
                    },
                )

            # Audit: log each normalization change
            for change in normalization_result.changes:
                audit_action = _CATEGORY_TO_AUDIT_ACTION.get(
                    change.category, f"DICOM_NORMALIZED_{change.category.upper()}"
                )
                await _log_audit_entry(
                    db=db,
                    operation=audit_action,
                    resource_type="DicomInstance",
                    status="SUCCESS",
                    user_id=str(user.id),
                    username=user.username,
                    details={
                        "resource_id": report.sop_instance_uid,
                        "study_instance_uid": report.study_instance_uid,
                        "tag_keyword": change.tag_keyword,
                        "original_value": change.original_value,
                        "corrected_value": change.corrected_value,
                        "rationale": change.rationale,
                        "risk_level": change.risk_level,
                    },
                )

        except (NormalizationFailedError, RevalidationFailedError):
            raise
        except pydicom.errors.InvalidDicomError as e:
            raise NormalizationFailedError(
                message="Failed to normalize DICOM: invalid DICOM file",
                details={"error": str(e)},
            )

    # Store in Orthanc
    resp = await request.app.state.http_client.post(
        "/instances",
        content=data,
        headers={"Content-Type": "application/dicom"},
    )

    if resp.status_code not in (200, 409):
        raise DicomUploadError(
            message="Failed to store DICOM instance in Orthanc",
            details={"orthanc_status": resp.status_code, "filename": file.filename},
        )

    result = resp.json()
    response: dict = {
        "status": "stored",
        "orthanc_id": result.get("ID"),
    }

    if report is not None:
        response.update({
            "sop_instance_uid": report.sop_instance_uid,
            "study_instance_uid": report.study_instance_uid,
            "validation": {
                "accepted": report.accepted,
                "validate_mode": validate,
                "warnings": report.warning_count,
                "info": report.info_count,
                "findings": [
                    {"severity": f.severity.value, "rule_code": f.rule_code, "message": f.message}
                    for f in report.findings
                    if f.severity.value in ("warning", "error")
                ],
            },
        })
    else:
        response["validation"] = {"accepted": True, "validate_mode": "off"}

    # Add normalization details to response
    if normalization_result is not None:
        response["normalization"] = {
            "applied": normalization_result.modified,
            "elapsed_ms": normalization_result.elapsed_ms,
            "changes": [
                {
                    "tag": c.tag_keyword,
                    "original": c.original_value,
                    "corrected": c.corrected_value,
                    "rationale": c.rationale,
                    "risk_level": c.risk_level,
                }
                for c in normalization_result.changes
            ] if normalization_result.modified else [],
        }
    else:
        response["normalization"] = {"applied": False}

    return response


@router.get("/studies/{study_uid}/series/{series_uid}/instances/{instance_uid}")
@cached(ttl=CACHE_TTL_ORTHANC, key_prefix="pacs:orthanc:instances:detail")
async def wado_rs_instance_detail(
    request: Request,
    study_uid: str,
    series_uid: str,
    instance_uid: str,
    user: Annotated[User, Depends(StudyReadRoles)],
):
    """WADO-RS: Get instance-level metadata (SOP class, rows, columns, photometric interpretation)."""
    resp = await request.app.state.http_client.post(
        "/tools/find",
        json={"Level": "Instance", "Query": {"SOPInstanceUID": instance_uid}, "Expand": True},
    )
    instances = resp.json()
    if not instances:
        raise NotFoundError("Instance", instance_uid)

    inst = instances[0]
    tags = inst.get("MainDicomTags", {})
    return {
        "orthanc_id": inst.get("ID"),
        "study_uid": study_uid,
        "series_uid": series_uid,
        "sop_instance_uid": tags.get("SOPInstanceUID"),
        "sop_class_uid": tags.get("SOPClassUID"),
        "instance_number": tags.get("InstanceNumber"),
        "rows": tags.get("Rows"),
        "columns": tags.get("Columns"),
        "bits_allocated": tags.get("BitsAllocated"),
        "bits_stored": tags.get("BitsStored"),
        "photometric_interpretation": tags.get("PhotometricInterpretation"),
        "transfer_syntax_uid": inst.get("TransferSyntax") or "",
    }


@router.get("/studies/{study_uid}/series/{series_uid}/instances/{instance_uid}/frames")
async def wado_rs_frames(
    request: Request,
    study_uid: str,
    series_uid: str,
    instance_uid: str,
    user: Annotated[User, Depends(StudyReadRoles)],
):
    """WADO-RS: Multiframe instance support (returns frame count and metadata for CT/MR)."""
    resp = await request.app.state.http_client.post(
        "/tools/find",
        json={"Level": "Instance", "Query": {"SOPInstanceUID": instance_uid}, "Expand": True},
    )
    instances = resp.json()
    if not instances:
        raise NotFoundError("Instance", instance_uid)

    inst = instances[0]
    tags = inst.get("MainDicomTags", {})
    frame_count = int(tags.get("NumberOfFrames", 1))

    return {
        "orthanc_id": inst.get("ID"),
        "instance_uid": instance_uid,
        "modality": tags.get("Modality"),
        "frame_count": frame_count,
        "rows": tags.get("Rows"),
        "columns": tags.get("Columns"),
    }


@router.get("/wado")
async def wado_uri_legacy(
    request: Request,
    user: Annotated[User, Depends(StudyReadRoles)],
    StudyInstanceUID: str = Query(...),
    SeriesInstanceUID: str | None = Query(None),
    SOPInstanceUID: str | None = Query(None),
):
    """WADO-URI (legacy) endpoint for backward compatibility.

    Maps DICOM UIDs to Orthanc IDs and returns DICOM instance as binary.
    Query parameters must include StudyInstanceUID; optionally SeriesInstanceUID and SOPInstanceUID.
    """
    # Build query for Orthanc tools/find
    query = {"StudyInstanceUID": StudyInstanceUID}
    if SeriesInstanceUID:
        query["SeriesInstanceUID"] = SeriesInstanceUID
    if SOPInstanceUID:
        query["SOPInstanceUID"] = SOPInstanceUID

    # Find instance(s) matching the UID criteria
    resp = await request.app.state.http_client.post(
        "/tools/find",
        json={"Level": "Instance", "Query": query, "Expand": False},
    )

    instance_ids = resp.json() if resp.status_code == 200 else []
    if not instance_ids:
        raise NotFoundError("Instance via WADO-URI", f"Study={StudyInstanceUID}")

    # Fetch the first matching instance as binary DICOM file
    orthanc_instance_id = instance_ids[0]
    file_resp = await request.app.state.http_client.get(
        f"/instances/{orthanc_instance_id}/file"
    )

    if file_resp.status_code != 200:
        raise NotFoundError("Instance file", orthanc_instance_id)

    return StreamingResponse(
        iter([file_resp.content]),
        media_type="application/dicom",
        headers={"Content-Disposition": f"attachment; filename={orthanc_instance_id}.dcm"},
    )
