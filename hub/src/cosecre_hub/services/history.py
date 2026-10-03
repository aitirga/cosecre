"""Undo and redo for every change, by recording what each action did to the rows.

Every request that changes something (and what the hub does on its own, such as
removing a duplicate) runs inside an *action*. While one is active, each flush
records, for every row of a tracked table it touched, the values before and
after. Undoing replays that backwards; redoing replays it forwards. Either
refuses — and changes nothing — when a row has moved on since, so an undo never
overwrites someone else's later work.

The sheet and Drive are not recorded here: they follow the database (see
:func:`cosecre_hub.api.history.after_replay`).
"""

from __future__ import annotations

import contextvars
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from sqlalchemy import Date, DateTime, and_, delete, event, inspect, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import Base
from ..models import HistoryAction, HistoryChange

logger = logging.getLogger(__name__)

#: What undo covers. Accounts, sessions and the history itself are not.
TRACKED = {
    "documents",
    "uploads",
    "extraction_jobs",
    "payment_matches",
    "bank_movements",
    "statement_imports",
    "responsables",
    "workspace_settings",
    "app_settings",
}
#: Bookkeeping that follows from the rest, never restored.
IGNORED = {"updated_at"}
IGNORED_BY_TABLE = {"documents": {"sheet_state", "sheet_row_ref", "sheet_snapshot"}}
#: A document still being read cannot be undone under the extraction's feet.
IN_FLIGHT = {"pending", "processing", "written_to_sheet"}

TABLE_LABEL = {
    "documents": "un document",
    "uploads": "un fitxer pujat",
    "extraction_jobs": "una lectura",
    "payment_matches": "una justificació",
    "bank_movements": "un moviment",
    "statement_imports": "un extracte",
    "responsables": "una persona",
    "workspace_settings": "la configuració",
    "app_settings": "una preferència",
}

#: ``(method, path suffix)`` → what people see. The first match wins.
LABELS: list[tuple[str, str, str]] = [
    ("POST", "/documents/records/upload", "Document pujat"),
    ("POST", "/documents/records/sync/pull", "Canvis del full integrats"),
    ("POST", "/documents/records/sync/push", "Registre enviat al full"),
    ("POST", "/documents/records/sync", "Sincronització amb el full"),
    ("POST", "/validate", "Document validat"),
    ("PATCH", "/documents/records/{reference}", "Document editat"),
    ("DELETE", "/documents/records/{reference}", "Document esborrat"),
    ("PUT", "/documents/settings", "Configuració del full"),
    ("POST", "/documents/migration/drive", "Originals pujats a Drive"),
    ("POST", "/documents/migration/enrich", "Documents antics completats"),
    ("POST", "/documents/migration", "Migració dels fulls antics"),
    ("POST", "/reconciliation/runs", "Justificació automàtica"),
    ("POST", "/movements/{movement_id}/confirm", "Pagament justificat"),
    ("POST", "/movements/{movement_id}/reject", "Moviment sense factura"),
    ("POST", "/matches/{match_id}/reject", "Proposta descartada"),
    ("POST", "/movements/{movement_id}/undo", "Justificació desfeta"),
    ("POST", "/movements/{movement_id}/repropose", "Nova proposta"),
    ("POST", "/statements/upload", "Extracte importat"),
    ("DELETE", "/statements/imports/{statement_id}", "Extracte esborrat"),
    ("PATCH", "/statements/movements/{movement_id}", "Moviment corregit"),
    ("POST", "/statements/caixeta/sync", "Caixeta sincronitzada"),
    ("PUT", "/settings", "Preferències"),
    ("DELETE", "/settings/{key}", "Preferències"),
]
_LABEL_PATTERNS = [
    (verb, re.compile(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(suffix)) + "$"), label)
    for verb, suffix, label in LABELS
]
#: Requests that never become actions.
UNTRACKED_PREFIXES = ("/auth", "/users", "/llm", "/backups", "/history", "/meta")


# ── The action in progress ───────────────────────────────────────────────────


