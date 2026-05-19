"""
sse.py — In-memory SSE connection manager with real-time presence tracking.

Each connected client is represented by an asyncio.Queue.
When a message is sent, the server pushes a JSON event into the
recipient's queue (and the sender's), which the open /stream
response immediately forwards to that client.

PRESENCE EVENTS:
  When a user connects:   {"type":"presence","username":"<name>","status":"online"}
  When a user disconnects: {"type":"presence","username":"<name>","status":"offline"}
  These are broadcast to ALL currently-connected clients.
"""

import asyncio
import json
import logging
from collections import defaultdict

log = logging.getLogger(__name__)


class ConnectionManager:
    """
    Tracks every live SSE connection and connected usernames.

    Internal structure:
        _queues:  { username: [Queue, Queue, ...] }
        _online:  set of usernames with at least one active connection
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def connect(self, username: str) -> asyncio.Queue:
        """
        Called when a client opens GET /stream.
        Creates a fresh Queue, registers it, and schedules a presence broadcast.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[username].append(queue)
        log.info("SSE connect: %s  (active streams: %d)", username, self._count())
        asyncio.create_task(self._broadcast_presence(username, "online"))
        return queue

    def disconnect(self, username: str, queue: asyncio.Queue) -> None:
        """
        Called when the client closes the connection.
        Removes the Queue; if no more connections remain, broadcasts offline.
        """
        try:
            self._queues[username].remove(queue)
        except ValueError:
            pass
        log.info("SSE disconnect: %s  (active streams: %d)", username, self._count())
        # Only broadcast offline when the user has NO remaining connections
        if not self._queues[username]:
            asyncio.create_task(self._broadcast_presence(username, "offline"))

    async def push(self, username: str, data: str) -> None:
        """
        Push a JSON string to every active stream belonging to *username*.
        Called from POST /messages after a message is saved.
        """
        for queue in list(self._queues[username]):
            await queue.put(data)

    async def broadcast(self, data: str) -> None:
        """Push a JSON string to ALL connected clients across all usernames."""
        for queues in list(self._queues.values()):
            for queue in queues:
                await queue.put(data)

    async def _broadcast_presence(self, username: str, status: str) -> None:
        event = json.dumps({"type": "presence", "username": username, "status": status})
        await self.broadcast(event)

    def _count(self) -> int:
        return sum(len(qs) for qs in self._queues.values())


# Module-level singleton — imported by routes.py
manager = ConnectionManager()

