"""AI-assisted radiology reading API.

Integrates with WeRUB AI Server (MedGemma) to provide:
- Auto-analysis + draft report creation
- Prior study comparison
- AI server health monitoring
- Patient-friendly findings explanation
"""
import io
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger, _log_audit_entry
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, OrthancError
from app.core.security import RequireRole, get_current_user
from app.models.report import Report, ReportStatus
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["ai-assist"])

AI_SERVER_URL = settings.ai_server_url
AI_API_KEY = settings.ai_api_key
AI_AUTH_HEADERS = {"Authorization": f"Bearer {AI_API_KEY}"}
AI_MEDICAL_HEADERS = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}


# ── Schemas ──

class AnalyzeAndDraftRequest(BaseModel):
    study_instance_uid: str
    series_instance_uid: str | None = None
    modality: str | None = None
    template_id: str | None = None
    auto_create_report: bool = True
    model_name: str | None = None  # AI model to use; None → GPU server default (MedGemma)


class CompareRequest(BaseModel):
    current_study_uid: str
    prior_study_uid: str | None = None  # Auto-find if not provided
    modality: str | None = None


class ExplainRequest(BaseModel):
    findings: str
    target: str = "patient"  # patient or referring


class SOAPRequest(BaseModel):
    """SOAP 요약 요청."""
    findings: str
    impression: str | None = None
    clinical_info: str | None = None
    patient_age: int | None = None
    patient_sex: str | None = None


class DifferentialRequest(BaseModel):
    """감별진단 요청."""
    symptoms: str
    findings: str | None = None
    patient_age: int | None = None
    patient_sex: str | None = None


class CompareReportRequest(BaseModel):
    """GPU 서버 비교 판독 보고서 요청."""
    current_study_uid: str
    prior_study_uid: str
    modality: str | None = None
    clinical_info: str | None = None


# ── Helper ──

def _pixels_to_jpeg(ds) -> bytes:
    """첫 프레임을 JPEG로 디코드 — Orthanc /preview가 415를 반환하는
    PALETTE COLOR 멀티프레임 US 등 비일반 photometric 대응."""
    import numpy as np
    from PIL import Image
    from pydicom.pixels import apply_color_lut, apply_voi_lut

    arr = ds.pixel_array
    if int(getattr(ds, "NumberOfFrames", 1) or 1) > 1:
        arr = arr[0]
    photometric = str(getattr(ds, "PhotometricInterpretation", ""))
    if photometric == "PALETTE COLOR":
        arr = apply_color_lut(arr, ds)
    elif photometric.startswith("MONOCHROME"):
        arr = apply_voi_lut(arr, ds)
        if photometric == "MONOCHROME1":
            arr = arr.max() - arr
    arr = arr.astype(np.float32)
    lo, hi = float(arr.min()), float(arr.max())
    if hi > lo:
        arr = (arr - lo) / (hi - lo) * 255.0
    img = Image.fromarray(arr.astype(np.uint8)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def _get_study_jpeg(client: httpx.AsyncClient, study_uid: str) -> tuple[bytes, dict]:
    """Get first instance JPEG from Orthanc by StudyInstanceUID."""
    find_resp = await client.post("/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": study_uid},
    })
    studies = find_resp.json() if find_resp.status_code == 200 else []
    if not studies:
        raise NotFoundError(resource="Study", resource_id=study_uid)

    study_id = studies[0]
    study_resp = await client.get(f"/studies/{study_id}")
    study = study_resp.json()
    patient_tags = study.get("PatientMainDicomTags", {})
    main_tags = study.get("MainDicomTags", {})

    # Get first instance
    for series_id in study.get("Series", []):
        sr = await client.get(f"/series/{series_id}")
        if sr.status_code != 200:
            continue
        instances = sr.json().get("Instances", [])
        if not instances:
            continue
        info = {
            "patient_id": patient_tags.get("PatientID", ""),
            "patient_name": patient_tags.get("PatientName", ""),
            "modality": sr.json().get("MainDicomTags", {}).get("Modality", ""),
            "study_description": main_tags.get("StudyDescription", ""),
            "study_date": main_tags.get("StudyDate", ""),
            "orthanc_study_id": study_id,
        }
        preview = await client.get(f"/instances/{instances[0]}/preview")
        if preview.status_code == 200:
            return preview.content, info
        # Orthanc가 렌더하지 못하는 photometric(PALETTE COLOR 등) → 원본을 pydicom으로 직접 디코드
        file_resp = await client.get(f"/instances/{instances[0]}/file")
        if file_resp.status_code == 200:
            try:
                import pydicom

                ds = pydicom.dcmread(io.BytesIO(file_resp.content))
                return _pixels_to_jpeg(ds), info
            except Exception as exc:  # 압축 TS 등 디코드 불가 시 다음 시리즈 시도
                logger.warning("pydicom decode fallback failed for instance %s: %s", instances[0], exc)

    raise NotFoundError(resource="Instance", resource_id="viewable")


