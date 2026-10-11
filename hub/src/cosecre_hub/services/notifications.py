"""In-app notifications: who hears about what.

Nothing leaves the hub — no e-mail — so a notification is a row the bell reads.
The rules live here rather than in each endpoint, so "who is told when" can be
read in one place.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from ..models import Document, Notification, Request, User

STAFF_ROLES = ("admin", "secretaria")

KIND_LABEL = {
    "compra": "Compra",
    "pressupost": "Pressupost",
    "consulta": "Consulta",
    "reemborsament": "Reemborsament",
}

STATUS_LABEL = {
    "oberta": "Oberta",
    "en_revisio": "En revisió",
    "aprovada": "Aprovada",
    "rebutjada": "Rebutjada",
    "resolta": "Resolta",
    "cancellada": "Cancel·lada",
}


def staff(session: Session) -> list[User]:
    return (
        session.query(User)
        .filter(User.role.in_(STAFF_ROLES), User.is_active.is_(True))
        .order_by(User.id)
        .all()
    )


def name_of(user: User | None) -> str:
    if user is None:
        return "Cosecre"
    return user.display_name or user.email


def notify(
    session: Session,
    recipients: Iterable[User | None],
    *,
    actor: User | None,
    kind: str,
    title: str,
    body: str = "",
    link: dict[str, Any] | None = None,
    request: Request | None = None,
) -> int:
    """One notification per recipient — never to whoever caused it, never twice."""
    seen: set[int] = set()
    for user in recipients:
        if user is None or not user.is_active or user.id in seen:
            continue
        if actor is not None and user.id == actor.id:
            continue
        seen.add(user.id)
        session.add(
            Notification(
                user_id=user.id,
                actor_id=actor.id if actor else None,
                kind=kind,
                title=title[:255],
                body=body,
                link=link,
                request_id=request.id if request else None,
            )
        )
    return len(seen)


def request_link(request: Request) -> dict[str, Any]:
    return {"name": "requests", "query": {"sol": str(request.id)}}


def _excerpt(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def office_for(session: Session, request: Request) -> list[User]:
    """Who on the office side hears about a request: its assignee once it has one."""
    return [request.assignee] if request.assignee is not None else staff(session)


def request_created(session: Session, request: Request, actor: User) -> None:
    notify(
        session,
        staff(session),
        actor=actor,
        kind="request_created",
        title=f"{KIND_LABEL[request.kind]}: {request.title}",
        body=f"{name_of(actor)} · {request.code}",
        link=request_link(request),
        request=request,
    )


def request_message(session: Session, request: Request, actor: User, body: str) -> None:
    if actor.id == request.requester_id:
        recipients: list[User | None] = office_for(session, request)
    else:
        recipients = [request.requester, request.assignee]
    notify(
        session,
        recipients,
        actor=actor,
        kind="request_message",
        title=f"{name_of(actor)} ha respost a {request.code}",
        body=_excerpt(body),
        link=request_link(request),
        request=request,
    )


def request_status(session: Session, request: Request, actor: User, note: str) -> None:
    label = STATUS_LABEL[request.status]
    if actor.id == request.requester_id:
        recipients: list[User | None] = office_for(session, request)
    else:
        recipients = [request.requester, request.assignee]
    notify(
        session,
        recipients,
        actor=actor,
        kind="request_status",
        title=f"{request.code} · {label}: {request.title}",
        body=_excerpt(note) if note else f"{name_of(actor)} l'ha marcada com a {label.lower()}.",
        link=request_link(request),
        request=request,
    )


def request_assigned(session: Session, request: Request, actor: User) -> None:
    notify(
        session,
        [request.assignee],
        actor=actor,
        kind="request_assigned",
        title=f"T'han assignat {request.code}: {request.title}",
        body=f"De {name_of(request.requester)}",
        link=request_link(request),
        request=request,
    )


# ── Invoices sent in by teachers ─────────────────────────────────────────────


def _submitted_by_teacher(session: Session, document: Document) -> User | None:
    creator = session.get(User, document.created_by_id) if document.created_by_id else None
    return creator if creator is not None and creator.role == "professor" else None


def _describe(document: Document) -> str:
    parts = [document.proveidor or "Proveïdor per llegir"]
    if document.import_value is not None:
        parts.append(f"{document.import_value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
    return " · ".join(parts)


def document_submitted(session: Session, document: Document) -> None:
    """A teacher's invoice has been read and waits for the office."""
    teacher = _submitted_by_teacher(session, document)
    if teacher is None:
        return
    request = session.get(Request, document.request_id) if document.request_id else None
    failed = document.status == "error"
    title = (
        f"{name_of(teacher)} ha enviat un document que no s'ha pogut llegir"
        if failed
        else f"{name_of(teacher)} ha enviat una factura per validar"
    )
    body = _describe(document) + (f" · per a {request.code}" if request else "")
    notify(
        session,
        office_for(session, request) if request else staff(session),
        actor=teacher,
        kind="document_submitted",
        title=title,
        body=body,
        link={"name": "register", "query": {"doc": document.internal_doc_number}},
        request=request,
    )


def document_validated(session: Session, document: Document, actor: User | None) -> None:
    """Tell the teacher who sent it that the office has validated it."""
    teacher = _submitted_by_teacher(session, document)
    if teacher is None:
        return
    notify(
        session,
        [teacher],
        actor=actor,
        kind="document_validated",
        title=f"Secretaria ha validat la teva factura: {document.num_factura or document.proveidor or document.internal_doc_number}",
        body=_describe(document),
        link={"name": "my-invoices", "query": {"doc": document.internal_doc_number}},
    )
