"""The chat as the client reads it: plain dicts, proposals expanded in place."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...models import AssistantConversation, AssistantMessage, AssistantProposal


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def proposal_dict(proposal: AssistantProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "summary": proposal.summary,
        "status": proposal.status,
        "detail": proposal.detail,
        "actions": [
            {
                "method": action.get("method"),
                "path": action.get("path"),
                "label": action.get("label", ""),
                "body": action.get("body"),
                "before": action.get("before"),
                "changes": action.get("changes", []),
            }
            for action in proposal.actions or []
        ],
        "results": proposal.results or [],
        "history_action_id": proposal.history_action_id,
        "created_at": _iso(proposal.created_at),
        "decided_at": _iso(proposal.decided_at),
    }


def message_dict(session: Session, message: AssistantMessage) -> dict[str, Any]:
    blocks = []
    for block in message.blocks or []:
        if block.get("type") == "proposal":
            proposal = session.get(AssistantProposal, block.get("proposal_id"))
            block = {**block, "proposal": proposal_dict(proposal) if proposal else None}
        blocks.append(block)
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "blocks": blocks,
        "status": message.status,
        "detail": message.detail,
        "model": message.model,
        "created_at": _iso(message.created_at),
    }


def conversation_summary(conversation: AssistantConversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title or "Conversa nova",
        "created_at": _iso(conversation.created_at),
        "updated_at": _iso(conversation.updated_at),
    }


def conversation_dict(session: Session, conversation: AssistantConversation) -> dict[str, Any]:
    return {
        **conversation_summary(conversation),
        "messages": [message_dict(session, message) for message in conversation.messages],
    }
