"""Stop a single-worker hub only after requests and background work are idle."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .models import ExtractionJob

logger = logging.getLogger(__name__)


class IdleShutdown:
    def __init__(self, seconds: float, shutdown: Callable[[], None], session_factory,
                 *, clock: Callable[[], float] = time.monotonic,
                 before_shutdown: Callable[[], None] | None = None):
        self.seconds = seconds
        self.shutdown = shutdown
        self.before_shutdown = before_shutdown
        self.session_factory = session_factory
        self.clock = clock
        self.last_activity = clock()
        self.active = 0
        self.stopping = False

    def begin(self):
        self.active += 1
        self.last_activity = self.clock()

    def end(self):
        self.active -= 1
        self.last_activity = self.clock()

    def due(self):
        return (not self.stopping and self.active == 0
                and self.clock() - self.last_activity >= self.seconds)

    def jobs_pending(self):
        with self.session_factory() as session:
            return session.query(ExtractionJob.id).filter(
                ExtractionJob.status.in_(["pending", "processing", "written_to_sheet"])
            ).first() is not None

    async def check(self):
        if not self.due():
            return
        observed = self.last_activity
        try:
            busy = await asyncio.to_thread(self.jobs_pending)
        except Exception:
            logger.exception("Idle shutdown postponed: could not check document jobs")
            self.last_activity = self.clock()
            return
        # A request may arrive while the database check is on another thread.
        if busy or observed != self.last_activity or not self.due():
            return
        self.stopping = True
        logger.warning("Idle shutdown after %s seconds; no requests or document jobs remain", self.seconds)
        if self.before_shutdown is not None:
            # Last chance to back up today's changes; new requests already get a
            # 503 "waking up", so nothing can change underneath it.
            await asyncio.to_thread(self.before_shutdown)
        self.shutdown()

    async def watch(self):
        while not self.stopping:
            await asyncio.sleep(min(5, self.seconds))
            await self.check()


class ActivityMiddleware:
    def __init__(self, app, idle: IdleShutdown):
        self.app = app
        self.idle = idle

    async def __call__(self, scope, receive, send):
        tracked = scope["type"] in {"http", "websocket"} and scope.get("path") != "/healthz"
        if not tracked:
            return await self.app(scope, receive, send)
        if self.idle.stopping:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1012})
            else:
                await send({"type": "http.response.start", "status": 503,
                            "headers": [(b"retry-after", b"1"), (b"connection", b"close")]})
                await send({"type": "http.response.body", "body": b"Server is waking up. Please retry."})
            return
        self.idle.begin()
        try:
            # Pure ASGI middleware awaits BackgroundTasks too, even after the
            # response has been sent or the uploading browser has disconnected.
            await self.app(scope, receive, send)
        finally:
            self.idle.end()
