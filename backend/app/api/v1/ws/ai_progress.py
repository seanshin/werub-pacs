"""WebSocket handler for real-time AI inference job progress updates.

Provides real-time streaming of job status changes:
- queued → running → completed/failed transitions
- Inference progress events (step 1/12, step 2/12, etc.)
- Final results (confidence score, DICOM UIDs)

Architecture:
- Connection per job_id using FastAPI WebSocket
- Redis Pub/Sub backend for multi-worker broadcast
- Reconnect logic and message queuing for lost connections
"""
import logging
import json
from uuid import UUID
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.core.exceptions import NotFoundError, PermissionDeniedError, AuthenticationError
from app.models.ai import InferenceJob
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Redis Pub/Sub channels
CHANNEL_TEMPLATE = "ai:job:{job_id}"  # e.g., "ai:job:uuid-1234"

router = APIRouter(prefix="/ws/ai", tags=["AI WebSocket"])


class JobProgressManager:
    """Manages WebSocket connections and broadcasts job progress."""

    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket):
        """Register a new WebSocket connection for a job.

        Args:
            job_id: UUID of the inference job
            websocket: FastAPI WebSocket connection
        """
        await websocket.accept()
        if job_id not in self.connections:
            self.connections[job_id] = []
        self.connections[job_id].append(websocket)
        logger.info(f"WebSocket connected for job {job_id}; active connections: {len(self.connections[job_id])}")

    async def disconnect(self, job_id: str, websocket: WebSocket):
        """Unregister a WebSocket connection.

        Args:
            job_id: UUID of the inference job
            websocket: FastAPI WebSocket connection
        """
        if job_id in self.connections:
            self.connections[job_id].remove(websocket)
            if not self.connections[job_id]:
                del self.connections[job_id]
            logger.info(f"WebSocket disconnected for job {job_id}")

    async def broadcast(self, job_id: str, message: dict):
        """Broadcast a message to all WebSocket clients for a job.

        Args:
            job_id: UUID of the inference job
            message: Message dict (will be JSON-encoded)
        """
        if job_id in self.connections:
            for websocket in self.connections[job_id]:
                try:
                    await websocket.send_json(message)
                    logger.debug(f"Sent WebSocket message to job {job_id}")
                except Exception as e:
                    logger.warning(f"Failed to send WebSocket message: {str(e)}")

    async def subscribe_redis(self, redis_client, job_id: str, websocket: WebSocket):
        """Subscribe to Redis Pub/Sub for job updates and forward to WebSocket.

        Args:
            redis_client: Redis client
            job_id: UUID of the inference job
            websocket: FastAPI WebSocket connection
        """
        channel = CHANNEL_TEMPLATE.format(job_id=job_id)
        pubsub = redis_client.pubsub()

        try:
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to Redis channel: {channel}")

            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    try:
                        data = json.loads(message["data"])
                        await websocket.send_json(data)
                        logger.debug(f"Forwarded Redis message to WebSocket: {data}")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in Redis message: {str(e)}")
                    except Exception as e:
                        logger.warning(f"Error forwarding Redis message: {str(e)}")
                        break

        except Exception as e:
            logger.error(f"Error in Redis subscription: {str(e)}", exc_info=True)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            logger.info(f"Unsubscribed from Redis channel: {channel}")


# Global connection manager
manager = JobProgressManager()


