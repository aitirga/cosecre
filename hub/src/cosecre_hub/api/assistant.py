"""The Assistent (beta): each person's own chats, and the changes they propose.

A chat belongs to whoever started it — nobody else, admins included, can list,
read or delete it. See :mod:`cosecre_hub.services.assistant` for what it can do.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import get_current_user, get_db, get_llm_registry, get_settings
from ..models import AssistantConversation, AssistantProposal, User
from ..security import create_access_token
from ..services.assistant import Bridge, Turn
from ..services.assistant import proposals as proposal_service
from ..services.assistant.serialize import conversation_dict, conversation_summary, proposal_dict
from ..services.llm import LLMError, LLMRegistry

router = APIRouter()

_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


class ConversationCreate(BaseModel):
    title: str = Field(default="", max_length=255)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


def _conversation(session: Session, user: User, conversation_id: int) -> AssistantConversation:
    conversation = session.get(AssistantConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Aquesta conversa no existeix.")
    return conversation


def _proposal(session: Session, user: User, proposal_id: int) -> AssistantProposal:
    proposal = session.get(AssistantProposal, proposal_id)
    if proposal is None or proposal.conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Aquesta proposta no existeix.")
    return proposal


def _ready(settings: Settings, registry: LLMRegistry) -> tuple[bool, str]:
    if not settings.assistant_enabled:
        return False, "L'assistent està desactivat en aquest hub."
    try:
        provider = registry.get()
    except LLMError as exc:
        return False, str(exc)
    if not provider.is_configured():
        return False, "El hub no té cap clau d'OpenAI configurada."
    return True, ""


@router.get("/status")
def assistant_status(
    settings: Settings = Depends(get_settings),
    registry: LLMRegistry = Depends(get_llm_registry),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    ready, detail = _ready(settings, registry)
    return {
        "enabled": settings.assistant_enabled,
        "ready": ready,
        "detail": detail,
        "model": settings.assistant_model,
        "reasoning_effort": settings.assistant_reasoning_effort,
        "beta": True,
    }


@router.get("/conversations")
def list_conversations(
    session: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict[str, Any]]:
    conversations = (
        session.query(AssistantConversation)
        .filter(AssistantConversation.user_id == user.id)
        .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id.desc())
        .all()
    )
    return [conversation_summary(conversation) for conversation in conversations]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = AssistantConversation(user_id=user.id, title=payload.title.strip())
    session.add(conversation)
    session.commit()
    return conversation_dict(session, conversation)


@router.get("/conversations/{conversation_id}")
def read_conversation(
    conversation_id: int, session: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, Any]:
    return conversation_dict(session, _conversation(session, user, conversation_id))


@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    payload: ConversationRename,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _conversation(session, user, conversation_id)
    conversation.title = payload.title.strip()
    session.commit()
    return conversation_summary(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204, response_model=None)
def delete_conversation(
    conversation_id: int, session: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    """Gone for good: the chat, its answers and its proposals. What was applied stays applied."""
    session.delete(_conversation(session, user, conversation_id))
    session.commit()


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: int,
    payload: MessageCreate,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    registry: LLMRegistry = Depends(get_llm_registry),
    user: User = Depends(get_current_user),
):
    """Ask, and stream the answer as NDJSON — see :mod:`cosecre_hub.services.assistant.agent`."""
    _conversation(session, user, conversation_id)
    ready, detail = _ready(settings, registry)
    if not ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    app = request.app
    user_id = user.id
    text = payload.text.strip()
    # The request's session may live as long as the stream; it must not hold
    # SQLite's read lock all that time.
    session.commit()

    def frames() -> Iterator[str]:
        # Its own session: the request's may be closed before the stream ends.
        own = app.state.session_factory()
        try:
            me = own.get(User, user_id)
            conversation = own.get(AssistantConversation, conversation_id)
            turn = Turn(
                session=own,
                settings=settings,
                provider=registry.get(),
                bridge=Bridge(app, create_access_token(me, settings)),
                user=me,
                conversation=conversation,
            )
            for frame in turn.run(text):
                yield json.dumps(frame, ensure_ascii=False, default=str) + "\n"
        finally:
            own.close()

    return StreamingResponse(frames(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: int,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Make the changes, as this person, as one undoable action."""
    proposal = _proposal(session, user, proposal_id)
    bridge = Bridge(request.app, create_access_token(user, settings))
    try:
        proposal = await proposal_service.apply(session, bridge, proposal, user)
    except proposal_service.ProposalInvalid as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    proposal.conversation.updated_at = datetime.now(UTC)
    session.commit()
    return proposal_dict(proposal)


@router.post("/proposals/{proposal_id}/discard")
def discard_proposal(
    proposal_id: int, session: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, Any]:
    proposal = _proposal(session, user, proposal_id)
    try:
        proposal = proposal_service.discard(session, proposal)
    except proposal_service.ProposalInvalid as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return proposal_dict(proposal)
