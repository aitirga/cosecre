"""Names and emails already used for an entry's responsible person."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...deps import get_current_user, get_db
from ...models import User
from ...schemas.documents import ResponsableSearch
from ...services import people

router = APIRouter()


@router.get("", response_model=ResponsableSearch)
def search_responsables(
    field: people.SearchField = "nom",
    q: str = Query(default="", max_length=255),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Known people whose name (or email) contains ``q``; all of them, most used
    first, when ``q`` is empty. ``suggestion`` is set when ``q`` looks like a
    misspelling of one of them."""
    return people.search(session, field, q)
