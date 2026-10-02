from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_sqlalchemy_engine(database_url: str):
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        # FastAPI runs sync endpoints on a threadpool, so the connection is not
        # guaranteed to stay on the thread that opened it.
        connect_args["check_same_thread"] = False
        # Parallel extractions commit from several threads; wait for the
        # write lock rather than failing with "database is locked".
        connect_args["timeout"] = 30
    return create_engine(database_url, connect_args=connect_args, future=True)


def create_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)
