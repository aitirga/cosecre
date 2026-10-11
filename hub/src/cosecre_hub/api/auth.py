from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import get_current_user, get_db, get_settings
from ..models import RefreshSession, User
from ..schemas import (
    ActivateRequest,
    AuthTokens,
    InvitePreview,
    LoginRequest,
    MessageResponse,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    SessionRead,
    UserRead,
)
from ..security import (
    check_invite_code,
    clear_invite,
    create_access_token,
    find_invited_user,
    hash_password,
    issue_refresh_token,
    revoke_all_sessions,
    revoke_refresh_token,
    rotate_refresh_token,
    utcnow,
    verify_password,
)

router = APIRouter()


def _tokens(
    session: Session,
    user: User,
    settings: Settings,
    *,
    client: str | None,
    client_label: str | None,
) -> AuthTokens:
    refresh_token = issue_refresh_token(
        session, user, settings, client=client, client_label=client_label
    )
    return AuthTokens(
        access_token=create_access_token(user, settings),
        refresh_token=refresh_token,
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserRead.model_validate(user),
    )


@router.post("/register", response_model=AuthTokens, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Create an account.

    Open only while the hub has no users — that first account becomes the admin.
    After that, registration is an admin action (``POST /users``) unless
    ``COSECRE_ALLOW_OPEN_REGISTRATION`` says otherwise: a hub reachable from the
    internet with open sign-up is an open door.
    """
    is_first_user = session.query(User).count() == 0
    if not is_first_user and not settings.allow_open_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registre està tancat en aquest hub. Demana un compte a un administrador.",
        )

    existing_user = session.query(User).filter(User.email == payload.email).first()
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aquest correu ja està registrat.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        is_admin=is_first_user,
        role="admin" if is_first_user else "secretaria",
        is_active=True,
        last_login_at=utcnow(),
        password_set_at=utcnow(),
    )
    session.add(user)
    session.flush()
    tokens = _tokens(
        session, user, settings, client=payload.client, client_label=payload.client_label
    )
    session.commit()
    return tokens


@router.post("/login", response_model=AuthTokens)
def login(
    payload: LoginRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = session.query(User).filter(User.email == payload.email).first()
    if user is not None and user.is_active and not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aquest compte encara no està activat. Fes servir l'enllaç o el codi d'invitació.",
        )
    # One message for "no such account" and "wrong password" alike, so the
    # endpoint cannot be used to enumerate who has an account here.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Correu o contrasenya incorrectes.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Aquest compte està desactivat.")

    user.last_login_at = utcnow()
    tokens = _tokens(
        session, user, settings, client=payload.client, client_label=payload.client_label
    )
    session.commit()
    return tokens


_INVITE_GONE = "Aquesta invitació no és vàlida o ha caducat. Demana'n una de nova a l'administrador."


@router.get("/invite/{token}", response_model=InvitePreview)
def invite_preview(token: str, session: Session = Depends(get_db)):
    """Who an invitation link is for, so the activation page can greet them."""
    user = find_invited_user(session, token)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_INVITE_GONE)
    return InvitePreview(email=user.email, display_name=user.display_name, role=user.role)


@router.post("/activate", response_model=AuthTokens)
def activate(
    payload: ActivateRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Open an invitation and choose the account's password; signs straight in."""
    if payload.token:
        user = find_invited_user(session, payload.token)
    else:
        user = session.query(User).filter(User.email == payload.email).first()
        if user is not None and not check_invite_code(user, payload.code or ""):
            # The failed attempt is counted on the row, so it is kept.
            session.commit()
            user = None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVITE_GONE)

    user.password_hash = hash_password(payload.password)
    user.password_set_at = utcnow()
    user.last_login_at = utcnow()
    clear_invite(user)
    tokens = _tokens(
        session, user, settings, client=payload.client, client_label=payload.client_label
    )
    session.commit()
    return tokens


@router.post("/refresh", response_model=AuthTokens)
def refresh(
    payload: RefreshRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    rotated = rotate_refresh_token(session, payload.refresh_token, settings)
    if rotated is None:
        # The rotation attempt may have spent a token even when it failed, so the
        # commit is not skipped on the error path.
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user, previous = rotated
    tokens = _tokens(
        session, user, settings, client=previous.client, client_label=previous.client_label
    )
    session.commit()
    return tokens


@router.post("/logout", response_model=MessageResponse)
def logout(payload: RefreshRequest, session: Session = Depends(get_db)):
    """Revoke one session. Unauthenticated on purpose.

    A client that is signing out has usually already dropped its access token, and
    holding the refresh token is proof enough to retire it.
    """
    revoked = revoke_refresh_token(session, payload.refresh_token)
    session.commit()
    return MessageResponse(message="Session revoked." if revoked else "Session was already gone.")


@router.post("/logout-all", response_model=MessageResponse)
def logout_all(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = revoke_all_sessions(session, user)
    session.commit()
    return MessageResponse(message=f"Signed out of {count} session(s).")


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return UserRead.model_validate(user)


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    live = (
        session.query(RefreshSession)
        .filter(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        .order_by(RefreshSession.created_at.desc())
        .all()
    )
    return [
        SessionRead(
            id=item.id,
            client=item.client,
            client_label=item.client_label,
            created_at=item.created_at,
            expires_at=item.expires_at,
        )
        for item in live
    ]


@router.post("/password", response_model=MessageResponse)
def change_password(
    payload: PasswordChangeRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="La contrasenya actual no és correcta."
        )
    user.password_hash = hash_password(payload.new_password)
    user.password_set_at = utcnow()
    # A password change is also how someone reacts to a suspected compromise, so
    # every other session goes with it.
    revoke_all_sessions(session, user)
    session.commit()
    return MessageResponse(message="Contrasenya canviada. S'han tancat les altres sessions.")