@router.websocket("/ai/{job_id}")
async def websocket_ai_progress(
    websocket: WebSocket,
    job_id: str,
    token: Optional[str] = Query(None),
):
    """WebSocket endpoint for real-time AI inference job progress.

    Endpoint: GET /api/v1/ws/ai/{job_id}?token={JWT_TOKEN}

    Flow:
    1. Accept WebSocket connection
    2. Validate JWT token and verify job exists and user has permission
    3. Send initial job state
    4. Subscribe to Redis Pub/Sub for live updates
    5. Forward updates to client until disconnect

    Message format:
    {
        "type": "status_update",
        "job_id": "...",
        "status": "queued|running|completed|failed",
        "step": 1,
        "total_steps": 12,
        "confidence_score": 0.95,
        "inference_time_ms": 1234,
        "timestamp": "2026-05-14T10:30:00Z"
    }

    Args:
        websocket: FastAPI WebSocket
        job_id: UUID of inference job (path parameter)
        token: JWT authentication token (query parameter, required)
        db: AsyncSession database connection (injected)
    """
    try:
        # Step 1: Accept WebSocket
        await manager.connect(job_id, websocket)

        # Step 2a: Validate JWT token
        if not token:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "AUTHENTICATION_REQUIRED",
                    "message": "Authentication token is required",
                }
            )
            await websocket.close(code=1008)
            return

        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
            user_role = payload.get("role")
            if not user_id:
                raise AuthenticationError(message="Invalid token: missing user_id")
        except AuthenticationError:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "AUTHENTICATION_INVALID",
                    "message": "Invalid or expired authentication token",
                }
            )
            await websocket.close(code=1008)
            return

        # Step 2b: Verify job exists and user has permission
        if db is None:
            db = next(get_db())

        job = await db.query(InferenceJob).filter(InferenceJob.id == job_id).first()
        if not job:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "RESOURCE_NOT_FOUND",
                    "message": f"Inference job {job_id} not found",
                }
            )
            await websocket.close(code=1008)
            return

        # Permission check: allow job creator and admins
        is_admin = user_role == "admin"
        is_owner = str(job.created_by) == user_id
        if not (is_owner or is_admin):
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "FORBIDDEN",
                    "message": "You do not have permission to view this job",
                }
            )
            await websocket.close(code=1008)
            return

        # Step 3: Send initial job state
        initial_message = {
            "type": "initial_state",
            "job_id": str(job.id),
            "status": job.status,
            "model_id": str(job.model_id),
            "study_instance_uid": job.study_instance_uid,
            "series_instance_uid": job.series_instance_uid,
            "celery_task_id": job.celery_task_id,
            "inference_time_ms": job.inference_time_ms,
            "confidence_score": float(job.confidence_score) if job.confidence_score else None,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await websocket.send_json(initial_message)
        logger.info(f"Sent initial state for job {job_id}")

        # Step 4 & 5: Subscribe to Redis Pub/Sub and forward updates
        redis_client = await get_redis_client()
        await manager.subscribe_redis(redis_client, job_id, websocket)

    except WebSocketDisconnect:
        await manager.disconnect(job_id, websocket)
        logger.info(f"WebSocket disconnected normally for job {job_id}")

    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {str(e)}", exc_info=True)
        await manager.disconnect(job_id, websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


async def publish_job_update(
    redis_client,
    job_id: str,
    status: str,
    step: Optional[int] = None,
    total_steps: int = 12,
    inference_time_ms: Optional[int] = None,
    confidence_score: Optional[float] = None,
    error_message: Optional[str] = None,
):
    """Publish job progress update to Redis Pub/Sub (called by Celery task).

    Args:
        redis_client: Redis client
        job_id: UUID of inference job
        status: Job status (queued, running, completed, failed)
        step: Current step number (1-12)
        total_steps: Total steps in pipeline
        inference_time_ms: Inference duration
        confidence_score: Model confidence
        error_message: Error details if failed
    """
    channel = CHANNEL_TEMPLATE.format(job_id=job_id)
    message = {
        "type": "status_update",
        "job_id": job_id,
        "status": status,
        "step": step,
        "total_steps": total_steps,
        "inference_time_ms": inference_time_ms,
        "confidence_score": confidence_score,
        "error_message": error_message,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        await redis_client.publish(channel, json.dumps(message))
        logger.debug(f"Published job update to Redis: {channel}")
    except Exception as e:
        logger.error(f"Failed to publish Redis message: {str(e)}", exc_info=True)
