"""WebSocket endpoints for real-time batch normalization progress."""
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_db
from app.core.exceptions import AuthenticationError
from app.core.security import decode_token
from app.core.websocket_manager import connection_manager
from app.services.batch_job_service import BatchJobService
from app.services.batch_progress import channel as batch_channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["WebSocket"])


@router.websocket("/ws/batch/{batch_id}")
async def websocket_batch_progress(
    websocket: WebSocket,
    batch_id: str,
    token: str = Query(...),
):
    """
    WebSocket endpoint for real-time batch progress updates.

    Connect to this endpoint to receive real-time updates as a batch is being processed.

    Message format:
    {
        "type": "progress" | "complete" | "error",
        "batch_id": "...",
        "status": "queued" | "processing" | "completed" | "failed",
        "processed": 10,
        "total": 50,
        "succeeded": 9,
        "failed": 1,
        "progress_percent": 20.0,
        "current_file": "filename.dcm",
        "elapsed_ms": 5000,
        "message": "Processing file..."
    }

    Args:
        websocket: WebSocket connection
        batch_id: Batch job UUID
        user_id: User ID for authorization
    """
    db: AsyncSession = None

    # JWT 검증(fail-closed) — 클라가 보낸 user_id를 신뢰하지 않고 토큰 sub에서 신원 유도.
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        user_role = payload.get("role")
        if not user_id:
            raise AuthenticationError(message="missing sub")
    except AuthenticationError:
        await websocket.close(code=1008, reason="Invalid token")
        return

    try:
        # Get DB session
        async_db = get_async_db()
        db = await async_db.__anext__()

        # Check batch exists and user has permission
        batch = await BatchJobService.get_batch_job(db, batch_id)
        if not batch:
            await websocket.close(code=1008, reason="Batch not found")
            return

        # 소유자 또는 admin만 — 토큰에서 검증된 신원 기준.
        if str(batch.user_id) != user_id and user_role != "admin":
            await websocket.close(code=1008, reason="Not authorized")
            return

        # Register connection
        await connection_manager.connect(websocket, batch_id, user_id)

        # Send initial status
        stats = await BatchJobService.get_batch_statistics(db, batch_id)
        await websocket.send_json({
            "type": "connected",
            "batch_id": batch_id,
            "status": batch.status,
            "message": "Connected to batch progress stream",
            "statistics": stats,
        })

        logger.info(f"WebSocket client connected: batch={batch_id}, user={user_id}")

        # K3: celery 워커가 Redis로 발행하는 진행상황을 구독해 클라이언트로 전달
        # (워커는 별도 프로세스라 in-process connection_manager로는 도달 불가).
        redis_client = aioredis.from_url(settings.redis_url)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(batch_channel(batch_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    payload = message["data"]
                    if isinstance(payload, (bytes, bytearray)):
                        payload = payload.decode()
                    await websocket.send_text(payload)  # 클라 끊기면 raise → 정리
        finally:
            # pubsub 루프가 어떻게 끝나든(예외/Redis연결종료) 소켓 등록 해제 — 정상종료
            # 경로에서 disconnect 누락 시 죽은 소켓 잔존 누수.
            try:
                connection_manager.disconnect(websocket, batch_id, user_id)
            except Exception:
                pass
            try:
                await pubsub.unsubscribe(batch_channel(batch_id))
                await redis_client.aclose()
            except Exception:
                pass

    except WebSocketDisconnect:
        connection_manager.disconnect(websocket, batch_id, user_id)
        logger.info(f"WebSocket client disconnected: batch={batch_id}, user={user_id}")

    except Exception as e:
        logger.exception(f"WebSocket error for batch {batch_id}: {str(e)}")
        try:
            connection_manager.disconnect(websocket, batch_id, user_id)
        except Exception:
            pass

    finally:
        if db:
            await db.close()


# Helper function to broadcast batch progress updates
async def broadcast_batch_progress(
    batch_id: str,
    status: str,
    processed: int,
    total: int,
    succeeded: int,
    failed: int,
    current_file: str = None,
    elapsed_ms: float = 0,
):
    """
    Broadcast batch progress update to all subscribers.

    Called by batch normalization task to send real-time updates.

    Args:
        batch_id: Batch job ID
        status: Current batch status
        processed: Number of files processed
        total: Total number of files
        succeeded: Number of successful files
        failed: Number of failed files
        current_file: Currently processing filename
        elapsed_ms: Elapsed time in milliseconds
    """
    progress_percent = (processed / total * 100) if total > 0 else 0

    message = {
        "type": "progress",
        "batch_id": batch_id,
        "status": status,
        "processed": processed,
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "progress_percent": progress_percent,
        "current_file": current_file,
        "elapsed_ms": elapsed_ms,
    }

    await connection_manager.broadcast_to_batch(batch_id, message)

    logger.debug(
        f"Broadcast batch progress: batch={batch_id}, "
        f"processed={processed}/{total}, "
        f"progress={progress_percent:.1f}%"
    )


async def broadcast_batch_complete(
    batch_id: str,
    status: str,
    total: int,
    succeeded: int,
    failed: int,
    error_summary: dict = None,
):
    """
    Broadcast batch completion update.

    Args:
        batch_id: Batch job ID
        status: Final status (completed, failed)
        total: Total files
        succeeded: Successful files
        failed: Failed files
        error_summary: Optional error summary
    """
    message = {
        "type": "complete",
        "batch_id": batch_id,
        "status": status,
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "error_summary": error_summary or {},
        "message": f"Batch {status}: {succeeded} succeeded, {failed} failed",
    }

    await connection_manager.broadcast_to_batch(batch_id, message)

    logger.info(
        f"Broadcast batch complete: batch={batch_id}, "
        f"status={status}, succeeded={succeeded}, failed={failed}"
    )


async def broadcast_batch_error(batch_id: str, error: str):
    """
    Broadcast batch error update.

    Args:
        batch_id: Batch job ID
        error: Error message
    """
    message = {
        "type": "error",
        "batch_id": batch_id,
        "error": error,
        "message": f"Batch processing error: {error}",
    }

    await connection_manager.broadcast_to_batch(batch_id, message)

    logger.error(f"Broadcast batch error: batch={batch_id}, error={error}")
