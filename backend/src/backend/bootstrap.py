from __future__ import annotations

import json

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .config import Settings
from .models import User, WorkspaceSetting
from .security import hash_password


class SeedUser(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    is_admin: bool = False


def ensure_workspace_settings(session: Session, settings: Settings) -> None:
    workspace = session.query(WorkspaceSetting).filter(WorkspaceSetting.id == 1).first()
    if workspace is None:
        session.add(
            WorkspaceSetting(
                id=1,
                openai_model=settings.openai_model,
            )
        )
        session.commit()
        return

    # Migrate the previous scaffold default to the current app default while
    # preserving any explicitly chosen custom model.
    if workspace.openai_model in {"", "gpt-4.1-mini"}:
        workspace.openai_model = settings.openai_model
        session.commit()


def seed_users(session: Session, settings: Settings) -> None:
    seed_file = settings.seed_users_file
    if not seed_file.exists():
        return

    payload = json.loads(seed_file.read_text(encoding="utf-8"))
    users = [SeedUser.model_validate(item) for item in payload]

    for seed_user in users:
        existing = session.query(User).filter(User.email == seed_user.email).first()
        if existing is None:
            session.add(
                User(
                    email=seed_user.email,
                    password_hash=hash_password(seed_user.password),
                    is_admin=seed_user.is_admin,
                )
            )
            continue

        existing.password_hash = hash_password(seed_user.password)
        existing.is_admin = seed_user.is_admin

    session.commit()
