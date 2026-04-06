from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(back_populates="user")
    uploads: Mapped[list["Upload"]] = relationship(back_populates="user")
    jobs: Mapped[list["ExtractionJob"]] = relationship(back_populates="user")


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_sessions")


class WorkspaceSetting(Base):
    __tablename__ = "workspace_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    spreadsheet_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    spreadsheet_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sheet_name: Mapped[str] = mapped_column(String(255), default="Factures")
    openai_model: Mapped[str] = mapped_column(String(120), default="gpt-5.4")
    extraction_prompt: Mapped[str] = mapped_column(Text, default="")
    polling_interval_seconds: Mapped[int] = mapped_column(Integer, default=30)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    internal_doc_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_file_name: Mapped[str] = mapped_column(String(255))
    source_file_type: Mapped[str] = mapped_column(String(120))
    stored_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="uploads")
    job: Mapped["ExtractionJob"] = relationship(back_populates="upload", uselist=False)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[int] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sheet_row_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    upload: Mapped["Upload"] = relationship(back_populates="job")
    user: Mapped["User"] = relationship(back_populates="jobs")


class SheetSyncIndex(Base):
    __tablename__ = "sheet_sync_index"

    internal_doc_number: Mapped[str] = mapped_column(String(64), primary_key=True)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validat: Mapped[bool] = mapped_column(Boolean, default=False)
    row_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
