from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..dependencies import get_current_user, get_db, get_settings
from ..models import User
from ..schemas import AuthTokens, LoginRequest, RefreshRequest, UserCreate, UserRead
from ..security import (
    create_access_token,
    hash_password,
    issue_refresh_token,
    rotate_refresh_token,
    verify_password,
)

router = APIRouter()


@router.post("/register", response_model=AuthTokens, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, session: Session = Depends(get_db), settings=Depends(get_settings)):
    existing_user = session.query(User).filter(User.email == payload.email).first()
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    is_first_user = session.query(User).count() == 0
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        is_admin=is_first_user,
    )
    session.add(user)
    session.flush()
    refresh_token = issue_refresh_token(session, user, settings)
    session.commit()
    session.refresh(user)
    return AuthTokens(
        access_token=create_access_token(user, settings),
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.post("/login", response_model=AuthTokens)
def login(payload: LoginRequest, session: Session = Depends(get_db), settings=Depends(get_settings)):
    user = session.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    refresh_token = issue_refresh_token(session, user, settings)
    session.commit()
    return AuthTokens(
        access_token=create_access_token(user, settings),
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.post("/refresh", response_model=AuthTokens)
def refresh(payload: RefreshRequest, session: Session = Depends(get_db), settings=Depends(get_settings)):
    user = rotate_refresh_token(session, payload.refresh_token, settings)
    if user is None:
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    refresh_token = issue_refresh_token(session, user, settings)
    session.commit()
    return AuthTokens(
        access_token=create_access_token(user, settings),
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return UserRead.model_validate(user)
