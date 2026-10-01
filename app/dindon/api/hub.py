"""Live events: PostgreSQL NOTIFY -> every open page (Server-Sent Events)."""
import asyncio
import json
import logging

import psycopg

log = logging.getLogger("dindon.hub")
CHANNEL = "dindon"


class Hub:
    """Keeps one connection that LISTENs, and hands every notification to the pages that are connected."""

    def __init__(self, database_url: str):
        self._url = database_url
        self._queues: set[asyncio.Queue] = set()
        self.listening = False

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    def publish(self, payload: str) -> None:
        for queue in self._queues:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:  # a page that cannot keep up reloads instead of replaying
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(json.dumps({"type": "graph"}))

    async def run(self) -> None:
        first = True
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(self._url, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self.listening = True
                    if not first:  # events may have been missed while the connection was down
                        self.publish(json.dumps({"type": "graph"}))
                    first = False
                    async for notification in conn.notifies():
                        self.publish(notification.payload)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.listening = False
                log.warning("live events: connection lost (%s), retrying", type(error).__name__)
                await asyncio.sleep(2)
