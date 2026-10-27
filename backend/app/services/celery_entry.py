"""Celery entry point — avoids importing async database module."""
import os
os.environ.setdefault("DATABASE_URL", "postgresql://openpacs:OpenPACS2026!@127.0.0.1:5432/openpacs")

from app.services.ai_worker import celery_app  # noqa: F401
