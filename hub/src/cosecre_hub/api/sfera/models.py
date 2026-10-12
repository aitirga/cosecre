"""Export plans to Esfer@: what was prepared, approved, attempted and confirmed.

The Hub keeps the plan and the journal; a desktop runner with the person's own
portal session claims one item at a time, sends it and reports back. An attempt
is persisted *before* the call, so a runner that dies mid-write leaves an
``executing`` item that is recovered as ``uncertain`` and reconciled by reading
the portal, never retried blind.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base
from ...models import utcnow

#: Item states. ``blocked``/``ready`` come from the preflight; approval turns
#: ``ready`` into ``approved``; the runner moves it on from there.
ITEM_STATES = (
    "blocked", "ready", "approved", "executing", "succeeded",
    "uncertain", "reconciled", "conflict", "failed", "cancelled",
)
#: An item in one of these still holds its source and duplicate key.
ACTIVE_STATES = ("ready", "approved", "executing", "uncertain", "conflict", "failed")


class SferaExportPlan(Base):
    __tablename__ = "sfera_export_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(String(20), default="blocked", index=True)
    environment: Mapped[str] = mapped_column(String(20))
    centre_code: Mapped[str] = mapped_column(String(16), index=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan_hash: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    items: Mapped[list["SferaExportItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="SferaExportItem.id"
    )


class SferaExportItem(Base):
    __tablename__ = "sfera_export_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("sfera_export_plans.id", ondelete="CASCADE"), index=True)
    entity: Mapped[str] = mapped_column(String(40), default="supplier_invoice")
    source_ref: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    movement_id: Mapped[int | None] = mapped_column(ForeignKey("bank_movements.id", ondelete="SET NULL"), nullable=True)
    duplicate_key: Mapped[str] = mapped_column(String(300), index=True)
    state: Mapped[str] = mapped_column(String(20), default="blocked", index=True)
    problems: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    #: The Cosecre contract as submitted (decimals as strings).
    invoice: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The portal body derived from it.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    remote_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    plan: Mapped[SferaExportPlan] = relationship(back_populates="items")
    attempts: Mapped[list["SferaExportAttempt"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="SferaExportAttempt.id"
    )


class SferaExportAttempt(Base):
    __tablename__ = "sfera_export_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("sfera_export_items.id", ondelete="CASCADE"), index=True)
    #: ``pending`` while the runner holds it; then the reported outcome.
    outcome: Mapped[str] = mapped_column(String(20), default="pending")
    runner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    item: Mapped[SferaExportItem] = relationship(back_populates="attempts")


class SferaRemoteMapping(Base):
    """A local record and the remote one it became, within one environment and centre.

    The same numeric ID can exist in formació and production or in two centres,
    so the context is part of the key.
    """

    __tablename__ = "sfera_remote_mappings"
    __table_args__ = (
        UniqueConstraint("environment", "centre_code", "entity", "duplicate_key", name="uq_sfera_mapping_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    environment: Mapped[str] = mapped_column(String(20))
    centre_code: Mapped[str] = mapped_column(String(16))
    entity: Mapped[str] = mapped_column(String(40))
    duplicate_key: Mapped[str] = mapped_column(String(300))
    source_ref: Mapped[str] = mapped_column(String(64))
    remote_id: Mapped[int] = mapped_column(Integer)
    remote_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("sfera_export_items.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
