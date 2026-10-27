"""Celery application entry point.

Re-exports celery_app from ai_worker for consistent import paths.
"""
from app.services.ai_worker import celery_app  # noqa: F401
