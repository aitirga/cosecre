from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .config import Settings
from .models import RefreshSession, User

password_hash = PasswordHash.recommended()


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, password_digest: str) -> bool:
    return password_hash.verify(password, password_digest)


def create_access_token(user: User, settings: Settings) -> str:
    expires_at = utcnow() + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "is_admin": user.is_admin,
        "type": "access",
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(session: Session, user: User, settings: Settings) -> str:
    refresh_token = secrets.token_urlsafe(48)
    session.add(
        RefreshSession(
            user_id=user.id,
            token_hash=_hash_refresh_token(refresh_token),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    session.flush()
    return refresh_token


def rotate_refresh_token(session: Session, refresh_token: str, settings: Settings) -> User | None:
    refresh_session = (
        session.query(RefreshSession)
        .filter(RefreshSession.token_hash == _hash_refresh_token(refresh_token))
        .first()
    )
    if refresh_session is None or refresh_session.revoked_at is not None:
        return None
    if normalize_utc(refresh_session.expires_at) <= utcnow():
        refresh_session.revoked_at = utcnow()
        session.flush()
        return None
    refresh_session.revoked_at = utcnow()
    session.flush()
    return refresh_session.user
