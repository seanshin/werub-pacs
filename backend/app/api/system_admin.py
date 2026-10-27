"""System administration API — DICOM nodes, routing, retention, QC dashboard, cache management."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.cache import get_cache_manager, purge_pattern
from app.core.cache_config import (
    CACHE_PATTERN_WORKLIST,
    CACHE_PATTERN_PERMISSIONS,
    CACHE_PATTERN_ORTHANC,
    CACHE_PATTERN_MODELS,
    CACHE_PATTERN_ALL,
)
from app.core.database import get_db
from app.core.exceptions import OrthancError, ValidationError
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User
from app.models.validation import ValidationResult, Severity

router = APIRouter(prefix="/api/v1/admin", tags=["system-admin"])


# ── DICOM Node Management ──

class DicomNodeConfig(BaseModel):
    name: str
    ae_title: str
    host: str
    port: int = 4242


@router.get("/dicom-nodes")
async def list_dicom_nodes(
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """List registered DICOM modalities."""
    client = request.app.state.http_client
    resp = await client.get("/modalities")
    modalities = resp.json() if resp.status_code == 200 else []

    nodes = []
    for name in modalities:
        detail = await client.get(f"/modalities/{name}/configuration")
        if detail.status_code == 200:
            cfg = detail.json()
            nodes.append({
                "name": name,
                "ae_title": cfg.get("AET"),
                "host": cfg.get("Host"),
                "port": cfg.get("Port"),
            })

    return {"count": len(nodes), "nodes": nodes}


@router.post("/dicom-nodes")
@AuditLogger.log("DICOM_NODE_REGISTERED", "DicomNode")
async def register_dicom_node(
    body: DicomNodeConfig,
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register a new DICOM modality node."""
    client = request.app.state.http_client
    resp = await client.put(
        f"/modalities/{body.name}",
        json={"AET": body.ae_title, "Host": body.host, "Port": body.port},
    )
    return {"status": "registered", "name": body.name, "ae_title": body.ae_title}


@router.post("/dicom-nodes/{name}/echo")
async def echo_dicom_node(
    name: str,
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """C-ECHO test to a registered DICOM node."""
    client = request.app.state.http_client
    resp = await client.post(f"/modalities/{name}/echo")
    if resp.status_code == 200:
        return {"status": "success", "node": name, "message": "C-ECHO OK"}
    raise OrthancError(message=f"C-ECHO failed: {resp.text[:200]}")


@router.delete("/dicom-nodes/{name}")
@AuditLogger.log("DICOM_NODE_DELETED", "DicomNode")
async def delete_dicom_node(
    name: str,
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a registered DICOM modality."""
    client = request.app.state.http_client
    await client.delete(f"/modalities/{name}")
    return {"status": "deleted", "name": name}


# ── Routing Rules ──

class RoutingRule(BaseModel):
    source_ae_title: str | None = None
    modality: str | None = None
    body_part: str | None = None
    destination_node: str
    auto_forward: bool = True


@router.get("/routing-rules")
async def list_routing_rules(
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """List auto-routing rules (stored in Redis)."""
    redis = request.app.state.redis
    rules = await redis.get("routing_rules")
    if rules:
        import json
        return {"rules": json.loads(rules)}
    return {"rules": []}


@router.post("/routing-rules")
@AuditLogger.log("ROUTING_RULE_CHANGED", "RoutingRule")
async def set_routing_rules(
    rules: list[RoutingRule],
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set auto-routing rules."""
    import json
    redis = request.app.state.redis
    await redis.set("routing_rules", json.dumps([r.model_dump() for r in rules]))
    return {"status": "saved", "count": len(rules)}


# ── Retention Policy ──

class RetentionPolicy(BaseModel):
    default_retention_days: int = 1825  # 5 years
    modality_overrides: dict[str, int] = {}  # e.g., {"CR": 365*3}


@router.get("/retention-policy")
async def get_retention_policy(
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Get current data retention policy."""
    redis = request.app.state.redis
    policy = await redis.get("retention_policy")
    if policy:
        import json
        return json.loads(policy)
    return {"default_retention_days": 1825, "modality_overrides": {}}


@router.post("/retention-policy")
@AuditLogger.log("RETENTION_POLICY_CHANGED", "RetentionPolicy")
async def set_retention_policy(
    policy: RetentionPolicy,
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set data retention policy."""
    import json
    redis = request.app.state.redis
    await redis.set("retention_policy", json.dumps(policy.model_dump()))
    return {"status": "saved", "policy": policy.model_dump()}


# ── QC Dashboard ──

@router.get("/qc-dashboard")
async def qc_dashboard(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """QC quality dashboard — validation statistics."""
    # Validation stats by severity
    severity_result = await db.execute(
        select(ValidationResult.severity, func.count())
        .group_by(ValidationResult.severity)
    )

    # By AE Title
    ae_result = await db.execute(
        select(ValidationResult.ae_title, func.count())
        .where(ValidationResult.ae_title.isnot(None))
        .group_by(ValidationResult.ae_title)
        .limit(10)
    )

    # By category
    cat_result = await db.execute(
        select(ValidationResult.category, func.count())
        .group_by(ValidationResult.category)
    )

    # By rule code (top issues)
    rule_result = await db.execute(
        select(ValidationResult.rule_code, func.count())
        .group_by(ValidationResult.rule_code)
        .order_by(func.count().desc())
        .limit(10)
    )

    total = await db.execute(select(func.count()).select_from(ValidationResult))

    return {
        "total_findings": total.scalar() or 0,
        "by_severity": dict(severity_result.all()),
        "by_ae_title": dict(ae_result.all()),
        "by_category": dict(cat_result.all()),
        "top_issues": dict(rule_result.all()),
    }


# ── Cache Management ──

@router.post("/cache/purge")
@AuditLogger.log("CACHE_PURGED", "Cache")
async def purge_cache(
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    db: Annotated[AsyncSession, Depends(get_db)],
    cache_type: str = Query("all", description="Cache type: all, worklist, permissions, orthanc, models"),
):
    """Purge Redis cache by type. Admin only."""
    patterns = {
        "all": CACHE_PATTERN_ALL,
        "worklist": CACHE_PATTERN_WORKLIST,
        "permissions": CACHE_PATTERN_PERMISSIONS,
        "orthanc": CACHE_PATTERN_ORTHANC,
        "models": CACHE_PATTERN_MODELS,
    }

    pattern = patterns.get(cache_type)
    if not pattern:
        raise ValidationError(
            message=f"Unknown cache_type: {cache_type}. Valid values: {', '.join(patterns.keys())}"
        )

    count = await purge_pattern(pattern)
    return {"status": "purged", "cache_type": cache_type, "keys_deleted": count}


@router.get("/cache/stats")
async def get_cache_stats(
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Get Redis cache statistics. Admin only."""
    cache_mgr = get_cache_manager()

    if not cache_mgr.available:
        return {"status": "unavailable", "message": "Redis cache is not available"}

    try:
        info = await cache_mgr.info("stats")
        memory_info = await cache_mgr.info("memory")

        return {
            "status": "ok",
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
            "hit_rate": (
                info.get("keyspace_hits", 0) / (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0))
                if (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)) > 0
                else 0
            ),
            "memory_mb": memory_info.get("used_memory", 0) / 1_000_000,
            "memory_percentage": (memory_info.get("used_memory", 0) / 100_000_000) * 100,  # 100MB limit
            "evicted_keys": memory_info.get("evicted_keys", 0),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
