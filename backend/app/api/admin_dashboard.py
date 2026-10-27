"""Admin dashboard API for batch management and monitoring."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_async_db
from app.core.auth import get_current_user
from app.core.security import RequireRole
from app.models.user import Role, User
from app.models.batch_job import BatchJob, BatchJobFile, NormalizationConfig, SupplierRule
from app.services.batch_job_service import BatchJobService
from app.services.config_service import ConfigService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin Dashboard"])


# Admin 가드 — RequireRole 경유로 v12.3 Break-the-Glass 차단(allow_btg=False) 적용.
# (이전 자체 require_admin은 RequireRole을 안 거쳐 BTG 우회 구멍이었음 — config 쓰기 포함.)
require_admin = RequireRole(Role.ADMIN, allow_btg=False)


@router.get("/dashboard/stats")
async def get_dashboard_statistics(
    hours: int = Query(24, ge=1, le=168),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Get global batch normalization statistics.

    Args:
        hours: Look back period in hours
        current_user: Authenticated admin
        db: Database session

    Returns:
        Dashboard statistics (batches, files, success rate, etc.)
    """
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Total batches in period
    total_batches_stmt = select(func.count(BatchJob.id)).where(
        BatchJob.created_at >= cutoff_time
    )
    total_batches_result = await db.execute(total_batches_stmt)
    total_batches = total_batches_result.scalar() or 0

    # Status distribution
    status_stmt = select(
        BatchJob.status,
        func.count(BatchJob.id).label("count")
    ).where(
        BatchJob.created_at >= cutoff_time
    ).group_by(BatchJob.status)

    status_result = await db.execute(status_stmt)
    status_dist = {row[0]: row[1] for row in status_result.all()}

    # Total files
    total_files_stmt = select(func.count(BatchJobFile.id)).where(
        BatchJobFile.created_at >= cutoff_time
    )
    total_files_result = await db.execute(total_files_stmt)
    total_files = total_files_result.scalar() or 0

    # File status distribution
    file_status_stmt = select(
        BatchJobFile.status,
        func.count(BatchJobFile.id).label("count")
    ).where(
        BatchJobFile.created_at >= cutoff_time
    ).group_by(BatchJobFile.status)

    file_status_result = await db.execute(file_status_stmt)
    file_status_dist = {row[0]: row[1] for row in file_status_result.all()}

    # Supplier distribution
    supplier_stmt = select(
        BatchJob.supplier,
        func.count(BatchJob.id).label("count")
    ).where(
        BatchJob.created_at >= cutoff_time
    ).group_by(BatchJob.supplier)

    supplier_result = await db.execute(supplier_stmt)
    supplier_dist = {row[0]: row[1] for row in supplier_result.all()}

    # Success metrics
    completed_batches = status_dist.get("completed", 0)
    failed_batches = status_dist.get("failed", 0)
    total_completed = completed_batches + failed_batches

    batch_success_rate = (
        (completed_batches / total_completed * 100) if total_completed > 0 else 0
    )

    # File success metrics
    normalized_files = file_status_dist.get("normalized", 0)
    stored_files = file_status_dist.get("stored", 0)
    failed_files = file_status_dist.get("failed", 0)
    total_processed = normalized_files + stored_files + failed_files

    file_success_rate = (
        ((normalized_files + stored_files) / total_processed * 100)
        if total_processed > 0
        else 0
    )

    # Average processing time
    processing_stmt = select(func.avg(
        func.extract("epoch", BatchJob.completed_at - BatchJob.started_at)
    )).where(
        (BatchJob.completed_at.isnot(None)) &
        (BatchJob.started_at.isnot(None)) &
        (BatchJob.created_at >= cutoff_time)
    )

    processing_result = await db.execute(processing_stmt)
    avg_processing_seconds = processing_result.scalar() or 0

    return {
        "period_hours": hours,
        "period_start": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
        "period_end": datetime.now(timezone.utc).isoformat(),
        "batches": {
            "total": total_batches,
            "by_status": status_dist,
            "success_rate": batch_success_rate,
        },
        "files": {
            "total": total_files,
            "by_status": file_status_dist,
            "success_rate": file_success_rate,
        },
        "suppliers": supplier_dist,
        "performance": {
            "avg_processing_seconds": round(avg_processing_seconds, 2),
            "batches_per_hour": round(total_batches / hours, 2),
            "files_per_hour": round(total_files / hours, 2),
        },
    }


