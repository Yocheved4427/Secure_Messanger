"""
sse.py — In-memory SSE connection manager.

Each connected client is represented by an asyncio.Queue.
When a message is sent, the server pushes a JSON event into the
recipient's queue (and the sender's), which the open /stream
response immediately forwards to that client.

WHY ASYNCIO.QUEUE?
  FastAPI runs on an async event loop. asyncio.Queue is the standard
  way to pass data between coroutines on that loop.
  One Queue per connected client — if the same user opens two tabs,
  both get their own Queue and both receive events.

LIMITATION (learning scope):
  This manager lives in process memory. In production you would replace
  the dict with a Redis pub/sub channel so multiple server instances
  can broadcast to each other.
"""

import asyncio
import logging
from collections import defaultdict

log = logging.getLogger(__name__)


class ConnectionManager:
    """
    Tracks every live SSE connection.

    Internal structure:
        { username: [Queue, Queue, ...] }

    Multiple queues per user because the same account may be logged in
    from several terminals or browser tabs simultaneously.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def connect(self, username: str) -> asyncio.Queue:
        """
        Called when a client opens GET /stream.
        Creates a fresh Queue, registers it, and returns it to the route
        handler so it can await events from it.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[username].append(queue)
        log.info("SSE connect: %s  (active streams: %d)", username, self._count())
        return queue

    def disconnect(self, username: str, queue: asyncio.Queue) -> None:
        """
        Called when the client closes the connection.
        Removes the Queue so we stop trying to push events to it.
        """
        try:
            self._queues[username].remove(queue)
        except ValueError:
            pass  # already removed — nothing to do
        log.info("SSE disconnect: %s  (active streams: %d)", username, self._count())

    async def push(self, username: str, data: str) -> None:
        """
        Push a JSON string to every active stream belonging to *username*.
        Called from POST /messages after a message is saved.

        If the user has no open /stream connections this is a no-op — the
        client can fetch the message later via GET /messages.
        """
        for queue in list(self._queues[username]):
            await queue.put(data)

    def _count(self) -> int:
        return sum(len(qs) for qs in self._queues.values())


# Module-level singleton — imported by routes.py
manager = ConnectionManager()
