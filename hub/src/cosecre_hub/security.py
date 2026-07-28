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
    """SQLite hands back naive datetimes even for ``DateTime(timezone=True)``."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, password_digest: str) -> bool:
    return password_hash.verify(password, password_digest)


# ------------------------------------------------------------------ access tokens


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


# ----------------------------------------------------------------- refresh tokens
#
# Only the SHA-256 of a refresh token is stored: a leaked database cannot be
# replayed as a set of live sessions. Rotation on every use means a stolen token
# stops working as soon as the real client refreshes.


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(
    session: Session,
    user: User,
    settings: Settings,
    *,
    client: str | None = None,
    client_label: str | None = None,
) -> str:
    refresh_token = secrets.token_urlsafe(48)
    session.add(
        RefreshSession(
            user_id=user.id,
            token_hash=_hash_refresh_token(refresh_token),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
            client=client,
            client_label=client_label,
        )
    )
    session.flush()
    return refresh_token


def find_refresh_session(session: Session, refresh_token: str) -> RefreshSession | None:
    return (
        session.query(RefreshSession)
        .filter(RefreshSession.token_hash == _hash_refresh_token(refresh_token))
        .first()
    )


def rotate_refresh_token(
    session: Session, refresh_token: str, settings: Settings
) -> tuple[User, RefreshSession] | None:
    """Consume a refresh token and return the user it belonged to.

    The old session is revoked whether or not it was still valid, so a replayed
    token is spent rather than left usable.
    """
    refresh_session = find_refresh_session(session, refresh_token)
    if refresh_session is None or refresh_session.revoked_at is not None:
        return None
    if normalize_utc(refresh_session.expires_at) <= utcnow():
        refresh_session.revoked_at = utcnow()
        session.flush()
        return None
    if not refresh_session.user.is_active:
        refresh_session.revoked_at = utcnow()
        session.flush()
        return None
    refresh_session.revoked_at = utcnow()
    session.flush()
    return refresh_session.user, refresh_session


def revoke_refresh_token(session: Session, refresh_token: str) -> bool:
    refresh_session = find_refresh_session(session, refresh_token)
    if refresh_session is None or refresh_session.revoked_at is not None:
        return False
    refresh_session.revoked_at = utcnow()
    session.flush()
    return True


def revoke_all_sessions(session: Session, user: User) -> int:
    """Sign a user out of every app. Returns how many sessions were live."""
    live = (
        session.query(RefreshSession)
        .filter(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        .all()
    )
    stamp = utcnow()
    for refresh_session in live:
        refresh_session.revoked_at = stamp
    session.flush()
    return len(live)
