"""Database schema.

Table and column names are deliberately identical to the ones the original
single-purpose backend used, so pointing the hub at an existing
``cosecre.db`` migrates a deployment without touching its data. Columns added
by the hub are all nullable or defaulted, and :mod:`cosecre_hub.bootstrap`
adds them to older databases on startup.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Added by the hub.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(back_populates="user")
    uploads: Mapped[list["Upload"]] = relationship(back_populates="user")
    jobs: Mapped[list["ExtractionJob"]] = relationship(back_populates="user")


class RefreshSession(Base):
    """One live sign-in. Rotated on every refresh, revoked on logout.

    ``client`` records which app the session belongs to, which is what makes
    "sign out everywhere" and per-device listings possible for a hub that
    several apps share.
    """

    __tablename__ = "refresh_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Added by the hub.
    client: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_sessions")


class AppSetting(Base):
    """Per-app configuration bag.

    Any Cosecre app can keep its shared settings here instead of shipping its
    own server: one row per ``(app, key)``, value is arbitrary JSON. Reads need
    a signed-in user, writes need an admin.
    """

    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("app_slug", "key", name="uq_app_settings_app_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_slug: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[Any] = mapped_column(JSON, default=dict)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WorkspaceSetting(Base):
    """Settings for the documents app.

    Kept as its own table rather than folded into :class:`AppSetting` because an
    existing deployment already has one, and because the documents pipeline
    reads these fields on a hot path where a typed column beats a JSON probe.
    """

    __tablename__ = "workspace_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    spreadsheet_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    spreadsheet_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The two tabs of the invoice/ticket era. Only the migration reads them now.
    sheet_name: Mapped[str] = mapped_column(String(255), default="Factures")
    ticket_sheet_name: Mapped[str] = mapped_column(String(255), default="Tiquets")
    registry_sheet_name: Mapped[str] = mapped_column(
        String(255), default="Registre documents comptables"
    )
    migration_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    openai_model: Mapped[str] = mapped_column(String(120), default="gpt-6-luna")
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
    document_type: Mapped[str] = mapped_column(String(40), default="invoice", index=True)
    source_file_name: Mapped[str] = mapped_column(String(255))
    source_file_type: Mapped[str] = mapped_column(String(120))
    stored_path: Mapped[str] = mapped_column(Text)
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: ``camera`` or ``file``: whether the person photographed the document in
    #: the app or picked an existing file. Decides the register's "Foto o original".
    capture_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
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


class Document(Base):
    """One entry of the accounting register — the hub's own copy of it.

    The spreadsheet is where people work, but it is a mirror: every field lives
    here first, edits made in the sheet are pulled back on each sync, and a row
    deleted there is kept here (``sheet_state = "removed"``) rather than lost.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    internal_doc_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tipus_document: Mapped[str] = mapped_column(String(60), default="")
    origen: Mapped[str] = mapped_column(String(20), default="")
    num_factura: Mapped[str] = mapped_column(String(255), default="")
    data_factura: Mapped[date | None] = mapped_column(Date, nullable=True)
    proveidor: Mapped[str] = mapped_column(Text, default="")
    cif_proveidor: Mapped[str] = mapped_column(String(64), default="")
    carrer: Mapped[str] = mapped_column(Text, default="")
    codi_postal: Mapped[str] = mapped_column(String(20), default="")
    ciutat: Mapped[str] = mapped_column(String(255), default="")
    compte_corrent: Mapped[str] = mapped_column(String(64), default="")
    cif_proveit: Mapped[str] = mapped_column(String(64), default="")
    import_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    descripcio: Mapped[str] = mapped_column(Text, default="")
    descripcio_compra: Mapped[str] = mapped_column(Text, default="")
    pagament: Mapped[str] = mapped_column(String(60), default="")
    pagament_observacions: Mapped[str] = mapped_column(Text, default="")
    metode_pagament: Mapped[str] = mapped_column(String(60), default="")
    data_pagament: Mapped[date | None] = mapped_column(Date, nullable=True)
    subministrat: Mapped[str] = mapped_column(String(60), default="")
    pressupost_afectat: Mapped[str] = mapped_column(Text, default="")
    responsable_nom: Mapped[str] = mapped_column(String(255), default="", server_default="")
    responsable_email: Mapped[str] = mapped_column(String(255), default="", server_default="")
    validat: Mapped[bool] = mapped_column(Boolean, default=False)

    #: The "Fitxer" cell: an ``=IMAGE(...)`` formula or a Drive link.
    file_link: Mapped[str] = mapped_column(Text, default="")
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transcripcio: Mapped[str] = mapped_column(Text, default="")
    #: Field → :class:`~cosecre_hub.schemas.AiHint` as a dict.
    ai_hints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The latest model run, step by step — see ``ExtractedDocument.trace``.
    ai_trace: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(40), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sheet_state: Mapped[str] = mapped_column(String(16), default="pending")
    sheet_row_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The register values as of the last time this entry and its sheet row were
    #: known to agree — the common ancestor of a three-way comparison. It is
    #: what tells "edited in the sheet" from "edited here" from "both".
    sheet_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: ``invoice`` or ``ticket`` for entries migrated from the two old tabs.
    legacy_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Set once a migrated entry has been re-read by the models for the new fields.
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    upload: Mapped["Upload | None"] = relationship()


class Responsable(Base):
    """A name/email pair someone has entered as an entry's responsible person.

    Kept so the form can offer names already used instead of retyping them, and
    spot a near-miss ("Susna") of one that exists. One row per distinct pair;
    either half may be empty.
    """

    __tablename__ = "responsables"
    __table_args__ = (UniqueConstraint("nom_key", "email", name="uq_responsables_nom_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nom: Mapped[str] = mapped_column(String(255), default="")
    #: ``nom`` folded (lower case, no accents, single spaces): what makes
    #: "Susana  Pérez" and "susana perez" the same person.
    nom_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    uses: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
