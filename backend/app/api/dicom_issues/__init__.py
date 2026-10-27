"""DICOM Issue Control Center API package.

Re-exports the router for backward compatibility with main.py:
    from app.api.dicom_issues import router as dicom_issues_router
"""
from .router import router
from .seed import seed_dicom_issue_data
from .fix import RULE_RESOLUTION

__all__ = ["router", "seed_dicom_issue_data", "RULE_RESOLUTION"]
