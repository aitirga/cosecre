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
    #: The three CaixaBank accounts, by IBAN: a dropped statement names its own
    #: IBAN in its title, and this is what turns that into a ``compte``.
    iban_general: Mapped[str] = mapped_column(String(64), default="", server_default="")
    iban_material: Mapped[str] = mapped_column(String(64), default="", server_default="")
    iban_menjador: Mapped[str] = mapped_column(String(64), default="", server_default="")
    prepaid_card_number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    caixeta_spreadsheet_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    caixeta_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: The spreadsheet's Drive ``modifiedTime`` at the last read: unchanged means
    #: there is nothing to read again.
    caixeta_fingerprint: Mapped[str] = mapped_column(String(64), default="", server_default="")
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


class DuplicateRemoval(Base):
    """A register entry taken out because another one said exactly the same.

    The entry itself is gone from the database and the sheet; this keeps what it
    said, which entry it repeated, and where its original file still is.
    """

    __tablename__ = "duplicate_removals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(64), index=True)
    kept_reference: Mapped[str] = mapped_column(String(64), index=True)
    #: The entry's register values, as ``snapshot_values`` writes them.
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entry_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    #: The history action that removed it; undoing that action restores it.
    action_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    #: Set while the entry is back: a restored entry is never removed again.
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


# ── Bank statements ──────────────────────────────────────────────────────────


class StatementImport(Base):
    """One statement brought in: a dropped file, or the caixeta sheet.

    The caixeta has a single, living import that every sync updates, so it shows
    up in lists the same way a file does.
    """

    __tablename__ = "statement_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: ``caixa_xls``, ``prepaid_pdf`` or ``caixeta_sheet``.
    source: Mapped[str] = mapped_column(String(20), index=True)
    #: One of ``COMPTES``: which of the five places the money moved in.
    compte: Mapped[str] = mapped_column(String(40), index=True)
    account_iban: Mapped[str] = mapped_column(String(64), default="")
    file_name: Mapped[str] = mapped_column(String(255), default="")
    stored_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="done")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_new: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    created_by: Mapped["User | None"] = relationship()
    movements: Mapped[list["BankMovement"]] = relationship(back_populates="statement")


class BankMovement(Base):
    """One line of a statement: money that left (or entered) an account.

    ``fingerprint`` is what makes bringing the same statement in twice — or two
    overlapping periods — harmless: a line already known is counted, not added.
    """

    __tablename__ = "bank_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("statement_imports.id", ondelete="CASCADE"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(20))
    compte: Mapped[str] = mapped_column(String(40), index=True)
    #: A ``METODES_PAGAMENT`` label: how the money moved.
    tipus: Mapped[str] = mapped_column(String(40), default="")
    #: ``pagament`` for a payment that should have an invoice behind it; anything
    #: else (``comissio``, ``traspas_intern``, ``ingres``, ``devolucio``,
    #: ``saldo_inicial``) is never matched.
    categoria: Mapped[str] = mapped_column(String(20), default="pagament")
    data: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    data_valor: Mapped[date | None] = mapped_column(Date, nullable=True)
    concepte: Mapped[str] = mapped_column(Text, default="")
    mes_dades: Mapped[str] = mapped_column(Text, default="")
    import_value: Mapped[float] = mapped_column(Float, default=0.0)
    saldo: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_factura_hint: Mapped[str] = mapped_column(String(255), default="")
    cif_hint: Mapped[str] = mapped_column(String(64), default="")
    iban_hint: Mapped[str] = mapped_column(String(64), default="")
    #: The source's own key for the line, when it has one (``Cix_012``).
    external_ref: Mapped[str] = mapped_column(String(64), default="")
    #: Our own key for the line, one series per account (``TP_007``, ``MEN_112``);
    #: the caixeta keeps its sheet's ``Cix_NNN``. See ``statements.store.assign_codes``.
    codi: Mapped[str] = mapped_column(String(20), default="", server_default="", index=True)
    #: What the statements mirror last wrote in this line's "Codi intern factura"
    #: and "Núm. factura" cells; ``None`` until it has written the line at all.
    #: A cell that differs from these was edited by hand. See
    #: ``api.statements_mirror``.
    mirror_refs: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_numbers: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: ``unmatched``, ``proposed``, ``confirmed``, ``rejected`` or ``not_applicable``.
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched", index=True)
    #: The other half of an internal transfer (a prepaid top-up and its charge).
    linked_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_movements.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    statement: Mapped["StatementImport"] = relationship(back_populates="movements")
    matches: Mapped[list["PaymentMatch"]] = relationship(
        back_populates="movement", cascade="all, delete-orphan"
    )


class PaymentMatch(Base):
    """A proposed or confirmed link between a movement and a register entry.

    Several rows for one movement mean it paid several invoices at once.
    """

    __tablename__ = "payment_matches"
    __table_args__ = (
        UniqueConstraint("movement_id", "document_id", name="uq_payment_matches_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_movements.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    #: 0–100, the one number people see. See ``services.matching.confidence``.
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    #: Rank among the proposals for this movement; 0 is the one put forward.
    rank: Mapped[int] = mapped_column(Integer, default=0)
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: ``rules``, ``openai``, ``jev``, ``jev+openai`` or ``person``.
    decided_by: Mapped[str] = mapped_column(String(20), default="rules")
    reason: Mapped[str] = mapped_column(Text, default="")
    ai_trace: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: ``proposed``, ``alternative``, ``confirmed`` or ``rejected``.
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    confirmed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    movement: Mapped["BankMovement"] = relationship(back_populates="matches")
    document: Mapped["Document"] = relationship()


class MatchRun(Base):
    """One press of "Començar justificació": progress for the button to show."""

    __tablename__ = "match_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The statement it ran over; ``None`` means every statement.
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("statement_imports.id", ondelete="CASCADE"), nullable=True
    )
    #: ``running``, ``done`` or ``error``.
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    proposed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── History: undo and redo ───────────────────────────────────────────────────


class HistoryAction(Base):
    """One thing someone did — an edit, a deletion, a confirmed payment — or the
    hub did on its own, with every row it changed in :class:`HistoryChange`."""

    __tablename__ = "history_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(255), default="")
    #: ``person`` for a request, ``auto`` for what the hub does by itself.
    kind: Mapped[str] = mapped_column(String(16), default="person")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: ``done`` or ``undone``.
    state: Mapped[str] = mapped_column(String(16), default="done", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    #: When it last took effect: created, or redone. Undo picks the latest.
    done_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HistoryChange(Base):
    """One row inserted, updated or deleted by an action: its values before and after."""

    __tablename__ = "history_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_id: Mapped[int] = mapped_column(
        ForeignKey("history_actions.id", ondelete="CASCADE"), index=True
    )
    table_name: Mapped[str] = mapped_column(String(64))
    #: ``insert``, ``update`` or ``delete``.
    op: Mapped[str] = mapped_column(String(8))
    pk: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Only the columns that changed, for an update; the whole row otherwise.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
