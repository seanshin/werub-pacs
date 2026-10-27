"""WebSocket connection manager for real-time updates."""
import json
import logging
from typing import Set, Dict, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections and broadcast updates."""

    def __init__(self):
        """Initialize connection manager."""
        # Active connections: {batch_id: set(WebSocket)}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Subscribe map: {user_id: {batch_id: set(WebSocket)}}
        self.user_subscriptions: Dict[str, Dict[str, Set[WebSocket]]] = {}

    async def connect(self, websocket: WebSocket, batch_id: str, user_id: str):
        """
        Register a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            batch_id: Batch ID being monitored
            user_id: User making the connection
        """
        await websocket.accept()

        # Add to active connections
        if batch_id not in self.active_connections:
            self.active_connections[batch_id] = set()
        self.active_connections[batch_id].add(websocket)

        # Add to user subscriptions
        if user_id not in self.user_subscriptions:
            self.user_subscriptions[user_id] = {}
        if batch_id not in self.user_subscriptions[user_id]:
            self.user_subscriptions[user_id][batch_id] = set()
        self.user_subscriptions[user_id][batch_id].add(websocket)

        logger.info(f"WebSocket connected: batch={batch_id}, user={user_id}")

    def disconnect(self, websocket: WebSocket, batch_id: str, user_id: str):
        """
        Unregister a WebSocket connection.

        Args:
            websocket: WebSocket connection
            batch_id: Batch ID
            user_id: User ID
        """
        if batch_id in self.active_connections:
            self.active_connections[batch_id].discard(websocket)
            if not self.active_connections[batch_id]:
                del self.active_connections[batch_id]

        if user_id in self.user_subscriptions:
            if batch_id in self.user_subscriptions[user_id]:
                self.user_subscriptions[user_id][batch_id].discard(websocket)
                if not self.user_subscriptions[user_id][batch_id]:
                    del self.user_subscriptions[user_id][batch_id]
                if not self.user_subscriptions[user_id]:
                    del self.user_subscriptions[user_id]

        logger.info(f"WebSocket disconnected: batch={batch_id}, user={user_id}")

    async def broadcast_to_batch(self, batch_id: str, message: dict):
        """
        Broadcast update to all subscribers of a batch.

        Args:
            batch_id: Batch ID
            message: Message to broadcast (will be JSON encoded)
        """
        if batch_id not in self.active_connections:
            return

        disconnected = set()
        for websocket in self.active_connections[batch_id]:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {str(e)}")
                disconnected.add(websocket)

        # Clean up disconnected sockets
        for ws in disconnected:
            self.active_connections[batch_id].discard(ws)

    async def broadcast_to_user(self, user_id: str, message: dict):
        """
        Broadcast update to all connections for a user.

        Args:
            user_id: User ID
            message: Message to broadcast
        """
        if user_id not in self.user_subscriptions:
            return

        disconnected = set()
        for batch_id, connections in self.user_subscriptions[user_id].items():
            for websocket in connections:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send to WebSocket: {str(e)}")
                    disconnected.add((batch_id, websocket))

        # Clean up
        for batch_id, ws in disconnected:
            if batch_id in self.user_subscriptions[user_id]:
                self.user_subscriptions[user_id][batch_id].discard(ws)

    def get_connection_count(self, batch_id: str) -> int:
        """Get number of active connections for a batch."""
        return len(self.active_connections.get(batch_id, set()))

    def get_user_batches(self, user_id: str) -> list[str]:
        """Get list of batches being monitored by user."""
        if user_id not in self.user_subscriptions:
            return []
        return list(self.user_subscriptions[user_id].keys())


# Global connection manager instance
connection_manager = ConnectionManager()
