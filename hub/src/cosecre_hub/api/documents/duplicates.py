"""Entries that say exactly the same thing twice are taken out on their own.

The same invoice photographed twice, or typed into the sheet after it had been
uploaded, leaves two entries with identical values. Those are not a judgement
call, so they are removed automatically — the copy that stays is the one with
the most work behind it — and logged, for Configuració to show. Anything less
than identical is left for a person.

Only the entry goes: its original file stays on the server and on Drive, its
payment links move to the copy that stays, and a backup precedes every pass.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...deps import get_current_user, get_db, get_workspace_setting
from ...models import Document, DuplicateRemoval, PaymentMatch, User
from ...services.sheets import GoogleSheetsService, SheetDocumentNotFound
from .register import IN_FLIGHT, document_snapshot

logger = logging.getLogger(__name__)

#: Bookkeeping, not what the document says: two copies may differ here.
IGNORED = {"file_link", "origen", "validat"}
_SPACES = re.compile(r"\s+")
_STATUS_RANK = {"confirmed": 3, "proposed": 2, "alternative": 1, "rejected": 0}


def _key(document: Document) -> tuple[Any, ...] | None:
    """What the entry says, folded; ``None`` when it says too little to compare."""
    if document.status in IN_FLIGHT or document.status == "error" or document.sheet_state == "removed":
        return None
    values = document_snapshot(document)
    if not values.get("num_factura") or values.get("import_value") is None:
        return None
    if not (values.get("proveidor") or values.get("cif_proveidor")):
        return None
    return tuple(
        _SPACES.sub(" ", value).casefold() if isinstance(value, str) else value
        for name, value in sorted(values.items())
        if name not in IGNORED
    )


def _worth(document: Document) -> tuple[Any, ...]:
    """Higher is the copy to keep: paid, then validated, then with a file, then oldest."""
    upload = document.upload
    has_file = bool(document.drive_file_id) or (upload is not None and Path(upload.stored_path).exists())
    confirmed = any(m.status == "confirmed" for m in _matches(document))
    created = document.created_at.timestamp() if document.created_at else 0.0
    return (confirmed, document.validat, has_file, -created, -document.id)


def _matches(document: Document) -> list[PaymentMatch]:
    session = Session.object_session(document)
    return session.query(PaymentMatch).filter(PaymentMatch.document_id == document.id).all()


def find_duplicates(documents: list[Document]) -> list[tuple[Document, Document]]:
    """``(duplicate, kept)`` pairs, oldest-first within each group."""
    groups: dict[tuple[Any, ...], list[Document]] = {}
    for document in documents:
        key = _key(document)
        if key is not None:
            groups.setdefault(key, []).append(document)
    pairs: list[tuple[Document, Document]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        kept = max(group, key=_worth)
        pairs.extend((document, kept) for document in group if document is not kept)
    return pairs


def _move_matches(session: Session, duplicate: Document, kept: Document) -> None:
    """Payment links follow the entry that stays; the better of two links wins."""
    for match in _matches(duplicate):
        other = (
            session.query(PaymentMatch)
            .filter(PaymentMatch.movement_id == match.movement_id, PaymentMatch.document_id == kept.id)
            .first()
        )
        if other is not None:
            if _STATUS_RANK.get(match.status, 0) <= _STATUS_RANK.get(other.status, 0):
                session.delete(match)
                continue
            session.delete(other)
            session.flush()
        match.document_id = kept.id
    session.flush()


def remove_duplicates(app, session: Session, *, sheet_ready: bool) -> int:
    """Take out every exact duplicate. The caller holds the register lock.

    Returns how many entries went. An entry whose sheet row cannot be removed
    is left alone until the next pass, so the two never disagree.
    """
    pairs = find_duplicates(session.query(Document).all())
    if not pairs:
        return 0
    try:
        app.state.backup_service.create(
            f"abans de treure {len(pairs)} {'duplicat' if len(pairs) == 1 else 'duplicats'}",
            kind="pre-dedupe",
            author="Cosecre",
        )
    except Exception:  # noqa: BLE001
        logger.exception("No backup before removing duplicates; leaving them for now")
        return 0

    service: GoogleSheetsService = app.state.sheet_service
    workspace = get_workspace_setting(session) if sheet_ready else None
    removed = 0
    for duplicate, kept in pairs:
        reference = duplicate.internal_doc_number
        if workspace is not None and duplicate.sheet_state != "removed":
            try:
                service.delete_row(workspace, service.find_row(workspace, reference))
            except SheetDocumentNotFound:
                pass
            except Exception:  # noqa: BLE001
                logger.warning("Could not remove the sheet row of duplicate %s", reference, exc_info=True)
                continue
        upload = duplicate.upload
        session.add(DuplicateRemoval(
            reference=reference,
            kept_reference=kept.internal_doc_number,
            values=document_snapshot(duplicate),
            source_file_name=upload.source_file_name if upload else None,
            stored_path=upload.stored_path if upload else None,
            drive_file_id=duplicate.drive_file_id,
            entry_created_at=duplicate.created_at,
        ))
        _move_matches(session, duplicate, kept)
        # The upload (and its file) stays: only the register entry goes.
        session.delete(duplicate)
        session.commit()
        removed += 1
        logger.info("Removed %s, an exact duplicate of %s", reference, kept.internal_doc_number)
    return removed


# ── What Configuració shows ──────────────────────────────────────────────────

router = APIRouter()


class DuplicateRemovalRead(BaseModel):
    reference: str
    kept_reference: str
    kept_exists: bool
    num_factura: str
    proveidor: str
    data_factura: str
    import_value: float | None
    source_file_name: str | None
    removed_at: Any


@router.get("", response_model=list[DuplicateRemovalRead])
def list_removed(session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = session.query(DuplicateRemoval).order_by(DuplicateRemoval.removed_at.desc()).limit(500).all()
    existing = {
        reference
        for (reference,) in session.query(Document.internal_doc_number)
        .filter(Document.internal_doc_number.in_({r.kept_reference for r in rows}))
        .all()
    }
    return [
        DuplicateRemovalRead(
            reference=row.reference,
            kept_reference=row.kept_reference,
            kept_exists=row.kept_reference in existing,
            num_factura=str(row.values.get("num_factura") or ""),
            proveidor=str(row.values.get("proveidor") or ""),
            data_factura=str(row.values.get("data_factura") or ""),
            import_value=row.values.get("import_value"),
            source_file_name=row.source_file_name,
            removed_at=row.removed_at,
        )
        for row in rows
    ]