@dataclass
class ActionContext:
    label: str | None = None
    kind: str = "person"
    user_id: int | None = None
    #: The ASGI scope, to name the action after the route that ran.
    scope: dict[str, Any] | None = field(default=None, repr=False)
    #: Set once the first change is written.
    id: int | None = None

    def resolved_label(self) -> str:
        if self.label:
            return self.label
        path = (self.scope or {}).get("path", "").rstrip("/")
        method = (self.scope or {}).get("method", "")
        for verb, pattern, label in _LABEL_PATTERNS:
            if verb == method and pattern.search(path):
                return label
        return "Canvi"


_current: contextvars.ContextVar[ActionContext | None] = contextvars.ContextVar("history_action", default=None)


def current() -> ActionContext | None:
    return _current.get()


@contextmanager
def action(label: str, *, kind: str = "auto", user_id: int | None = None) -> Iterator[ActionContext]:
    """Run a block as its own action (the hub acting on its own, mostly)."""
    ctx = ActionContext(label=label, kind=kind, user_id=user_id)
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def begin_request(scope: dict[str, Any], api_prefix: str) -> contextvars.Token | None:
    if scope.get("type") != "http" or scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    path = scope.get("path", "")
    if path.startswith(api_prefix):
        path = path[len(api_prefix):]
    if path.startswith(UNTRACKED_PREFIXES):
        return None
    return _current.set(ActionContext(scope=scope))


def end_request(token: contextvars.Token | None) -> None:
    if token is not None:
        _current.reset(token)


# ── Values ───────────────────────────────────────────────────────────────────


def _columns(table_name: str) -> list[str]:
    skip = IGNORED | IGNORED_BY_TABLE.get(table_name, set())
    return [c.name for c in Base.metadata.tables[table_name].columns if c.name not in skip]


def _to_json(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _from_json(table_name: str, values: dict[str, Any]) -> dict[str, Any]:
    table = Base.metadata.tables[table_name]
    out: dict[str, Any] = {}
    for name, value in values.items():
        if name not in table.c:
            continue
        kind = table.c[name].type
        if value is not None and isinstance(kind, DateTime):
            value = datetime.fromisoformat(value)
        elif value is not None and isinstance(kind, Date):
            value = date.fromisoformat(value)
        out[name] = value
    return out


def _where(table_name: str, pk: dict[str, Any]):
    table = Base.metadata.tables[table_name]
    return and_(*[table.c[name] == value for name, value in pk.items()])


def _read(conn, table_name: str, pk: dict[str, Any]) -> dict[str, Any] | None:
    table = Base.metadata.tables[table_name]
    row = conn.execute(
        select(*[table.c[name] for name in _columns(table_name)]).where(_where(table_name, pk))
    ).mappings().first()
    return None if row is None else {name: _to_json(value) for name, value in row.items()}


def _identity(obj) -> tuple[str, dict[str, Any]] | None:
    state = inspect(obj)
    table_name = state.mapper.local_table.name
    if table_name not in TRACKED:
        return None
    # A row inserted in this flush has its key, but no identity until it ends.
    key = state.identity or state.mapper.primary_key_from_instance(obj)
    if key is None or any(part is None for part in key):
        return None
    names = [column.name for column in state.mapper.primary_key]
    return table_name, dict(zip(names, key, strict=True))


# ── Recording ────────────────────────────────────────────────────────────────


@event.listens_for(Session, "before_flush")
def _before_flush(session: Session, _flush_context, _instances) -> None:
    if current() is None:
        return
    conn = session.connection()
    before = session.info.setdefault("history_before", {})
    objects = list(session.dirty) + list(session.deleted)
    for obj in list(session.deleted):
        state = inspect(obj)
        objects.extend(child for child, *_ in state.mapper.cascade_iterator("delete", state))
    for obj in objects:
        identity = _identity(obj)
        if identity is None:
            continue
        key = (identity[0], tuple(sorted(identity[1].items())))
        if key not in before:
            before[key] = _read(conn, *identity)


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, _flush_context) -> None:
    ctx = current()
    if ctx is None:
        return
    conn = session.connection()
    before: dict = session.info.pop("history_before", {})
    rows: list[dict[str, Any]] = []
    for obj in session.new:
        identity = _identity(obj)
        if identity is not None:
            rows.append({"table_name": identity[0], "op": "insert", "pk": identity[1],
                         "before": None, "after": _read(conn, *identity)})
    for (table_name, pk_items), old in before.items():
        if old is None:
            continue
        pk = dict(pk_items)
        new = _read(conn, table_name, pk)
        if new is None:
            rows.append({"table_name": table_name, "op": "delete", "pk": pk, "before": old, "after": None})
            continue
        changed = [name for name in new if old.get(name) != new.get(name)]
        if changed:
            rows.append({"table_name": table_name, "op": "update", "pk": pk,
                         "before": {n: old.get(n) for n in changed}, "after": {n: new[n] for n in changed}})
    if not rows:
        return
    action_id = _ensure_action(session, conn, ctx)
    conn.execute(insert(HistoryChange.__table__), [{**row, "action_id": action_id} for row in rows])


