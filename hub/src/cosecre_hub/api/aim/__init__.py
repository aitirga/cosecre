"""AIM — Artificial Intelligence and Mathematics.

A teacher authors an exercise with the hub's model gateway, publishes it to a
library their colleagues share, runs it live for a class, and watches each
student work. Every student gets their own tutor, seeded with the exercise and
that student's accumulated profile, which guides without giving the solution.

This package is the whole server side: models, schemas, dependencies and routes.
That is a deliberate departure from the documents module, which spreads across
the shared ``models.py`` and ``schemas/`` because it inherited a schema that has
to stay byte-compatible with the original backend. AIM has no such history, and
keeping it in one directory is what makes the hub's "Adding a Cosecre app"
contract literally true: one package, one ``include_router`` line.
"""

from fastapi import APIRouter

from . import models  # noqa: F401 — registers the tables on Base before init_db
from .exercises import router as exercises_router
from .roster import router as roster_router

router = APIRouter()
router.include_router(roster_router)
router.include_router(exercises_router)

__all__ = ["router"]
