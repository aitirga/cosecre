"""Requests to the office — open to every role.

A Professor/a sees and acts on their own requests only; the office (admin and
Secretaria) sees all of them and moves them along. Anything someone may not
see answers 404, so request numbers cannot be probed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..deps import get_current_user, get_db
from ..models import Document, Request, RequestMessage, User
from ..schemas.requests import (
    LinkedDocument,
    PersonBrief,
    RequestAssign,
    RequestCreate,
    RequestDetail,
    RequestMessageCreate,
    RequestMessageRead,
    RequestStatusChange,
    RequestSummary,
)
from ..security import utcnow
from ..services import notifications

router = APIRouter()

#: Where the office may move a request from each status. Reopening is always
#: back to "en revisió": someone is looking at it again.
OFFICE_MOVES: dict[str, set[str]] = {
    "oberta": {"en_revisio", "aprovada", "rebutjada", "resolta"},
    "en_revisio": {"aprovada", "rebutjada", "resolta"},
    "aprovada": {"en_revisio", "resolta"},
    "rebutjada": {"en_revisio"},
    "resolta": {"en_revisio"},
    "cancellada": set(),
}
#: The person who asked can only withdraw it, and only before it is decided.
REQUESTER_MOVES: dict[str, set[str]] = {
    "oberta": {"cancellada"},
    "en_revisio": {"cancellada"},
}
#: The order the client offers moves in.
STATUS_ORDER = ["en_revisio", "aprovada", "rebutjada", "resolta", "oberta", "cancellada"]


def is_office(user: User) -> bool:
    return user.role in notifications.STAFF_ROLES


def allowed_moves(request: Request, user: User) -> list[str]:
    moves: set[str] = set()
    if is_office(user):
        moves |= OFFICE_MOVES.get(request.status, set())
    if request.requester_id == user.id:
        moves |= REQUESTER_MOVES.get(request.status, set())
    return [s for s in STATUS_ORDER if s in moves]


def _visible(session: Session, request_id: int, user: User) -> Request:
    request = (
        session.query(Request)
        .options(selectinload(Request.messages).selectinload(RequestMessage.author))
        .filter(Request.id == request_id)
        .first()
    )
    if request is None or not (is_office(user) or request.requester_id == user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aquesta sol·licitud no existeix.")
    return request


def _document_counts(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = (
        session.query(Document.request_id, func.count(Document.id))
        .filter(Document.request_id.in_(ids))
        .group_by(Document.request_id)
        .all()
    )
    return dict(rows)


def _summary(request: Request, document_count: int) -> dict:
    return {
        "id": request.id,
        "code": request.code,
        "kind": request.kind,
        "title": request.title,
        "amount": request.amount,
        "proveidor": request.proveidor,
        "compte": request.compte,
        "needed_by": request.needed_by,
        "status": request.status,
        "requester": PersonBrief.of(request.requester),
        "assignee": PersonBrief.of(request.assignee),
        "message_count": sum(1 for m in request.messages if m.kind == "message"),
        "document_count": document_count,
        "created_at": request.created_at,
        "last_activity_at": request.last_activity_at,
    }


def _detail(session: Session, request: Request, user: User) -> RequestDetail:
    documents = (
        session.query(Document)
        .filter(Document.request_id == request.id)
        .order_by(Document.created_at)
        .all()
    )
    return RequestDetail(
        **_summary(request, len(documents)),
        description=request.description,
        messages=[
            RequestMessageRead(
                id=m.id,
                kind=m.kind,
                body=m.body,
                status=m.status,
                author=PersonBrief.of(m.author),
                created_at=m.created_at,
            )
            for m in request.messages
        ],
        documents=[
            LinkedDocument(
                num_doc_intern=d.internal_doc_number,
                num_factura=d.num_factura,
                proveidor=d.proveidor,
                import_value=d.import_value,
                status=d.status,
                validat=d.validat,
            )
            for d in documents
        ],
        allowed_statuses=allowed_moves(request, user),
        can_reply=request.status != "cancellada",
    )


def _touch(request: Request) -> None:
    request.last_activity_at = utcnow()


def _record_status(request: Request, actor: User, new_status: str, note: str) -> None:
    request.status = new_status
    request.messages.append(
        RequestMessage(author_id=actor.id, kind="status", status=new_status, body=note)
    )
    _touch(request)


@router.get("", response_model=list[RequestSummary])
def list_requests(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = session.query(Request).options(
        selectinload(Request.messages),
        selectinload(Request.requester),
        selectinload(Request.assignee),
    )
    if not is_office(user):
        query = query.filter(Request.requester_id == user.id)
    requests = query.order_by(Request.last_activity_at.desc()).all()
    counts = _document_counts(session, [r.id for r in requests])
    return [RequestSummary(**_summary(r, counts.get(r.id, 0))) for r in requests]


@router.post("", response_model=RequestDetail, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: RequestCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    request = Request(**payload.model_dump(), requester_id=user.id, status="oberta")
    session.add(request)
    session.flush()
    session.refresh(request)
    notifications.request_created(session, request, user)
    session.commit()
    return _detail(session, _visible(session, request.id, user), user)


@router.get("/office", response_model=list[PersonBrief])
def office(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Who a request can be handed to. The office's own question."""
    if not is_office(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Només per a secretaria.")
    return [PersonBrief.of(person) for person in notifications.staff(session) if person.password_hash]


@router.get("/{request_id}", response_model=RequestDetail)
def read_request(request_id: int, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _detail(session, _visible(session, request_id, user), user)


@router.post("/{request_id}/messages", response_model=RequestDetail)
def add_message(
    request_id: int,
    payload: RequestMessageCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    request = _visible(session, request_id, user)
    if request.status == "cancellada":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aquesta sol·licitud està cancel·lada.")

    request.messages.append(RequestMessage(author_id=user.id, kind="message", body=payload.body))
    # The office answering a new request is the office looking at it: it moves
    # on to "en revisió" and, unless someone has it already, it is theirs.
    if is_office(user) and request.requester_id != user.id and request.status == "oberta":
        request.messages.append(RequestMessage(author_id=user.id, kind="status", status="en_revisio"))
        request.status = "en_revisio"
        if request.assignee_id is None:
            request.assignee_id = user.id
    _touch(request)
    session.flush()
    session.refresh(request)
    notifications.request_message(session, request, user, payload.body)
    session.commit()
    return _detail(session, _visible(session, request_id, user), user)


@router.post("/{request_id}/status", response_model=RequestDetail)
def change_status(
    request_id: int,
    payload: RequestStatusChange,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    request = _visible(session, request_id, user)
    if payload.status not in allowed_moves(request, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No es pot passar de «{notifications.STATUS_LABEL[request.status]}» a «{notifications.STATUS_LABEL[payload.status]}».",
        )
    note = payload.note.strip()
    if payload.status == "rebutjada" and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Explica per què es rebutja: la persona que ho demana ho veurà.",
        )
    _record_status(request, user, payload.status, note)
    if is_office(user) and request.assignee_id is None and payload.status != "cancellada":
        request.assignee_id = user.id
    session.flush()
    session.refresh(request)
    notifications.request_status(session, request, user, note)
    session.commit()
    return _detail(session, _visible(session, request_id, user), user)


@router.post("/{request_id}/assign", response_model=RequestDetail)
def assign(
    request_id: int,
    payload: RequestAssign,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    request = _visible(session, request_id, user)
    if not is_office(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Només secretaria pot assignar sol·licituds.")
    if payload.assignee_id is not None:
        assignee = session.get(User, payload.assignee_id)
        if assignee is None or not assignee.is_active or not is_office(assignee):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Només es pot assignar a algú de secretaria.",
            )
    request.assignee_id = payload.assignee_id
    _touch(request)
    session.flush()
    session.refresh(request)
    if request.assignee is not None:
        notifications.request_assigned(session, request, user)
    session.commit()
    return _detail(session, _visible(session, request_id, user), user)