async def _call_medical_analyze(image_bytes: bytes, modality: str, body_part: str = "",
                                clinical_info: str = "", model_name: str | None = None) -> dict:
    """Call WeRUB Medical Vision API. ``model_name`` selects the model; when
    omitted the GPU server uses its default (MedGemma)."""
    modality_map = {"CR": "xray", "DX": "xray", "CT": "ct", "MR": "mri", "US": "ultrasound",
                    "MG": "xray", "XA": "xray", "RF": "xray", "PT": "ct", "NM": "ct"}
    api_modality = modality_map.get(modality, "xray")

    data = {"modality": api_modality, "language": "ko"}
    if body_part:
        data["body_part"] = body_part
    if clinical_info:
        data["clinical_info"] = clinical_info
    if model_name:
        data["model"] = model_name

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{AI_SERVER_URL}/api/vision/medical/analyze",
            headers=AI_AUTH_HEADERS,
            files={"image": ("image.jpg", image_bytes, "image/jpeg")},
            data=data,
        )
        if resp.status_code == 200:
            return resp.json()
        # Log error details
        error_body = resp.text[:200]
        logger.error(f"AI Server error {resp.status_code}: {error_body}")
        raise OrthancError(message=f"AI 분석 실패 ({resp.status_code}): {error_body}")


# ── Endpoints ──

@router.post("/precheck")
@AuditLogger.log("AI_ASSIST_PRECHECK", "Study")
async def precheck_study(
    body: AnalyzeAndDraftRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],  # audit decorator용
    user: Annotated[User, Depends(get_current_user)],
):
    """AI 분석 가능 여부 사전 검증.

    Orthanc에서 영상 JPEG를 추출하고 GPU 서버의 precheck API로 검증합니다.
    의료 영상 적합성, 해상도, 선명도, 모달리티 자동 감지 결과를 반환합니다.
    """
    orthanc = request.app.state.http_client

    try:
        img_bytes, study_info = await _get_study_jpeg(orthanc, body.study_instance_uid)
    except Exception:
        return {"suitable": False, "reason": "영상을 불러올 수 없습니다.", "study_uid": body.study_instance_uid}

    modality = body.modality or study_info.get("modality", "")
    modality_map = {"CR": "xray", "DX": "xray", "CT": "ct", "MR": "mri", "US": "ultrasound"}
    expected = modality_map.get(modality, "")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            data = {}
            if expected:
                data["expected_modality"] = expected
            resp = await client.post(
                f"{AI_SERVER_URL}/api/vision/medical/precheck",
                headers=AI_AUTH_HEADERS,
                files={"image": ("image.jpg", img_bytes, "image/jpeg")},
                data=data,
            )
            if resp.status_code == 200:
                result = resp.json()
                result["study_info"] = study_info
                return result
            return {"suitable": False, "reason": f"Precheck 서버 오류 ({resp.status_code})", "study_info": study_info}
    except Exception as e:
        return {"suitable": False, "reason": f"Precheck 서버 연결 실패: {e}", "study_info": study_info}


