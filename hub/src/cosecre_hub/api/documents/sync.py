"""Keeping the sheet and the database in step — deliberately.

Every entry remembers the values it had the last time it and its sheet row
agreed (``Document.sheet_snapshot``). Comparing the sheet and the database
against that common ancestor says *who* changed what, the way a version
control system does:

=================  ============================================  ===============
status             meaning                                       done by
=================  ============================================  ===============
``db_changed``     edited in the app, the sheet is behind         automatically
``not_in_sheet``   never written to the sheet yet                 automatically
``sheet_changed``  edited in the sheet, the database is behind    automatically
``new_in_sheet``   a row typed into the sheet                     automatically
``missing``        the row was deleted from the sheet             a person: pull
``conflict``       edited on both sides                           a person
=================  ============================================  ===============

Whatever only one side changed travels on its own, both ways: the sheet's
edits come in as one undoable action. What both sides changed, and rows
deleted from the sheet, wait for a person; a pull or push they ask for is
preceded by a backup.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from ...deps import get_workspace_setting
from ...models import Document, PaymentMatch
from ...schemas import SyncResult
from ...services import history, people
from ...services.sheets import (
    COLUMNS_BY_FIELD,
    GoogleSheetsService,
    SheetRow,
    changed_fields,
    has_substance,
    snapshot_values,
)
from .duplicates import remove_duplicates
from .register import (
    IN_FLIGHT,
    apply_values,
    confirm_hints,
    document_snapshot,
    generate_reference,
    sheet_values,
    status_after_review,
)

logger = logging.getLogger(__name__)

#: Lists poll every few seconds; Google does not need to hear about each one.
SYNC_INTERVAL_SECONDS = 20

Status = Literal["db_changed", "not_in_sheet", "sheet_changed", "new_in_sheet", "missing", "conflict"]
#: What a pull (sheet → database) acts on, and what a push (database → sheet) does.
PULLABLE = {"sheet_changed", "new_in_sheet", "missing", "conflict"}
PUSHABLE = {"db_changed", "not_in_sheet", "sheet_changed", "missing", "conflict"}
AUTOMATIC = {"db_changed", "not_in_sheet"}


@dataclass
class Change:
    field: str
    label: str
    db: Any
    sheet: Any


@dataclass
class DiffEntry:
    reference: str
    status: Status
    row: int | None
    num_factura: str
    proveidor: str
    changes: list[Change] = field(default_factory=list)
    # Not serialised: what applying this entry needs.
    _document: Document | None = None
    _row: SheetRow | None = None


def _label(name: str) -> str:
    return COLUMNS_BY_FIELD[name].header


def _changes(db: dict[str, Any], sheet: dict[str, Any]) -> list[Change]:
    return [Change(n, _label(n), db.get(n), sheet.get(n)) for n in changed_fields(db, sheet)]


def compute_diff(rows: list[SheetRow], documents: list[Document]) -> list[DiffEntry]:
    by_reference = {d.internal_doc_number: d for d in documents}
    entries: list[DiffEntry] = []
    seen: set[str] = set()

    for row in rows:
        reference = str(row.values.get("num_doc_intern") or "").strip()
        sheet = snapshot_values(row.values)
        document = by_reference.get(reference) if reference and reference not in seen else None
        if document is None:
            empty = snapshot_values({})
            entries.append(DiffEntry(
                reference=reference, status="new_in_sheet", row=row.row_number,
                num_factura=str(sheet.get("num_factura") or ""), proveidor=str(sheet.get("proveidor") or ""),
                changes=_changes(empty, sheet), _row=row,
            ))
            continue
        seen.add(reference)
        db = document_snapshot(document)
        if db == sheet:
            continue
        base = document.sheet_snapshot
        if base is None:
            # No common ancestor yet (entries from before versioning): an
            # unsent local edit says the database moved; otherwise the sheet did.
            status: Status = "db_changed" if document.sheet_state == "pending" else "sheet_changed"
        else:
            sheet_moved, db_moved = sheet != base, db != base
            status = "conflict" if sheet_moved and db_moved else "sheet_changed" if sheet_moved else "db_changed"
        entries.append(DiffEntry(
            reference=reference, status=status, row=row.row_number,
            num_factura=document.num_factura, proveidor=document.proveidor,
            changes=_changes(db, sheet), _document=document, _row=row,
        ))

    for document in documents:
        if document.internal_doc_number in seen or document.sheet_state == "removed":
            continue
        if document.status in IN_FLIGHT:
            continue
        was_there = document.sheet_snapshot is not None and document.sheet_state == "synced"
        entries.append(DiffEntry(
            reference=document.internal_doc_number,
            status="missing" if was_there else "not_in_sheet",
            row=None, num_factura=document.num_factura, proveidor=document.proveidor,
            _document=document,
        ))
    return entries


def summarize(entries: list[DiffEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return counts


def _read(app, session: Session) -> tuple[GoogleSheetsService, Any, list[SheetRow], list[Document]]:
    service: GoogleSheetsService = app.state.sheet_service
    workspace = get_workspace_setting(session)
    rows = service.read_register(workspace)
    return service, workspace, rows, session.query(Document).all()


def _baseline_agreeing(rows: list[SheetRow], documents: list[Document]) -> None:
    """Entries that agree with their row get that agreement recorded as their base."""
    by_reference = {d.internal_doc_number: d for d in documents}
    for row in rows:
        document = by_reference.get(str(row.values.get("num_doc_intern") or ""))
        if document is None or document.status in IN_FLIGHT:
            continue
        sheet = snapshot_values(row.values)
        if document_snapshot(document) == sheet:
            document.sheet_row_ref = row.row_number
            if document.sheet_snapshot != sheet:
                document.sheet_snapshot = sheet
            if document.sheet_state != "synced":
                document.sheet_state = "synced"


def _write(service, workspace, document: Document, entry: DiffEntry) -> None:
    if entry.row is not None:
        service.write_row(workspace, entry.row, sheet_values(document))
        document.sheet_row_ref = entry.row
    else:
        document.sheet_row_ref = service.append_row(workspace, sheet_values(document))
    document.sheet_state = "synced"
    document.sheet_snapshot = document_snapshot(document)


def _pull_entry(session: Session, entry: DiffEntry, reference_writes: list[tuple[int, dict[str, Any]]]) -> None:
    """Bring one sheet row into the database, as its status says."""
    row = entry._row
    if entry.status == "missing":
        _drop(session, entry._document)
        return
    if entry.status == "new_in_sheet":
        reference = entry.reference
        if not reference or session.query(Document).filter_by(internal_doc_number=reference).first():
            reference = generate_reference()
            reference_writes.append((row.row_number, {"num_doc_intern": reference}))
        document = Document(internal_doc_number=reference, sheet_state="synced")
        session.add(document)
    else:
        document = entry._document
    changed = apply_values(document, row.values)
    if {"responsable_nom", "responsable_email"} & set(changed):
        people.remember(session, document.responsable_nom, document.responsable_email)
    confirm_hints(document, changed)
    if document.status not in IN_FLIGHT:
        document.status = status_after_review(document)
    document.sheet_state = "synced"
    document.sheet_row_ref = row.row_number
    document.sheet_snapshot = snapshot_values(row.values)


def _drop(session: Session, document: Document) -> None:
    """Take an entry out because its row was deleted from the sheet.

    Its payment links go with it; the upload (and its file) stays. Undoing the
    action brings it back as an entry the sheet lacks, so it is written there again.
    """
    for match in session.query(PaymentMatch).filter_by(document_id=document.id).all():
        session.delete(match)
    document.sheet_state = "pending"
    document.sheet_row_ref = None
    document.sheet_snapshot = None
    session.flush()
    session.delete(document)
    session.flush()


def remove_unlisted(session: Session) -> int:
    """Entries a pull once kept after their row was deleted from the sheet go now."""
    kept = session.query(Document).filter(Document.sheet_state == "removed").all()
    if not kept:
        return 0
    with history.action("Files esborrades del full retirades"):
        for document in kept:
            _drop(session, document)
        session.commit()
    logger.info("Register: %d entries deleted from the sheet removed", len(kept))
    return len(kept)


def _clean_pull(entry: DiffEntry) -> bool:
    """A sheet edit nothing else contradicts, so it can come in on its own.

    A row typed into the sheet, or one edited there while the app left it
    alone since they last agreed. Conflicts and deleted rows wait for a person,
    as do entries from before versioning (no common ancestor to tell who moved)
    and rows carrying a code the database no longer has — the app wrote those,
    so their entry was taken out here (a restore, say), not typed in there.
    """
    if entry.status == "new_in_sheet":
        return not entry.reference and has_substance(entry._row.values)
    document = entry._document
    return (
        entry.status == "sheet_changed"
        and document is not None
        and document.sheet_snapshot is not None
        and document.status not in IN_FLIGHT
    )


def _is_empty(session: Session, document: Document) -> bool:
    """An entry with nothing in it: no invoice data, no file, no payment."""
    return (
        not has_substance(document_snapshot(document))
        and document.upload_id is None
        and not document.drive_file_id
        and document.status not in IN_FLIGHT
        and session.query(PaymentMatch).filter_by(document_id=document.id).first() is None
    )


def remove_empty(service, workspace, session: Session, rows: list[SheetRow], documents: list[Document]) -> int:
    """Take out entries that say nothing, and their codes from the sheet's rows.

    Blank rows of a sheet table once came in as entries; nothing was in them,
    so nothing is lost. One undoable action. Returns how many went.
    """
    empty = [d for d in documents if _is_empty(session, d)]
    if not empty:
        return 0
    references = {d.internal_doc_number for d in empty}
    with history.action("Entrades buides retirades"):
        for document in empty:
            session.delete(document)
        session.flush()
    # The row stays (it belongs to the table); only our code goes, so it is blank again.
    clears = [
        (row.row_number, {"num_doc_intern": ""})
        for row in rows
        if row.values.get("num_doc_intern") in references and not has_substance(row.values)
    ]
    if clears:
        service.write_cells(workspace, clears)
    session.commit()
    logger.info("Register: %d empty entries removed", len(empty))
    return len(empty)


def trust_database(session: Session) -> None:
    """After a restore the database is the truth: every entry the sheet disagrees
    with is sent there on the next sync, rather than pulled back from it."""
    session.query(Document).filter(Document.sheet_state != "removed").update(
        {Document.sheet_snapshot: None, Document.sheet_state: "pending"}, synchronize_session=False
    )
    session.commit()


def auto_sync(app, session: Session, *, force: bool = False) -> SyncResult:
    """Send app edits on, bring clean sheet edits in, count what is left. Throttled."""
    service: GoogleSheetsService = app.state.sheet_service
    workspace = get_workspace_setting(session)
    if not service.is_ready(workspace):
        with app.state.register_lock:
            remove_duplicates(app, session, sheet_ready=False)
        return SyncResult(refreshed=session.query(Document).count(), sheet_configured=False)
    total = session.query(Document).count()
    now = time.monotonic()
    if not force and now - app.state.register_synced_at < SYNC_INTERVAL_SECONDS:
        return app.state.sheet_status or SyncResult(refreshed=total)
    if not app.state.register_lock.acquire(blocking=force):
        return app.state.sheet_status or SyncResult(refreshed=total)
    try:
        app.state.register_synced_at = now
        remove_duplicates(app, session, sheet_ready=True)
        remove_unlisted(session)
        _, _, rows, documents = _read(app, session)
        if remove_empty(service, workspace, session, rows, documents):
            _, _, rows, documents = _read(app, session)
        _baseline_agreeing(rows, documents)
        entries = compute_diff(rows, documents)
        pushed = 0
        for entry in entries:
            if entry.status in AUTOMATIC and entry._document is not None:
                _write(service, workspace, entry._document, entry)
                pushed += 1
        session.commit()
        incoming = [e for e in entries if _clean_pull(e)]
        if incoming:
            # Undoable as one action, like a pull a person asked for.
            with history.action("Canvis del full integrats"):
                reference_writes: list[tuple[int, dict[str, Any]]] = []
                for entry in incoming:
                    _pull_entry(session, entry, reference_writes)
                if reference_writes:
                    service.write_cells(workspace, reference_writes)
                session.commit()
            logger.info("Register: %d sheet edits brought in", len(incoming))
        pulled_ids = {id(e) for e in incoming}
        waiting = [e for e in entries if e.status in PULLABLE and id(e) not in pulled_ids]
        counts = summarize(waiting)
        result = SyncResult(
            refreshed=len(rows),
            pushed=pushed,
            pulled=len(incoming),
            waiting=len(waiting),
            conflicts=counts.get("conflict", 0),
        )
        app.state.sheet_status = result
        return result
    except Exception as exc:  # noqa: BLE001
        # A Sheets outage degrades to the database's view rather than failing.
        logger.exception("Register sync with Google Sheets failed")
        session.rollback()
        return SyncResult(refreshed=total, error=f"No s'ha pogut llegir el full: {exc}")
    finally:
        app.state.register_lock.release()


def diff(app, session: Session) -> list[DiffEntry]:
    with app.state.register_lock:
        _, _, rows, documents = _read(app, session)
        _baseline_agreeing(rows, documents)
        session.commit()
        return compute_diff(rows, documents)


def _selected(entries: list[DiffEntry], allowed: set[str], references: list[str] | None) -> list[DiffEntry]:
    picked = [e for e in entries if e.status in allowed]
    if references is not None:
        wanted = set(references)
        # Rows typed into the sheet have no reference yet; they are picked by row.
        picked = [e for e in picked if e.reference in wanted or f"row:{e.row}" in wanted]
    return picked


def pull(app, session: Session, *, references: list[str] | None, author: str) -> dict[str, Any]:
    """Sheet → database, after a backup of the database as it was."""
    with app.state.register_lock:
        service, workspace, rows, documents = _read(app, session)
        _baseline_agreeing(rows, documents)
        chosen = _selected(compute_diff(rows, documents), PULLABLE, references)
        if not chosen:
            session.commit()
            return {"applied": 0, "backup": None}
        backup = app.state.backup_service.create(
            f"abans d'integrar {len(chosen)} canvis del full", kind="pre-pull", author=author,
            sheet_rows=[{"row": r.row_number, **snapshot_values(r.values),
                         "num_doc_intern": r.values.get("num_doc_intern")} for r in rows],
        )
        reference_writes: list[tuple[int, dict[str, Any]]] = []
        for entry in chosen:
            _pull_entry(session, entry, reference_writes)
        if reference_writes:
            service.write_cells(workspace, reference_writes)
        session.commit()
    app.state.register_synced_at = 0.0
    return {"applied": len(chosen), "backup": backup.name}


def push(app, session: Session, *, references: list[str] | None, author: str) -> dict[str, Any]:
    """Database → sheet, after a backup that also keeps the sheet's values."""
    with app.state.register_lock:
        service, workspace, rows, documents = _read(app, session)
        _baseline_agreeing(rows, documents)
        chosen = [
            e for e in _selected(compute_diff(rows, documents), PUSHABLE, references)
            if e._document is not None
        ]
        if not chosen:
            session.commit()
            return {"applied": 0, "backup": None}
        backup = app.state.backup_service.create(
            f"abans d'escriure {len(chosen)} documents al full", kind="pre-push", author=author,
            sheet_rows=[{"row": r.row_number, **snapshot_values(r.values),
                         "num_doc_intern": r.values.get("num_doc_intern")} for r in rows],
        )
        for entry in chosen:
            _write(service, workspace, entry._document, entry)
        session.commit()
    app.state.register_synced_at = 0.0
    return {"applied": len(chosen), "backup": backup.name}
