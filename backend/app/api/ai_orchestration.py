"""AI Orchestration Platform API — 다중 모델 파이프라인 관리/실행/비교.

WeRU.B AI Server v2.50.0 Orchestration Platform 프록시 + PACS 자체 기능:
- 파이프라인 CRUD (생성/조회/수정/삭제/복제)
- 실험 실행 (debug, test, compare)
- 버전 관리 (자동 백업, 롤백)
- 프로덕션 승격 (판독/응급/자동초안 연동)
- 품질 평가 (판독의 평가)
- 실행 이력 (PACS Study 연결)
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.audit import AuditLog
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/orchestration", tags=["ai-orchestration"])

AI_SERVER_URL = settings.ai_server_url
AI_API_KEY = settings.ai_api_key
AI_HEADERS = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}


# ── Helpers ──

async def _ai_get(path: str, timeout: float = 15.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{AI_SERVER_URL}{path}", headers=AI_HEADERS)
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"AI 서버 오류 ({resp.status_code})", "detail": resp.text[:300]}


async def _ai_post(path: str, json_body: dict, timeout: float = 120.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{AI_SERVER_URL}{path}", headers=AI_HEADERS, json=json_body)
        if resp.status_code in (200, 201):
            return resp.json()
        return {"error": f"AI 서버 오류 ({resp.status_code})", "detail": resp.text[:300]}


async def _ai_put(path: str, json_body: dict, timeout: float = 30.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.put(f"{AI_SERVER_URL}{path}", headers=AI_HEADERS, json=json_body)
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"AI 서버 오류 ({resp.status_code})", "detail": resp.text[:300]}


async def _ai_delete(path: str, timeout: float = 15.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.delete(f"{AI_SERVER_URL}{path}", headers=AI_HEADERS)
        if resp.status_code in (200, 204):
            return resp.json() if resp.text else {"status": "deleted"}
        return {"error": f"AI 서버 오류 ({resp.status_code})", "detail": resp.text[:300]}


# ── Schemas ──

class StageConfig(BaseModel):
    model: str = Field(..., description="모델명 (e.g. medgemma:4b)")
    role: str = Field(..., description="단계 역할 (e.g. 소견 추출)")
    system: str | None = Field(None, description="시스템 프롬프트")
    on_fail: str = Field("abort", description="abort / continue / skip")
    retry: int = Field(0, ge=0, le=3)
    fallback_model: str | None = None


class PipelineCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    stages: list[StageConfig] = Field(..., min_length=1, max_length=5)
    description: str | None = None


class PipelineUpdateRequest(BaseModel):
    stages: list[StageConfig] = Field(..., min_length=1, max_length=5)
    description: str | None = None


class RunRequest(BaseModel):
    pipeline: str
    input: str | None = None
    study_instance_uid: str | None = None
    debug: bool = False


class TestRequest(BaseModel):
    pipeline: str
    mode: str = Field("validate", description="validate / dry_run / full_test")
    input: str | None = None


class CompareRequest(BaseModel):
    pipelines: list[str] = Field(..., min_length=2, max_length=3)
    input: str | None = None
    study_instance_uid: str | None = None


class PromoteRequest(BaseModel):
    target: str = Field(..., description="reading / emergency / auto_draft")


class EvaluateRequest(BaseModel):
    quality_score: int = Field(..., ge=1, le=5)
    note: str | None = None


# ═══════════════════════════════════════════════════
# 1. 파이프라인 CRUD (AI 서버 프록시)
# ═══════════════════════════════════════════════════

@router.get("/pipelines")
async def list_pipelines(user: Annotated[User, Depends(get_current_user)]):
    """파이프라인 목록 (builtin + custom)."""
    result = await _ai_get("/api/orchestration/pipelines")
    if result.get("error"):
        return result

    # Normalize response — AI server returns {pipelines: [{builtin: {}, custom: {}}]}
    pipelines = []
    raw = result.get("pipelines", result)
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        for group_type in ("builtin", "custom"):
            group = raw[0].get(group_type, {})
            if isinstance(group, dict):
                for name, stages in group.items():
                    pipelines.append({
                        "name": name,
                        "stages": stages if isinstance(stages, list) else [],
                        "is_builtin": group_type == "builtin",
                    })
    elif isinstance(raw, dict):
        for group_type in ("builtin", "custom"):
            group = raw.get(group_type, {})
            if isinstance(group, dict):
                for name, stages in group.items():
                    pipelines.append({
                        "name": name,
                        "stages": stages if isinstance(stages, list) else [],
                        "is_builtin": group_type == "builtin",
                    })

    # Enrich custom pipelines with stage details (list API returns empty stages for custom)
    for p in pipelines:
        if not p.get("is_builtin") and not p.get("stages"):
            detail = await _ai_get(f"/api/orchestration/pipeline/{p['name']}")
            if not detail.get("error") and detail.get("stages"):
                p["stages"] = detail["stages"]
                p["description"] = detail.get("description", "")

    return {"pipelines": pipelines, "count": len(pipelines)}


@router.get("/pipelines/{name}")
async def get_pipeline(
    name: str,
    user: Annotated[User, Depends(get_current_user)],
):
    """파이프라인 상세."""
    return await _ai_get(f"/api/orchestration/pipeline/{name}")


@router.post("/pipelines")
async def create_pipeline(
    body: PipelineCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """파이프라인 생성 (최대 5단계). Admin only."""
    payload = {
        "name": body.name,
        "stages": [s.model_dump(exclude_none=True) for s in body.stages],
    }
    if body.description:
        payload["description"] = body.description

    result = await _ai_post("/api/orchestration/pipeline", payload)

    if not result.get("error"):
        audit = AuditLog(
            user_id=str(user.id), username=user.username,
            action="PIPELINE_CREATED", resource_type="Pipeline",
            resource_id=body.name,
            details={"stages": len(body.stages), "models": [s.model for s in body.stages]},
        )
        db.add(audit)
        await db.commit()

    return result


@router.put("/pipelines/{name}")
async def update_pipeline(
    name: str,
    body: PipelineUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """파이프라인 수정 (이전 버전 자동 백업). Admin only."""
    payload = {"stages": [s.model_dump(exclude_none=True) for s in body.stages]}
    if body.description:
        payload["description"] = body.description

    result = await _ai_put(f"/api/orchestration/pipeline/{name}", payload)

    if not result.get("error"):
        audit = AuditLog(
            user_id=str(user.id), username=user.username,
            action="PIPELINE_UPDATED", resource_type="Pipeline",
            resource_id=name,
            details={"stages": len(body.stages)},
        )
        db.add(audit)
        await db.commit()

    return result


@router.delete("/pipelines/{name}")
async def delete_pipeline(
    name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """파이프라인 삭제. Admin only."""
    result = await _ai_delete(f"/api/orchestration/pipeline/{name}")

    if not result.get("error"):
        audit = AuditLog(
            user_id=str(user.id), username=user.username,
            action="PIPELINE_DELETED", resource_type="Pipeline",
            resource_id=name, details={},
        )
        db.add(audit)
        await db.commit()

    return result


@router.post("/pipelines/{name}/clone")
async def clone_pipeline(
    name: str,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """파이프라인 복제 (builtin 포함). Admin only."""
    return await _ai_post(f"/api/orchestration/pipeline/{name}/clone", {})


@router.get("/pipelines/{name}/versions")
async def pipeline_versions(
    name: str,
    user: Annotated[User, Depends(get_current_user)],
):
    """파이프라인 버전 목록."""
    return await _ai_get(f"/api/orchestration/pipeline/{name}/versions")


@router.post("/pipelines/{name}/rollback")
async def rollback_pipeline(
    name: str,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    version: int = Query(..., ge=1),
):
    """이전 버전 복원. Admin only."""
    return await _ai_post(f"/api/orchestration/pipeline/{name}/rollback?version={version}", {})


# ═══════════════════════════════════════════════════
# 2. 실험 실행 / 테스트 / 비교
# ═══════════════════════════════════════════════════

@router.post("/run")
async def run_pipeline(
    body: RunRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """파이프라인 실행 (PACS Study 연결 가능).

    debug=true 시 각 단계 중간 결과 포함.
    study_instance_uid 지정 시 Orthanc에서 영상 소견을 자동 추출하여 입력.
    """
    input_text = body.input or ""

    # If study_uid provided, get study info as input context
    if body.study_instance_uid and not input_text:
        try:
            orthanc = request.app.state.http_client
            from app.api.ai_assist import _get_study_jpeg, _call_medical_analyze
            img_bytes, study_info = await _get_study_jpeg(orthanc, body.study_instance_uid)
            modality = study_info.get("modality", "CR")
            ai_result = await _call_medical_analyze(img_bytes, modality)
            # 환자명/환자ID는 프롬프트에서 의도적으로 제외 — 추론에 불필요한
            # 직접 식별자 (데이터 최소화, arch-invariants 감사 후속)
            input_text = (
                f"검사: {study_info.get('study_description', '')} ({modality})\n"
                f"소견: {ai_result.get('findings', '')}\n"
                f"판독소견: {ai_result.get('impression', '')}"
            )
        except Exception as e:
            logger.warning(f"Study context extraction failed: {e}")

    payload = {"pipeline": body.pipeline, "input": input_text, "debug": body.debug}
    result = await _ai_post("/api/orchestration/run", payload)

    # Record in PACS audit
    if not result.get("error"):
        audit = AuditLog(
            user_id=str(user.id), username=user.username,
            action="PIPELINE_RUN", resource_type="Pipeline",
            resource_id=body.pipeline,
            details={
                "run_id": result.get("run_id"),
                "study_uid": body.study_instance_uid,
                "debug": body.debug,
                "duration_ms": result.get("total_duration_ms"),
            },
        )
        db.add(audit)
        await db.commit()

    return result


@router.post("/test")
async def test_pipeline(
    body: TestRequest,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """파이프라인 테스트.

    - validate: 모델 존재 + VRAM 확인
    - dry_run: 1단계만 실행
    - full_test: 전체 실행 + 품질 검증
    """
    payload = {"pipeline": body.pipeline, "mode": body.mode}
    if body.input:
        payload["input"] = body.input
    return await _ai_post("/api/orchestration/test", payload)


@router.post("/compare")
async def compare_pipelines(
    body: CompareRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """A/B 비교 — 2~3개 파이프라인 동시 실행.

    동일 입력으로 여러 파이프라인을 실행하고 결과를 나란히 비교.
    study_instance_uid 지정 시 자동 영상 소견 추출.
    """
    input_text = body.input or ""

    if body.study_instance_uid and not input_text:
        try:
            orthanc = request.app.state.http_client
            from app.api.ai_assist import _get_study_jpeg, _call_medical_analyze
            img_bytes, study_info = await _get_study_jpeg(orthanc, body.study_instance_uid)
            modality = study_info.get("modality", "CR")
            ai_result = await _call_medical_analyze(img_bytes, modality)
            # 환자명/환자ID는 프롬프트에서 의도적으로 제외 — 추론에 불필요한
            # 직접 식별자 (데이터 최소화, arch-invariants 감사 후속)
            input_text = (
                f"검사: {study_info.get('study_description', '')} ({modality})\n"
                f"소견: {ai_result.get('findings', '')}\n"
                f"판독소견: {ai_result.get('impression', '')}"
            )
        except Exception as e:
            logger.warning(f"Study context extraction failed: {e}")

    payload = {"pipelines": body.pipelines, "input": input_text}
    result = await _ai_post("/api/orchestration/compare", payload, timeout=180.0)

    if not result.get("error"):
        audit = AuditLog(
            user_id=str(user.id), username=user.username,
            action="PIPELINE_COMPARED", resource_type="Pipeline",
            resource_id=",".join(body.pipelines),
            details={"study_uid": body.study_instance_uid, "pipeline_count": len(body.pipelines)},
        )
        db.add(audit)
        await db.commit()

    return result


@router.get("/runs")
async def list_runs(
    user: Annotated[User, Depends(get_current_user)],
    pipeline: str | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    """실행 이력 목록."""
    path = f"/api/orchestration/runs?limit={limit}"
    if pipeline:
        path += f"&pipeline={pipeline}"
    return await _ai_get(path)


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: Annotated[User, Depends(get_current_user)],
):
    """실행 결과 상세."""
    return await _ai_get(f"/api/orchestration/run/{run_id}")


# ═══════════════════════════════════════════════════
# 3. 프로덕션 승격 / 품질 평가
# ═══════════════════════════════════════════════════

@router.post("/pipelines/{name}/promote")
async def promote_pipeline(
    name: str,
    body: PromoteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))],
):
    """파이프라인을 프로덕션 워크플로우에 승격.

    target: reading(판독), emergency(응급), auto_draft(자동초안)
    """
    import json
    config_key = f"orchestration_production_{body.target}"
    config_val = json.dumps({"pipeline": name, "promoted_by": user.username,
                             "promoted_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
    try:
        await db.execute(text("""
            INSERT INTO openpacs_config (key, value, updated_by)
            VALUES (:key, :val, :user)
            ON CONFLICT (key) DO UPDATE SET value = :val, updated_by = :user, updated_at = NOW()
        """), {"key": config_key, "val": config_val, "user": user.username})

        audit = AuditLog(
            user_id=str(user.id), username=user.username,
            action="PIPELINE_PROMOTED", resource_type="Pipeline",
            resource_id=name, details={"target": body.target},
        )
        db.add(audit)
        await db.commit()
    except Exception as e:
        return {"error": str(e)}

    return {"status": "promoted", "pipeline": name, "target": body.target}


@router.get("/production")
async def get_production_pipelines(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """현재 프로덕션 파이프라인 조회."""
    import json
    result = {}
    for target in ["reading", "emergency", "auto_draft"]:
        try:
            row = await db.execute(text(
                "SELECT value FROM openpacs_config WHERE key = :key"
            ), {"key": f"orchestration_production_{target}"})
            val = row.scalar_one_or_none()
            if val:
                result[target] = json.loads(val) if isinstance(val, str) else val
            else:
                result[target] = None
        except Exception:
            result[target] = None
    return result


@router.post("/runs/{run_id}/evaluate")
async def evaluate_run(
    run_id: str,
    body: EvaluateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """실행 결과 품질 평가 (1~5점)."""
    audit = AuditLog(
        user_id=str(user.id), username=user.username,
        action="PIPELINE_EVALUATED", resource_type="PipelineRun",
        resource_id=run_id,
        details={"quality_score": body.quality_score, "note": body.note},
    )
    db.add(audit)
    await db.commit()

    return {
        "run_id": run_id,
        "quality_score": body.quality_score,
        "evaluated_by": user.username,
        "note": body.note,
    }
