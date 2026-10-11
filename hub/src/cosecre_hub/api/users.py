"""Admin-managed accounts — the replacement for a plaintext seed file."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, require_admin
from ..models import User
from ..schemas import InviteIssued, MessageResponse, UserCreate, UserRead, UserUpdate
from ..security import clear_invite, hash_password, issue_invite, revoke_all_sessions, utcnow

router = APIRouter()


@router.get("", response_model=list[UserRead])
def list_users(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = session.query(User).order_by(User.created_at.asc()).all()
    return [UserRead.model_validate(user) for user in users]


def _invited(session: Session, user: User) -> InviteIssued:
    token, code = issue_invite(user)
    session.flush()
    return InviteIssued(
        user=UserRead.model_validate(user), token=token, code=code, expires_at=user.invite_expires_at
    )


def _is_last_admin(session: Session, user: User) -> bool:
    if user.role != "admin":
        return False
    others = (
        session.query(User)
        .filter(User.role == "admin", User.is_active.is_(True), User.id != user.id)
        .count()
    )
    return others == 0


@router.post("", response_model=UserRead | InviteIssued, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Enable an e-mail address.

    Without a password the account is invited: the response carries the link
    token and code once, and the account cannot sign in until its owner opens
    one of them and chooses a password.
    """
    if session.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aquest correu ja està registrat.")

    role = payload.resolved_role
    user = User(
        email=payload.email,
        password_hash="",
        display_name=payload.display_name,
        role=role,
        is_admin=role == "admin",
        is_active=True,
    )
    session.add(user)
    if payload.password is None:
        issued = _invited(session, user)
        session.commit()
        return issued

    user.password_hash = hash_password(payload.password)
    user.password_set_at = utcnow()
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@router.post("/{user_id}/invite", response_model=InviteIssued)
def reinvite_user(
    user_id: int,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Issue a new invitation — also how an account is reset.

    The password stops working and every session is signed out; the owner
    chooses a new password through the new link or code.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Per canviar la teva contrasenya, fes-ho des del teu compte.",
        )
    user.is_active = True
    revoke_all_sessions(session, user)
    issued = _invited(session, user)
    session.commit()
    return issued


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
    role = payload.resolved_role
    if role is not None and role != "admin" and _is_last_admin(session, user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="És l'últim compte d'administrador.",
        )

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if role is not None:
        user.role = role
        user.is_admin = role == "admin"
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            revoke_all_sessions(session, user)
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        user.password_set_at = utcnow()
        clear_invite(user)
        revoke_all_sessions(session, user)

    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{user_id}", response_model=MessageResponse)
def remove_user(
    user_id: int,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Take an account away.

    One that never signed in is deleted outright — it owns nothing. One that has
    been used is disabled instead: uploads, documents and requests point at it,
    and removing the row would take that history with it.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No pots desactivar el teu propi compte."
        )

    if user.password_set_at is None and user.last_login_at is None:
        session.delete(user)
        session.commit()
        return MessageResponse(message=f"{user.email} was removed.")

    user.is_active = False
    clear_invite(user)
    revoke_all_sessions(session, user)
    session.commit()
    return MessageResponse(message=f"{user.email} was disabled.")


@router.get("/me", response_model=UserRead, include_in_schema=False)
def read_self(user: User = Depends(get_current_user)):
    """Convenience alias so a client does not have to know it is under /auth."""
    return UserRead.model_validate(user)
