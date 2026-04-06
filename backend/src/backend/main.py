from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .bootstrap import ensure_workspace_settings, seed_users
from .config import Settings, get_settings
from .database import create_session_factory, create_sqlalchemy_engine, init_db


def create_app(settings_override: Settings | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    settings.ensure_directories()
    engine = create_sqlalchemy_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        session = session_factory()
        try:
            ensure_workspace_settings(session, settings)
            seed_users(session, settings)
        finally:
            session.close()
        yield
        engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/healthz")
    def healthcheck():
        return {"status": "ok"}

    return app


app = create_app()


def run() -> None:
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
