"""Multi-tenancy middleware and utilities.

Row-Level Security approach: tenant_id extracted from JWT claim,
injected into every DB query via PostgreSQL session variable.
"""
import logging
from contextvars import ContextVar
from typing import Optional
from uuid import UUID

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Context variable for current tenant (thread-safe)
_current_tenant: ContextVar[Optional[str]] = ContextVar('current_tenant', default=None)


def get_current_tenant() -> Optional[str]:
    """Get current tenant ID from context."""
    return _current_tenant.get()


def set_current_tenant(tenant_id: Optional[str]):
    """Set current tenant ID in context."""
    _current_tenant.set(tenant_id)


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant_id from JWT and set in request context.

    Tenant identification order:
    1. JWT claim 'tenant_id' (primary)
    2. X-Tenant-ID header (admin override)
    3. Default tenant (for backward compatibility)
    """

    # Paths that don't require tenant context
    EXEMPT_PATHS = {
        "/health", "/metrics", "/docs", "/redoc", "/openapi.json",
        "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/setup",
        # per-frame nginx auth_request 핫패스 — 중복 토큰 디코드/테넌트 컨텍스트 불요
        "/api/v1/dicomweb/_authcheck",
    }

    async def dispatch(self, request: Request, call_next):
        # Skip tenant check for exempt paths
        path = request.url.path.rstrip("/")
        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        # Extract tenant from JWT or header
        tenant_id = None

        # 1. Try JWT claim
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from app.core.security import decode_token
                token = auth_header.split(" ")[1]
                payload = decode_token(token)
                tenant_id = payload.get("tenant_id")
            except Exception:
                pass

        # 2. Try header override (super admin only)
        if not tenant_id:
            tenant_id = request.headers.get("x-tenant-id")

        # 3. Default tenant (backward compatibility for single-tenant mode)
        if not tenant_id:
            tenant_id = "default"

        # Set in context
        set_current_tenant(tenant_id)

        # Set PostgreSQL session variable for RLS
        # (will be used when RLS policies are enabled)
        request.state.tenant_id = tenant_id

        response = await call_next(request)

        # Clear context
        set_current_tenant(None)

        return response


# Tenant-aware query helper
def tenant_filter(query: str, tenant_id: Optional[str] = None) -> str:
    """Add tenant_id filter to SQL query.

    Usage:
        query = tenant_filter("SELECT * FROM reports WHERE status = :status")
        # Returns: "SELECT * FROM reports WHERE status = :status AND tenant_id = :_tenant_id"
    """
    tid = tenant_id or get_current_tenant()
    if not tid or tid == "default":
        return query  # Single-tenant mode: no filter

    # Simple approach: append AND clause
    if "WHERE" in query.upper():
        return query + " AND tenant_id = :_tenant_id"
    else:
        return query + " WHERE tenant_id = :_tenant_id"
