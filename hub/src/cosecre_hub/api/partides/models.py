"""The school's budget lines (partides) and which invoices are charged to them.

A budget comes from esfer@ once a year as an Excel; importing it again updates
the lines in place, keyed by ``(exercici, codi)``, so the assignments already
made — and the context written for each line — survive a re-import.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    delete,
    event,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base
from ...models import Document, utcnow


class Pressupost(Base):
    """One year's budget, as the esfer@ export described it."""

    __tablename__ = "pressupostos"

    exercici: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    centre: Mapped[str] = mapped_column(String(255), default="")
    nif: Mapped[str] = mapped_column(String(32), default="")
    codi_centre: Mapped[str] = mapped_column(String(32), default="")
    #: The report's own date ("Data: 12/10/2026"), as written.
    data_informe: Mapped[str] = mapped_column(String(32), default="")
    total_ingressos: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_despeses: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), default="")
    imported_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Partida(Base):
    __tablename__ = "partides"
    __table_args__ = (UniqueConstraint("exercici", "codi", name="uq_partides_exercici_codi"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercici: Mapped[int] = mapped_column(Integer, index=True)
    #: ``despesa`` or ``ingres``.
    tipus: Mapped[str] = mapped_column(String(16), default="despesa")
    codi: Mapped[str] = mapped_column(String(64))
    #: The line this one is a sub-line of, by code; ``None`` at the top level.
    codi_pare: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: esfer@'s "codi finalista": the earmarked fund the money comes from.
    codi_finalista: Mapped[str] = mapped_column(String(64), default="")
    nom: Mapped[str] = mapped_column(Text, default="")
    import_pressupost: Mapped[float] = mapped_column(Float, default=0.0)
    #: Position in the export, which is esfer@'s own order.
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    #: Gone from the latest import but kept, because invoices are charged to it.
    retirada: Mapped[bool] = mapped_column(Boolean, default=False)
    #: What the secretari/a wrote about when to use this line. Read by Jev.
    context: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DocumentPartida(Base):
    """One invoice charged to one line. An invoice may have several."""

    __tablename__ = "document_partides"
    __table_args__ = (
        UniqueConstraint("document_id", "partida_id", name="uq_document_partides_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    partida_id: Mapped[int] = mapped_column(
        ForeignKey("partides.id", ondelete="CASCADE"), index=True
    )
    #: The part of the invoice charged here, when it is split. ``None`` = all of it.
    import_assignat: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: ``persona`` or ``jev``: who first put it there.
    origen: Mapped[str] = mapped_column(String(16), default="persona")
    #: Jev's probability for this line, when Jev proposed it.
    confianca: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: False while it is only Jev's preliminary proposal.
    confirmada: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartidaSuggestion(Base):
    """Jev's latest ranking for an invoice, kept to show the alternatives."""

    __tablename__ = "partida_suggestions"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    #: ``[{"partida_id": 12, "probability": 0.61}, …]``, best first.
    ranking: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    #: Probability that the purchase spans several budget concepts.
    multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Probability of "no line fits".
    cap: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Document, "after_delete")
def _forget_document(mapper, connection, target: Document) -> None:
    """SQLite does not enforce the cascades, and a reused id would inherit them."""
    for table in (DocumentPartida.__table__, PartidaSuggestion.__table__):
        connection.execute(delete(table).where(table.c.document_id == target.id))
