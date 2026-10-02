"""Admin-managed accounts — the replacement for a plaintext seed file."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, require_admin
from ..models import User
from ..schemas import MessageResponse, UserCreate, UserRead, UserUpdate
from ..security import hash_password, revoke_all_sessions

router = APIRouter()


@router.get("", response_model=list[UserRead])
def list_users(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = session.query(User).order_by(User.created_at.asc()).all()
    return [UserRead.model_validate(user) for user in users]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if session.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aquest correu ja està registrat.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        is_admin=payload.is_admin,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Locking yourself out, or demoting the last admin, leaves a hub nobody can
    # administer — and no way to undo it through the API.
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No pots desactivar el teu propi compte."
        )
    if payload.is_admin is False and user.is_admin:
        remaining_admins = (
            session.query(User)
            .filter(User.is_admin.is_(True), User.is_active.is_(True), User.id != user.id)
            .count()
        )
        if remaining_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="És l'últim compte d'administrador.",
            )

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            revoke_all_sessions(session, user)
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        revoke_all_sessions(session, user)

    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{user_id}", response_model=MessageResponse)
def deactivate_user(
    user_id: int,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Disable an account rather than delete it.

    Uploads and extraction jobs are owned by a user; removing the row would take
    that history with it, so accounts are retired instead.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No pots desactivar el teu propi compte."
        )

    user.is_active = False
    revoke_all_sessions(session, user)
    session.commit()
    return MessageResponse(message=f"{user.email} was disabled.")


@router.get("/me", response_model=UserRead, include_in_schema=False)
def read_self(user: User = Depends(get_current_user)):
    """Convenience alias so a client does not have to know it is under /auth."""
    return UserRead.model_validate(user)
