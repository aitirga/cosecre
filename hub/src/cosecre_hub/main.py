from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress

import uvicorn
from anyio import CapacityLimiter
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from . import API_VERSION, __version__
from .api import api_router
from .api.statements import caixeta_sync
from .bootstrap import recover_interrupted_jobs, run_startup_tasks
from .config import Settings, get_settings
from .db import create_session_factory, create_sqlalchemy_engine, init_db
from .services.backup import BackupService
from .services.classification import DocumentClassifier, JevClient
from .services.llm import LLMRegistry
from .services.sheets import GoogleSheetsService
from .idle import ActivityMiddleware, IdleShutdown
from .services import history

logger = logging.getLogger(__name__)


class SPAFiles(StaticFiles):
    """Serve client routes while preserving missing asset and API errors."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if (
                exc.status_code == 404
                and scope["method"] in {"GET", "HEAD"}
                and not path.startswith(("api/", "assets/"))
                and "." not in path.rsplit("/", 1)[-1]
            ):
                return await super().get_response("index.html", scope)
            raise


async def backup_schedule(service: BackupService, interval_seconds: float = 600) -> None:
    """Check every ten minutes whether a backup is due; take it off the event loop."""
    while True:
        await asyncio.to_thread(service.run_if_due)
        await asyncio.sleep(interval_seconds)



class HistoryMiddleware:
    """Every request that changes something becomes one undoable action."""

    def __init__(self, app, api_prefix: str):
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope, receive, send):
        token = history.begin_request(scope, self.api_prefix)
        try:
            await self.app(scope, receive, send)
        finally:
            history.end_request(token)


def create_app(
    settings_override: Settings | None = None,
    *,
    llm_registry: LLMRegistry | None = None,
    classifier: DocumentClassifier | None = None,
    sheet_service: GoogleSheetsService | None = None,
    idle_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    """Build the hub.

    ``llm_registry``, ``classifier`` and ``sheet_service`` are injectable so
    tests — and any deployment that wants a different provider mix — can supply
    their own without patching module state.
    """
    settings = settings_override or get_settings()
    settings.ensure_directories()
    engine = create_sqlalchemy_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    registry = llm_registry or LLMRegistry.from_settings(settings)
    if classifier is None:
        classifier = DocumentClassifier(
            JevClient(settings.typesafe_api_key, settings.jev_model)
            if settings.typesafe_api_key
            else None
        )
    sheet_service = sheet_service or GoogleSheetsService(settings)
    backup_service = BackupService(settings, session_factory, sheet_service)
    idle = (
        IdleShutdown(
            settings.idle_timeout_seconds,
            idle_shutdown,
            session_factory,
            before_shutdown=backup_service.before_shutdown,
        )
        if idle_shutdown and settings.idle_timeout_seconds
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.idle_timeout_seconds and idle is None:
            raise RuntimeError("Idle shutdown requires the cosecre_hub.server production entry point")
        init_db(engine)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.llm_registry = registry
        app.state.sheet_service = sheet_service
        app.state.classifier = classifier
        app.state.backup_service = backup_service
        app.state.extraction_limiter = CapacityLimiter(settings.extraction_concurrency)
        # Migration enrichment may use every slot but one, so a photo taken
        # mid-migration never waits behind fifty old documents.
        app.state.enrichment_limiter = CapacityLimiter(max(1, settings.extraction_concurrency - 1))
        # Choosing a free Drive name and claiming it must be one step, or two
        # parallel uploads of the same date and number pick the same name.
        app.state.drive_lock = threading.Lock()
        # Serialises everything that reads-then-writes the register sheet.
        app.state.register_lock = threading.RLock()
        app.state.register_synced_at = 0.0
        app.state.sheet_status = None
        app.state.enrichment_running = False
        app.state.drive_backfill_running = False
        session = session_factory()
        try:
            run_startup_tasks(session, settings)
            recover_interrupted_jobs(session)
        finally:
            session.close()
        app.state.caixeta_checked_at = 0.0
        app.state.caixeta_error = None
        app.state.mirror_synced_at = None
        app.state.mirror_error = None
        app.state.mirror_timer = None
        tasks = []
        # The machine wakes because someone is about to use it: read the caixeta now.
        tasks.append(asyncio.create_task(asyncio.to_thread(caixeta_sync.sync_if_due, app)))
        if settings.backup_enabled:
            tasks.append(asyncio.create_task(backup_schedule(backup_service)))
        if idle is not None:
            idle.last_activity = idle.clock()
            tasks.append(asyncio.create_task(idle.watch()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            timer = getattr(app.state, "mirror_timer", None)
            if timer is not None:
                timer.cancel()
            classifier.close()
            sheet_service.close()
            engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Shared identity, storage and LLM gateway for Cosecre apps. "
            f"API version {API_VERSION}."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Downloads read the file's name from it.
        expose_headers=["Content-Disposition"],
    )
    if idle is not None:
        app.add_middleware(ActivityMiddleware, idle=idle)
    app.add_middleware(HistoryMiddleware, api_prefix=settings.api_prefix)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/healthz", tags=["meta"])
    async def healthcheck():
        """Liveness only — no database round trip, so it stays cheap to poll."""
        return {"status": "ok", "version": __version__}

    if settings.static_dir is not None:
        app.mount("/", SPAFiles(directory=settings.static_dir, html=True), name="web")

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "cosecre_hub.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
