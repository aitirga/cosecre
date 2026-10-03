from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Settings
from .models import User, WorkspaceSetting
from .security import decode_access_token
from .services.llm import LLMRegistry
from .services import history

bearer_scheme = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request):
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_llm_registry(request: Request) -> LLMRegistry:
    return request.app.state.llm_registry


def get_workspace_setting(session: Session) -> WorkspaceSetting:
    workspace = session.query(WorkspaceSetting).filter(WorkspaceSetting.id == 1).first()
    if workspace is None:
        workspace = WorkspaceSetting(id=1)
        session.add(workspace)
        session.commit()
        session.refresh(workspace)
    return workspace


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except Exception as exc:  # noqa: BLE001 — every decode failure is one 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    user = session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Deactivating an account has to take effect before its access token expires,
    # so it is checked on every request rather than only at sign-in.
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Aquest compte està desactivat.")
    action = history.current()
    if action is not None and action.user_id is None:
        action.user_id = user.id
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cal ser administrador.")
    return user
