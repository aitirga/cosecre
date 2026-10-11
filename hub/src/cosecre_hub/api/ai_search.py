"""Plain-words search for any list in the app; see :mod:`..services.ai_search`."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import get_current_user
from ..models import User
from ..services.ai_filter import AiFilterUnavailable
from ..services.ai_search import TableSpec, read_search

router = APIRouter()


class AiSearchRequest(TableSpec):
    query: str = Field(min_length=2, max_length=500)


class AiSourceRead(BaseModel):
    source: str
    confidence: float | None = None


class AiSearchRead(BaseModel):
    filters: dict[str, str]
    search: str
    explanation: str
    sources: dict[str, AiSourceRead]
    models: dict[str, str]
    answer: None = None


def _today():
    try:
        return datetime.now(ZoneInfo("Europe/Madrid")).date()
    except ZoneInfoNotFoundError:
        return datetime.now().date()


@router.post("", response_model=AiSearchRead)
def ai_search(payload: AiSearchRequest, request: Request, _: User = Depends(get_current_user)):
    """Read a question as the filters the list described. Reads none of the hub's data."""
    jev = getattr(request.app.state.classifier, "jev", None)
    try:
        result = read_search(payload, payload.query.strip(), request.app.state.llm_registry, jev, _today())
    except AiFilterUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AiSearchRead(
        filters=result.filters,
        search=result.search,
        explanation=result.explanation,
        sources={name: AiSourceRead(source=r.source, confidence=r.confidence) for name, r in result.sources.items()},
        models=result.models,
    )