@router.post("/analyze-and-draft")
@AuditLogger.log("AI_ASSIST_ANALYZE", "Study")
async def analyze_and_draft(
    body: AnalyzeAndDraftRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """AI 영상 분석 + 판독문 초안 자동 생성.

    1. Orthanc에서 영상 JPEG 추출
    2. MedGemma로 분석 (소견/판독소견/권고)
    3. 판독 리포트 초안 자동 생성 (draft)
    """
    orthanc = request.app.state.http_client

    # Get image
    img_bytes, study_info = await _get_study_jpeg(orthanc, body.study_instance_uid)
    modality = body.modality or study_info.get("modality", "CR")

    # Detect body part from study description
    desc = (study_info.get("study_description") or "").lower()
    body_part = ""
    if "chest" in desc or "lung" in desc: body_part = "chest"
    elif "abdomen" in desc or "liver" in desc: body_part = "abdomen"
    elif "brain" in desc or "head" in desc: body_part = "brain"
    elif "spine" in desc or "lumbar" in desc or "cervical" in desc: body_part = "spine"
    elif "knee" in desc or "shoulder" in desc or "extremity" in desc: body_part = "extremity"

    # Call AI (optional caller-selected model)
    ai_result = await _call_medical_analyze(img_bytes, modality, body_part=body_part,
                                            model_name=body.model_name)

    findings = ai_result.get("findings", "")
    impression = ai_result.get("impression", "")
    recommendations = ai_result.get("recommendations", "")

    result = {
        "ai_analysis": {
            "findings": findings,
            "impression": impression,
            "recommendations": recommendations,
            "model": ai_result.get("model", "medgemma"),
            "duration_ms": ai_result.get("duration_ms", 0),
            "body_part": ai_result.get("body_part", ""),
        },
        "study_info": study_info,
    }

    # Auto-create report draft
    if body.auto_create_report:
        # Check existing report
        existing = await db.execute(
            select(Report).where(Report.study_instance_uid == body.study_instance_uid)
        )
        report = existing.scalar_one_or_none()

        if report and report.status in ("draft", ReportStatus.DRAFT.value):
            # Update existing draft
            report.findings = findings
            report.impression = impression
            report.recommendation = recommendations
            report.ai_findings = ai_result
        elif not report:
            # Create new draft
            report = Report(
                study_instance_uid=body.study_instance_uid,
                orthanc_study_id=study_info.get("orthanc_study_id"),
                patient_id=study_info.get("patient_id", "-"),
                patient_name=study_info.get("patient_name"),
                modality=modality,
                study_date=study_info.get("study_date"),
                study_description=study_info.get("study_description"),
                findings=findings,
                impression=impression,
                recommendation=recommendations,
                status=ReportStatus.DRAFT,
                urgency="normal",
                author_id=user.id,
                author_name=f"AI ({ai_result.get('model', 'MedGemma')})",
                ai_findings=ai_result,
            )
            db.add(report)

        await db.commit()
        if report:
            await db.refresh(report)
            result["report_id"] = str(report.id)
            result["report_status"] = report.status

    return result


@router.post("/compare-studies")
@AuditLogger.log("AI_ASSIST_COMPARE", "Study")
async def compare_studies(
    body: CompareRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """이전 검사와 비교 분석.

    이전 Study UID가 없으면 동일 환자의 가장 최근 이전 검사를 자동 탐색.
    """
    orthanc = request.app.state.http_client

    # Get current image
    current_img, current_info = await _get_study_jpeg(orthanc, body.current_study_uid)
    modality = body.modality or current_info.get("modality", "CR")

    # Find prior study if not specified
    prior_uid = body.prior_study_uid
    if not prior_uid:
        patient_id = current_info.get("patient_id")
        if patient_id:
            find_resp = await orthanc.post("/tools/find", json={
                "Level": "Study",
                "Query": {"PatientID": patient_id},
            })
            study_ids = find_resp.json() if find_resp.status_code == 200 else []
            for sid in study_ids:
                sr = await orthanc.get(f"/studies/{sid}")
                if sr.status_code == 200:
                    s = sr.json()
                    s_uid = s.get("MainDicomTags", {}).get("StudyInstanceUID", "")
                    if s_uid != body.current_study_uid:
                        prior_uid = s_uid
                        break

    if not prior_uid:
        return {
            "comparison": None,
            "message": "이전 검사를 찾을 수 없습니다.",
            "current_analysis": (await _call_medical_analyze(current_img, modality)),
        }

    # Get prior image
    prior_img, prior_info = await _get_study_jpeg(orthanc, prior_uid)

    # Analyze both
    current_analysis = await _call_medical_analyze(current_img, modality)
    prior_analysis = await _call_medical_analyze(prior_img, modality)

    # Simple comparison
    current_findings = current_analysis.get("findings", "")
    prior_findings = prior_analysis.get("findings", "")

    comparison_text = (
        f"[현재 검사] {current_findings}\n\n"
        f"[이전 검사] {prior_findings}\n\n"
        f"[비교 소견] "
    )

    if current_findings == prior_findings:
        comparison_text += "이전 검사 대비 유의한 변화 없음 (stable)."
        progression = "stable"
    else:
        comparison_text += "이전 검사 대비 변화가 관찰됩니다. 판독의 확인이 필요합니다."
        progression = "changed"

    return {
        "comparison": {
            "text": comparison_text,
            "progression": progression,
            "current_date": current_info.get("study_date"),
            "prior_date": prior_info.get("study_date"),
        },
        "current_analysis": current_analysis,
        "prior_analysis": prior_analysis,
        "prior_study_uid": prior_uid,
    }


@router.get("/auto-draft/config")
async def get_auto_draft_config(user: Annotated[User, Depends(get_current_user)]):
    """AI 자동 판독 초안 설정 조회."""
    from sqlalchemy import text
    from app.core.database import get_db
    # Use async_session directly
    from app.core.database import async_session
    if async_session:
        async with async_session() as db:
            try:
                result = await db.execute(text("SELECT value FROM openpacs_config WHERE key = 'ai_auto_draft'"))
                row = result.scalar_one_or_none()
                if row:
                    import json
                    return json.loads(row) if isinstance(row, str) else row
            except Exception:
                pass
    return {"enabled": False, "modalities": ["CR", "DX", "CT", "MR"], "min_series": 1}


@router.put("/auto-draft/config")
async def update_auto_draft_config(
    body: dict,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """AI 자동 판독 초안 설정 변경. Admin only."""

    import json
    from sqlalchemy import text
    from app.core.database import async_session
    if async_session:
        async with async_session() as db:
            val = json.dumps(body, ensure_ascii=False)
            # ★전후 대조는 쓰기 **전에** 스냅샷(v13.38 규칙) — 설정 감사의 가치는
            #   "무엇이 무엇으로" 바뀌었는지에 있다.
            prev = (await db.execute(
                text("SELECT value FROM openpacs_config WHERE key = 'ai_auto_draft'")
            )).scalar()
            await db.execute(text("""
                INSERT INTO openpacs_config (key, value, updated_by)
                VALUES ('ai_auto_draft', :val, :user)
                ON CONFLICT (key) DO UPDATE SET value = :val, updated_by = :user, updated_at = NOW()
            """), {"val": val, "user": user.username})
            await db.commit()

            # 이 EP는 형제(precheck·analyze·compare·explain)가 모두 @AuditLogger.log를
            # 달고 있는데 혼자 빠져 있었다(v13.46 스윕에서 발견). **어느 모달리티가
            # 자동 초안 대상인지**를 바꾸는 설정이라 임상 동작에 직접 영향이 있다.
            # 데코레이터를 쓸 수 없다 — 이 핸들러는 `db` 의존성 없이 자체 세션을 열고,
            # 데코레이터는 kwargs에 db·user가 없으면 조용히 스킵한다(v13.30 함정).
            await _log_audit_entry(
                db=db, operation="AI_AUTO_DRAFT_CONFIG_UPDATED",
                resource_type="Config", status="SUCCESS",
                user_id=str(user.id), username=user.username,
                resource_id="ai_auto_draft",
                details={"before": prev, "after": val},
            )
    return {"status": "ok", "message": "AI 자동 초안 설정 저장됨"}


@router.get("/server-status")
async def ai_server_status(user: Annotated[User, Depends(get_current_user)]):
    """AI 서버 (GPU) 상태 조회."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            health = await client.get(f"{AI_SERVER_URL}/api/health", headers=AI_AUTH_HEADERS)
            if health.status_code == 200:
                data = health.json()
                return {
                    "server_url": AI_SERVER_URL,
                    "healthy": data.get("healthy", False),
                    "checks": data.get("checks", {}),
                    "ollama_running": data.get("checks", {}).get("ollama", {}).get("ok", False),
                }
            return {"server_url": AI_SERVER_URL, "healthy": False, "error": f"HTTP {health.status_code}"}
    except Exception as e:
        return {"server_url": AI_SERVER_URL, "healthy": False, "error": str(e)}


@router.post("/explain-findings")
@AuditLogger.log("AI_ASSIST_EXPLAIN", "Report")
async def explain_findings(
    body: ExplainRequest,
    db: Annotated[AsyncSession, Depends(get_db)],  # audit decorator용
    user: Annotated[User, Depends(get_current_user)],
):
    """AI 소견을 환자가 이해하기 쉬운 말로 설명."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{AI_SERVER_URL}/api/medical/explain",
                headers=AI_MEDICAL_HEADERS,
                json={"text": body.findings, "target": body.target},
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.HTTPError:
        pass
    # 공개판: 실패를 성공처럼 감싸지 않는다 — 원문을 「설명」 칸에 대신 넣지 않고 오류로 알린다
    raise HTTPException(502, "AI 설명 서비스를 사용할 수 없습니다(원문을 설명으로 대신 보여 주지 않습니다)")


@router.post("/soap-summary")
@AuditLogger.log("AI_ASSIST_SOAP", "Report")
async def soap_summary(
    body: SOAPRequest,
    db: Annotated[AsyncSession, Depends(get_db)],  # audit decorator용
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """판독 소견 → SOAP 요약 생성.

    WeRUB Medical AI의 /api/medical/summarize 호출.
    """
    record_text = f"소견: {body.findings}"
    if body.impression:
        record_text += f"\n판독소견: {body.impression}"
    if body.clinical_info:
        record_text += f"\n임상정보: {body.clinical_info}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{AI_SERVER_URL}/api/medical/summarize",
                headers=AI_MEDICAL_HEADERS,
                json={
                    "text": record_text,
                    "patient_age": body.patient_age,
                    "patient_sex": body.patient_sex,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"AI 서버 응답 오류: {resp.status_code}", "soap": None}
    except Exception as e:
        logger.error(f"SOAP summary failed: {e}")
        return {"error": "AI 서버 연결 실패", "soap": None}


@router.post("/differential-diagnosis")
@AuditLogger.log("AI_ASSIST_DDX", "Report")
async def differential_diagnosis(
    body: DifferentialRequest,
    db: Annotated[AsyncSession, Depends(get_db)],  # audit decorator용
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """감별진단 Top 3 + ICD-10 코드.

    WeRUB Medical AI의 /api/medical/analyze 호출.
    """
    symptoms = body.symptoms
    if body.findings:
        symptoms += f"\n영상 소견: {body.findings}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{AI_SERVER_URL}/api/medical/analyze",
                headers=AI_MEDICAL_HEADERS,
                json={
                    "symptoms": symptoms,
                    "patient_age": body.patient_age,
                    "patient_sex": body.patient_sex,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"AI 서버 응답 오류: {resp.status_code}", "diagnoses": []}
    except Exception as e:
        logger.error(f"Differential diagnosis failed: {e}")
        return {"error": "AI 서버 연결 실패", "diagnoses": []}


@router.post("/compare-report")
@AuditLogger.log("AI_ASSIST_COMPARE_RPT", "Study")
async def compare_report(
    body: CompareReportRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],  # audit decorator용
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """GPU 서버 비교 판독 보고서 생성.

    현재/이전 영상을 GPU 서버의 /api/vision/medical/report로 전송하여
    AI 기반 비교 판독 보고서를 생성.
    """
    orthanc = request.app.state.http_client

    # Get both images
    try:
        current_img, current_info = await _get_study_jpeg(orthanc, body.current_study_uid)
        prior_img, prior_info = await _get_study_jpeg(orthanc, body.prior_study_uid)
    except HTTPException:
        raise
    except Exception as e:
        raise NotFoundError(resource="Instance")

    modality = body.modality or current_info.get("modality", "CR")
    modality_map = {"CR": "xray", "DX": "xray", "CT": "ct", "MR": "mri", "US": "ultrasound"}
    api_modality = modality_map.get(modality, "xray")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{AI_SERVER_URL}/api/vision/medical/report",
                headers=AI_AUTH_HEADERS,
                files=[
                    ("current_image", ("current.jpg", current_img, "image/jpeg")),
                    ("previous_image", ("prior.jpg", prior_img, "image/jpeg")),
                ],
                data={
                    "modality": api_modality,
                    "clinical_info": body.clinical_info or "",
                    "language": "ko",
                },
            )
            if resp.status_code == 200:
                result = resp.json()
                result["current_study"] = {
                    "uid": body.current_study_uid,
                    "date": current_info.get("study_date"),
                    "description": current_info.get("study_description"),
                }
                result["prior_study"] = {
                    "uid": body.prior_study_uid,
                    "date": prior_info.get("study_date"),
                    "description": prior_info.get("study_description"),
                }
                return result
            raise OrthancError(message=f"AI 서버 비교 분석 오류: {resp.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Compare report failed: {e}")
        raise OrthancError(message=f"AI 서버 연결 실패: {e}")


class ApplyAIResultRequest(BaseModel):
    """AI 결과를 리포트에 직접 저장."""
    study_instance_uid: str
    findings: str = ""
    impression: str = ""
    recommendation: str = ""


@router.post("/apply-to-report")
@AuditLogger.log("AI_APPLY_TO_REPORT", "Report")
async def apply_ai_to_report(
    body: ApplyAIResultRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """AI/파이프라인 결과를 리포트에 직접 저장 (upsert).

    기존 draft 리포트가 있으면 업데이트, 없으면 새로 생성.
    """
    existing = await db.execute(
        select(Report).where(Report.study_instance_uid == body.study_instance_uid)
    )
    report = existing.scalar_one_or_none()

    # Allow updating draft and preliminary reports (not final/addendum)
    editable = ("draft", "preliminary", ReportStatus.DRAFT.value, ReportStatus.PRELIMINARY.value)
    if report and report.status in editable:
        # Only overwrite non-empty fields to avoid clearing existing content
        if body.findings:
            report.findings = body.findings
        if body.impression:
            report.impression = body.impression
        if body.recommendation:
            report.recommendation = body.recommendation
    elif not report:
        report = Report(
            study_instance_uid=body.study_instance_uid,
            findings=body.findings,
            impression=body.impression,
            recommendation=body.recommendation,
            status=ReportStatus.DRAFT,
            urgency="normal",
            author_id=user.id,
            author_name=f"AI Pipeline ({user.username})",
        )
        db.add(report)

    await db.commit()
    if report:
        await db.refresh(report)
        return {"status": "ok", "report_id": str(report.id), "findings": report.findings[:100]}
    return {"status": "ok"}