@router.get("/dashboard/recent-batches")
async def get_recent_batches(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Get most recent batch jobs across all users.

    Args:
        limit: Number of batches to return
        current_user: Authenticated admin
        db: Database session

    Returns:
        List of recent batches with summary
    """
    stmt = select(BatchJob).order_by(BatchJob.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    batches = result.scalars().all()

    return {
        "total": len(batches),
        "batches": [
            {
                "batch_id": str(b.id),
                "user_id": str(b.user_id),
                "status": b.status,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "started_at": b.started_at.isoformat() if b.started_at else None,
                "completed_at": b.completed_at.isoformat() if b.completed_at else None,
                "total_files": b.total_files,
                "succeeded_files": b.succeeded_files,
                "failed_files": b.failed_files,
                "supplier": b.supplier,
                "success_rate": (
                    (b.succeeded_files / b.total_files * 100) if b.total_files > 0 else 0
                ),
            }
            for b in batches
        ],
    }


@router.get("/dashboard/slow-batches")
async def get_slow_batches(
    threshold_minutes: int = Query(30, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Get batches that took longer than threshold to process.

    Args:
        threshold_minutes: Minimum processing time
        limit: Number of batches to return
        current_user: Authenticated admin
        db: Database session

    Returns:
        List of slow batches
    """
    threshold_seconds = threshold_minutes * 60

    stmt = select(BatchJob).where(
        (BatchJob.started_at.isnot(None)) &
        (BatchJob.completed_at.isnot(None))
    ).order_by(
        (BatchJob.completed_at - BatchJob.started_at).desc()
    ).limit(limit)

    result = await db.execute(stmt)
    batches = result.scalars().all()

    slow_batches = []
    for batch in batches:
        if batch.completed_at and batch.started_at:
            elapsed = (batch.completed_at - batch.started_at).total_seconds()
            if elapsed >= threshold_seconds:
                slow_batches.append({
                    "batch_id": str(batch.id),
                    "user_id": str(batch.user_id),
                    "status": batch.status,
                    "total_files": batch.total_files,
                    "succeeded_files": batch.succeeded_files,
                    "failed_files": batch.failed_files,
                    "processing_seconds": round(elapsed, 2),
                    "files_per_second": round(batch.succeeded_files / elapsed, 2) if elapsed > 0 else 0,
                })

    return {
        "threshold_minutes": threshold_minutes,
        "total": len(slow_batches),
        "batches": slow_batches,
    }


# Configuration Management Endpoints

@router.get("/config/modalities")
async def list_modality_configurations(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    List all modality normalization configurations.

    Args:
        current_user: Authenticated admin
        db: Database session

    Returns:
        List of modality configurations
    """
    stmt = select(NormalizationConfig).order_by(NormalizationConfig.modality)
    result = await db.execute(stmt)
    configs = result.scalars().all()

    return {
        "total": len(configs),
        "configurations": [
            {
                "config_id": str(c.id),
                "modality": c.modality,
                "algorithms": c.algorithms,
                "risk_tiers": c.risk_tiers,
                "updated_by": c.updated_by,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in configs
        ],
    }


@router.post("/config/modalities/{modality}")
async def update_modality_configuration(
    modality: str,
    algorithms: dict,
    risk_tiers: dict,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Create or update modality configuration.

    Args:
        modality: DICOM modality (CT, MR, US, XR, etc.)
        algorithms: Algorithm settings dict
        risk_tiers: Risk tier handling dict
        current_user: Authenticated admin
        db: Database session

    Returns:
        Updated configuration
    """
    config = await ConfigService.update_modality_config(
        db,
        modality,
        algorithms,
        risk_tiers,
        updated_by=str(current_user.id),
    )
    await db.commit()

    return {
        "config_id": str(config.id),
        "modality": config.modality,
        "algorithms": config.algorithms,
        "risk_tiers": config.risk_tiers,
        "updated_by": config.updated_by,
        "updated_at": config.updated_at.isoformat(),
    }


@router.get("/config/suppliers")
async def list_supplier_rules(
    supplier: Optional[str] = Query(None),
    active_only: bool = Query(True),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    List supplier-specific normalization rules.

    Args:
        supplier: Filter by supplier name
        active_only: Only return active rules
        current_user: Authenticated admin
        db: Database session

    Returns:
        List of supplier rules
    """
    stmt = select(SupplierRule)

    if supplier:
        stmt = stmt.where(SupplierRule.supplier_name == supplier)
    if active_only:
        stmt = stmt.where(SupplierRule.is_active == True)

    stmt = stmt.order_by(
        SupplierRule.supplier_name,
        SupplierRule.rule_version.desc(),
    )

    result = await db.execute(stmt)
    rules = result.scalars().all()

    return {
        "total": len(rules),
        "rules": [
            {
                "rule_id": str(r.id),
                "supplier_name": r.supplier_name,
                "rule_version": r.rule_version,
                "is_active": r.is_active,
                "managed_by": r.managed_by,
                "description": r.description,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rules
        ],
    }


@router.post("/config/suppliers")
async def create_supplier_rule(
    supplier_name: str,
    rule_version: str,
    rule_config: dict,
    description: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Create a new supplier-specific rule.

    Args:
        supplier_name: Supplier name (siemens, ge, philips, etc.)
        rule_version: Version identifier
        rule_config: Rule configuration JSON
        description: Optional description
        current_user: Authenticated admin
        db: Database session

    Returns:
        Created rule
    """
    rule = await ConfigService.create_supplier_rule(
        db,
        supplier_name,
        rule_version,
        rule_config,
        managed_by=str(current_user.id),
        description=description,
    )
    await db.commit()

    return {
        "rule_id": str(rule.id),
        "supplier_name": rule.supplier_name,
        "rule_version": rule.rule_version,
        "is_active": rule.is_active,
        "managed_by": rule.managed_by,
        "description": rule.description,
        "created_at": rule.created_at.isoformat(),
    }


@router.put("/config/suppliers/{rule_id}/deactivate")
async def deactivate_supplier_rule(
    rule_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Deactivate a supplier rule (soft delete).

    Args:
        rule_id: Rule UUID
        current_user: Authenticated admin
        db: Database session

    Returns:
        Deactivated rule
    """
    rule = await ConfigService.deactivate_supplier_rule(db, rule_id)
    await db.commit()

    return {
        "rule_id": str(rule.id),
        "supplier_name": rule.supplier_name,
        "is_active": rule.is_active,
        "message": "Rule deactivated",
    }