def _ensure_action(session: Session, conn, ctx: ActionContext) -> int:
    if ctx.id is not None:
        return ctx.id
    now = datetime.now(UTC)
    result = conn.execute(insert(HistoryAction.__table__).values(
        label=ctx.resolved_label(), kind=ctx.kind, user_id=ctx.user_id,
        state="done", created_at=now, done_at=now,
    ))
    ctx.id = result.inserted_primary_key[0]
    session.info.setdefault("history_created", []).append(ctx)
    if ctx.kind == "person" and ctx.user_id is not None:
        # Something new ends what could be redone, as in any editor.
        conn.execute(
            update(HistoryAction.__table__)
            .where(HistoryAction.user_id == ctx.user_id, HistoryAction.kind == "person",
                   HistoryAction.state == "undone")
            .values(state="dropped")
        )
    return ctx.id


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    for ctx in session.info.pop("history_created", []):
        ctx.id = None
    session.info.pop("history_before", None)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    session.info.pop("history_created", None)


# ── Replaying ────────────────────────────────────────────────────────────────


class HistoryConflict(Exception):
    pass


Direction = Literal["undo", "redo"]


def replay(session: Session, target: HistoryAction, direction: Direction) -> list[HistoryChange]:
    """Undo or redo one action in the session's transaction. Raises on conflict.

    The caller commits — or rolls back, on :class:`HistoryConflict`, so a
    half-replayed action never lands.
    """
    order = HistoryChange.id.desc() if direction == "undo" else HistoryChange.id.asc()
    changes = session.query(HistoryChange).filter(HistoryChange.action_id == target.id).order_by(order).all()
    conn = session.connection()
    for document_id in {c.pk.get("id") for c in changes if c.table_name == "documents"}:
        row = _read(conn, "documents", {"id": document_id})
        if row is not None and row.get("status") in IN_FLIGHT:
            raise HistoryConflict("Encara s'està llegint un dels documents; torna-ho a provar d'aquí a un moment.")
    for change in changes:
        table_name = change.table_name
        if table_name not in Base.metadata.tables:
            continue
        table = Base.metadata.tables[table_name]
        where = _where(table_name, change.pk)
        now = _read(conn, table_name, change.pk)
        what = TABLE_LABEL.get(table_name, table_name)

        # What the row must look like now, and what it becomes.
        if direction == "undo":
            expected, target_values = change.after, change.before
            op = {"insert": "remove", "delete": "add", "update": "set"}[change.op]
        else:
            expected, target_values = change.before, change.after
            op = {"insert": "add", "delete": "remove", "update": "set"}[change.op]

        try:
            if op == "remove":
                if now is None:
                    continue
                if expected and any(now.get(n) != v for n, v in expected.items() if n in now):
                    raise HistoryConflict(f"No es pot: {what} ha canviat després.")
                conn.execute(delete(table).where(where))
            elif op == "add":
                if now is not None:
                    raise HistoryConflict(f"No es pot: {what} ja hi torna a ser.")
                conn.execute(insert(table).values(**_from_json(table_name, target_values or {})))
            else:
                if now is None:
                    raise HistoryConflict(f"No es pot: {what} ja no hi és.")
                if any(now.get(n) != v for n, v in (expected or {}).items()):
                    raise HistoryConflict(f"No es pot: {what} s'ha tornat a canviar després.")
                conn.execute(update(table).where(where).values(**_from_json(table_name, target_values or {})))
        except IntegrityError as exc:
            raise HistoryConflict(f"No es pot: {what} xocaria amb un altre registre.") from exc

    stamp = datetime.now(UTC)
    if direction == "undo":
        target.state, target.undone_at = "undone", stamp
    else:
        target.state, target.done_at, target.undone_at = "done", stamp, None
    return changes
