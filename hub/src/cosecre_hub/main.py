from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import API_VERSION, __version__
from .api import api_router
from .bootstrap import run_startup_tasks
from .config import Settings, get_settings
from .db import create_session_factory, create_sqlalchemy_engine, init_db
from .services.llm import LLMRegistry

logger = logging.getLogger(__name__)


def create_app(
    settings_override: Settings | None = None,
    *,
    llm_registry: LLMRegistry | None = None,
) -> FastAPI:
    """Build the hub.

    ``llm_registry`` is injectable so tests — and any deployment that wants a
    different provider mix — can supply their own without patching module state.
    """
    settings = settings_override or get_settings()
    settings.ensure_directories()
    engine = create_sqlalchemy_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    registry = llm_registry or LLMRegistry.from_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.llm_registry = registry
        session = session_factory()
        try:
            run_startup_tasks(session, settings)
        finally:
            session.close()
        yield
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
    )
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/healthz", tags=["meta"])
    def healthcheck():
        """Liveness only — no database round trip, so it stays cheap to poll."""
        return {"status": "ok", "version": __version__}

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
