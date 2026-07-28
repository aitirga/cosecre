from __future__ import annotations

import json

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .config import Settings
from .models import User, WorkspaceSetting
from .security import hash_password


class SeedUser(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    is_admin: bool = False


def ensure_workspace_settings(session: Session, settings: Settings) -> None:
    bind = session.get_bind()
    inspector = inspect(bind)

    workspace_columns = {column["name"] for column in inspector.get_columns("workspace_settings")}
    if "ticket_sheet_name" not in workspace_columns:
        session.execute(
            text(
                "ALTER TABLE workspace_settings "
                "ADD COLUMN ticket_sheet_name VARCHAR(255) DEFAULT 'Tiquets' NOT NULL"
            )
        )
        session.commit()

    upload_columns = {column["name"] for column in inspector.get_columns("uploads")}
    if "document_type" not in upload_columns:
        session.execute(
            text(
                "ALTER TABLE uploads "
                "ADD COLUMN document_type VARCHAR(40) DEFAULT 'invoice' NOT NULL"
            )
        )
        session.commit()
        session.execute(text("UPDATE uploads SET document_type = 'invoice' WHERE document_type IS NULL"))
        session.commit()

    if "drive_file_id" not in upload_columns:
        session.execute(
            text("ALTER TABLE uploads ADD COLUMN drive_file_id VARCHAR(255)")
        )
        session.commit()

    workspace = session.query(WorkspaceSetting).filter(WorkspaceSetting.id == 1).first()
    if workspace is None:
        session.add(
            WorkspaceSetting(
                id=1,
                openai_model=settings.openai_model,
                ticket_sheet_name="Tiquets",
            )
        )
        session.commit()
        return

    # Migrate the previous scaffold default to the current app default while
    # preserving any explicitly chosen custom model.
    if workspace.openai_model in {"", "gpt-4.1-mini"}:
        workspace.openai_model = settings.openai_model
    if not workspace.ticket_sheet_name:
        workspace.ticket_sheet_name = "Tiquets"
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
