"""The school's budget lines (partides) and which statement movements are charged to them.

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
from ...models import BankMovement, utcnow


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
    #: Gone from the latest import but kept, because movements are charged to it.
    retirada: Mapped[bool] = mapped_column(Boolean, default=False)
    #: What the secretari/a wrote about when to use this line. Read by Jev.
    context: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MovementPartida(Base):
    """One statement movement charged to one line. A movement may have several.

    esfer@ books the money that moved, not the paper behind it: what is
    charged to a line is the bank (or caixeta, or card) movement, and the
    invoices it paid are only what tells which line.
    """

    __tablename__ = "movement_partides"
    __table_args__ = (
        UniqueConstraint("movement_id", "partida_id", name="uq_movement_partides_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_movements.id", ondelete="CASCADE"), index=True
    )
    partida_id: Mapped[int] = mapped_column(
        ForeignKey("partides.id", ondelete="CASCADE"), index=True
    )
    #: The part of the movement charged here, when it is split. ``None`` = all of it.
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


class MovementPartidaSuggestion(Base):
    """Jev's latest ranking for a movement, kept to show the alternatives."""

    __tablename__ = "movement_partida_suggestions"

    movement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_movements.id", ondelete="CASCADE"), primary_key=True
    )
    #: ``[{"partida_id": 12, "probability": 0.61, "jev": 0.48}, …]``, best first;
    #: ``probability`` is after the history weighed in, ``jev`` before.
    ranking: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    #: Probability that the payment spans several budget concepts.
    multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Probability of "no line fits".
    cap: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartidaDecision(Base):
    """What Jev put first for a movement and what a person charged it to.

    Written when a person confirms the lines, so a later re-ask cannot hide
    that Jev was wrong. Names are kept as they were: lines are per year.
    """

    __tablename__ = "partida_decisions"

    movement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_movements.id", ondelete="CASCADE"), primary_key=True
    )
    proposada_codi: Mapped[str] = mapped_column(String(64), default="")
    proposada_nom: Mapped[str] = mapped_column(Text, default="")
    #: Jev's probability for it, after the history weighed in.
    probabilitat: Mapped[float] = mapped_column(Float, default=0.0)
    #: ``[{"codi": …, "nom": …}, …]``: what the person confirmed.
    triades: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    #: The person did not keep Jev's first line.
    corregida: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(BankMovement, "after_delete")
def _forget_movement(mapper, connection, target: BankMovement) -> None:
    """SQLite does not enforce the cascades, and a reused id would inherit them."""
    for table in (
        MovementPartida.__table__,
        MovementPartidaSuggestion.__table__,
        PartidaDecision.__table__,
    ):
        connection.execute(delete(table).where(table.c.movement_id == target.id))
