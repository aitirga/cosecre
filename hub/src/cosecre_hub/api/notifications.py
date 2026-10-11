"""The bell: a person's own notifications, and nobody else's."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from ..deps import get_current_user, get_db
from ..models import Notification, User
from ..schemas import MessageResponse
from ..schemas.requests import NotificationRead, PersonBrief, UnreadCount
from ..security import utcnow

router = APIRouter()


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    limit: int = Query(default=30, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        session.query(Notification)
        .options(selectinload(Notification.actor))
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .all()
    )
    return [
        NotificationRead(
            id=n.id,
            kind=n.kind,
            title=n.title,
            body=n.body,
            link=n.link,
            actor=PersonBrief.of(n.actor),
            read=n.read_at is not None,
            created_at=n.created_at,
        )
        for n in rows
    ]


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = (
        session.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .count()
    )
    return UnreadCount(count=count)


@router.post("/read-all", response_model=MessageResponse)
def read_all(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = (
        session.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .update({Notification.read_at: utcnow()}, synchronize_session=False)
    )
    session.commit()
    return MessageResponse(message=f"{count} marked as read.")


@router.post("/{notification_id}/read", response_model=MessageResponse)
def read_one(notification_id: int, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    notification = session.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = utcnow()
        session.commit()
    return MessageResponse(message="Read.")
