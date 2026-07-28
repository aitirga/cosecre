"""Startup work: schema catch-up, then account provisioning.

The hub is meant to be pointed at a database an earlier version of the app
created, so every column it added since is applied here rather than requiring a
migration tool for what is a handful of nullable additions.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .config import Settings
from .models import User, WorkspaceSetting
from .security import hash_password

logger = logging.getLogger(__name__)

#: ``(table, column, DDL type + constraints)``. Applied in order, skipped when the
#: column already exists, so running this against a current database is a no-op.
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "display_name", "VARCHAR(255)"),
    ("users", "is_active", "BOOLEAN DEFAULT 1 NOT NULL"),
    ("users", "last_login_at", "DATETIME"),
    ("refresh_sessions", "client", "VARCHAR(64)"),
    ("refresh_sessions", "client_label", "VARCHAR(255)"),
    ("workspace_settings", "ticket_sheet_name", "VARCHAR(255) DEFAULT 'Tiquets' NOT NULL"),
    ("uploads", "document_type", "VARCHAR(40) DEFAULT 'invoice' NOT NULL"),
    ("uploads", "drive_file_id", "VARCHAR(255)"),
]


class SeedUser(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    is_admin: bool = False


def apply_compat_migrations(session: Session) -> list[str]:
    """Add any column this build expects but the database does not have yet."""
    inspector = inspect(session.get_bind())
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    for table, column, ddl in ADDED_COLUMNS:
        if table not in existing_tables:
            continue
        columns = {info["name"] for info in inspector.get_columns(table)}
        if column in columns:
            continue
        session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        session.commit()
        applied.append(f"{table}.{column}")

    if applied:
        logger.info("Applied schema catch-up: %s", ", ".join(applied))
    return applied


def ensure_workspace_settings(session: Session, settings: Settings) -> None:
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

    # Carry an old scaffold default forward to the configured one, while leaving
    # an explicitly chosen model alone.
    if workspace.openai_model in {"", "gpt-4.1-mini"}:
        workspace.openai_model = settings.openai_model
    if not workspace.ticket_sheet_name:
        workspace.ticket_sheet_name = "Tiquets"
    session.commit()


def bootstrap_admin(session: Session, settings: Settings) -> None:
    """Create (or reset) the first admin from the environment.

    Preferred over a seed file because nothing sensitive has to be written to
    disk inside the repository. Setting the variables again later resets that
    account's password, which is the documented way back in after a lockout.
    """
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if not email or not password:
        return

    user = session.query(User).filter(User.email == email).first()
    if user is None:
        session.add(
            User(
                email=email,
                password_hash=hash_password(password),
                is_admin=True,
                is_active=True,
            )
        )
        logger.info("Created bootstrap admin %s", email)
    else:
        user.password_hash = hash_password(password)
        user.is_admin = True
        user.is_active = True
        logger.info("Reset bootstrap admin %s", email)
    session.commit()


def seed_users(session: Session, settings: Settings) -> None:
    """Upsert accounts from the legacy seed file, when one is configured.

    Kept for deployments that already rely on it. The file holds plaintext
    passwords, so it is gitignored and the hub says so out loud on every start.
    """
    seed_file = settings.seed_users_file
    if seed_file is None or not seed_file.exists():
        return

    logger.warning(
        "Seeding accounts from %s. This file contains plaintext passwords — keep it out of "
        "version control and prefer COSECRE_BOOTSTRAP_ADMIN_EMAIL/PASSWORD plus admin-managed "
        "users instead.",
        seed_file,
    )

    try:
        payload = json.loads(seed_file.read_text(encoding="utf-8"))
        seeds = [SeedUser.model_validate(item) for item in payload]
    except (OSError, ValueError, ValidationError):
        # A malformed seed file must not stop the hub from starting; every other
        # account still works.
        logger.exception("Could not read seed users from %s", seed_file)
        return

    for seed_user in seeds:
        existing = session.query(User).filter(User.email == seed_user.email).first()
        if existing is None:
            session.add(
                User(
                    email=seed_user.email,
                    password_hash=hash_password(seed_user.password),
                    is_admin=seed_user.is_admin,
                    is_active=True,
                )
            )
            continue
        existing.password_hash = hash_password(seed_user.password)
        existing.is_admin = seed_user.is_admin

    session.commit()


def run_startup_tasks(session: Session, settings: Settings) -> None:
    apply_compat_migrations(session)
    ensure_workspace_settings(session, settings)
    bootstrap_admin(session, settings)
    seed_users(session, settings)

    if settings.is_secret_key_default:
        logger.warning(
            "COSECRE_SECRET_KEY is still the built-in default. Every access token this hub "
            "issues can be forged until it is changed."
        )
