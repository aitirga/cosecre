"""Eines: things made out of what the register and the statements already hold.

Nothing here changes data. Each tool reads, builds a file, and hands it over.
"""

from __future__ import annotations

import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..deps import get_current_user, get_db
from ..models import StatementImport, User
from ..services import dossier

router = APIRouter()


@router.get("/statement-dossier/{statement_id}")
def statement_dossier(
    statement_id: int,
    proposals: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """A statement as one PDF: an index of every line, then each invoice with its original.

    ``proposals`` also gives a sheet to lines whose match is only proposed,
    marked as such — useful to review before confirming, never to hand in.
    ``date_from``/``date_to`` (inclusive) keep only the lines dated inside them.
    """
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="La data d'inici és posterior a la de final.")
    statement = session.get(StatementImport, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat l'extracte.")
    path = dossier.build(session, statement, proposals=proposals, date_from=date_from, date_to=date_to)
    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=dossier.file_name(statement, date_from, date_to),
        background=BackgroundTask(os.unlink, path),
    )
