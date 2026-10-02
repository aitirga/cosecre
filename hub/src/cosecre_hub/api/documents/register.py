"""The register's own logic, between the HTTP routes and Google.

The database is written first, always; the sheet is brought in line after. When
Google is down nothing is lost — the entry is marked ``pending`` and the next
sync pushes it. Edits made in the sheet travel the other way only when someone
integrates them (see :mod:`.sync`).
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ...deps import get_workspace_setting
from ...models import Document, ExtractionJob, Upload
from ...schemas import AiHint, DocumentRecord, SyncResult
from ...services.extraction import DocumentExtractionService, ExtractedDocument
from ...services.sheets import (
    REGISTER_COLUMNS,
    GoogleSheetsService,
    drive_file_id_from_link,
    file_cell,
    snapshot_values,
)
from ...services.text_format import iban_is_valid

logger = logging.getLogger(__name__)

IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
IN_FLIGHT = {"pending", "processing", "written_to_sheet"}

REGISTER_FIELDS = tuple(column.field for column in REGISTER_COLUMNS)
#: Fields a sheet edit may change. The reference is the row's identity.
SHEET_EDITABLE = tuple(name for name in REGISTER_FIELDS if name != "num_doc_intern")


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_reference() -> str:
    return f"DOC-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


# ── Conversions ──────────────────────────────────────────────────────────────


def sheet_values(document: Document) -> dict[str, Any]:
    values = {name: getattr(document, name, "") for name in REGISTER_FIELDS if name != "num_doc_intern"}
    values["num_doc_intern"] = document.internal_doc_number
    return values


def apply_values(document: Document, values: dict[str, Any]) -> list[str]:
    """Copy register values onto an entry; returns the fields that changed."""
    changed: list[str] = []
    for name in SHEET_EDITABLE:
        if name not in values:
            continue
        new = values[name]
        if name == "validat":
            new = bool(new)
        elif new is None and name not in {"data_factura", "data_pagament", "import_value"}:
            new = ""
        if getattr(document, name) != new:
            setattr(document, name, new)
            changed.append(name)
    if "file_link" in changed and not document.drive_file_id:
        document.drive_file_id = drive_file_id_from_link(document.file_link)
    return changed


def status_after_review(document: Document) -> str:
    return "validated" if document.validat else "needs_validation"


def to_record(document: Document) -> DocumentRecord:
    upload = document.upload
    file_url = None
    if upload is not None and Path(upload.stored_path).exists():
        file_url = f"/documents/records/{document.internal_doc_number}/file"
    return DocumentRecord(
        num_doc_intern=document.internal_doc_number,
        **{name: getattr(document, name) for name in REGISTER_FIELDS if name != "num_doc_intern"},
        transcripcio=document.transcripcio or "",
        file_url=file_url,
        drive_url=(
            f"https://drive.google.com/file/d/{document.drive_file_id}/view"
            if document.drive_file_id
            else None
        ),
        source_file_name=upload.source_file_name if upload else None,
        source_file_type=upload.source_file_type if upload else None,
        extraction_status=document.status,  # type: ignore[arg-type]
        sheet_state=document.sheet_state,  # type: ignore[arg-type]
        sheet_row_ref=document.sheet_row_ref,
        legacy_type=document.legacy_type,
        ai_hints={name: AiHint.model_validate(hint) for name, hint in (document.ai_hints or {}).items()},
        ai_trace=document.ai_trace,
        iban_valid=iban_is_valid(document.compte_corrent) if document.compte_corrent else None,
        created_at=document.created_at,
        updated_at=document.updated_at,
        error_message=document.error_message,
    )


def confirm_hints(document: Document, fields: list[str] | None = None) -> None:
    """A person has looked at these fields (or at all of them, on validation)."""
    hints = dict(document.ai_hints or {})
    for name, hint in hints.items():
        if fields is None or name in fields:
            hints[name] = {**hint, "review": False}
    document.ai_hints = hints


def apply_extraction(document: Document, extracted: ExtractedDocument, *, only_empty: bool) -> list[str]:
    """Merge a model reading into an entry.

    ``only_empty`` is for entries a person already worked on (migrated rows):
    the models may fill gaps, never overwrite.
    """
    filled: list[str] = []
    for name, value in extracted.fields.items():
        if value in ("", None):
            continue
        current = getattr(document, name)
        if only_empty and current not in ("", None):
            continue
        if current != value:
            setattr(document, name, value)
            filled.append(name)
    document.transcripcio = extracted.transcription
    document.ai_trace = {**extracted.trace, "only_empty": only_empty, "filled": filled}
    hints = dict(document.ai_hints or {})
    for name, hint in extracted.hints.items():
        if not only_empty or name in filled:
            hints[name] = hint.model_dump(exclude_none=True)
    document.ai_hints = hints
    return filled


# ── Drive ────────────────────────────────────────────────────────────────────

_UNSAFE = re.compile(r'[\\/:*?"<>|\s]+')


def drive_name(document: Document, extension: str) -> str:
    """``<yyyy-mm-dd>_<número>`` — sorts by date in any file listing."""
    when = document.data_factura.strftime("%Y-%m-%d") if document.data_factura else "sense-data"
    number = _UNSAFE.sub("-", document.num_factura.strip()).strip("-.") or document.internal_doc_number
    return f"{when}_{number[:80]}{extension}"


def extension_for(document: Document) -> str:
    upload = document.upload
    if upload is not None:
        suffix = Path(upload.stored_path).suffix.lower()
        if suffix:
            return suffix
    if document.drive_file_name and "." in document.drive_file_name:
        return "." + document.drive_file_name.rsplit(".", 1)[1]
    return ""


def unique_drive_name(
    service: GoogleSheetsService,
    folder_id: str | None,
    document: Document,
    *,
    mime_type: str | None = None,
) -> str:
    extension = extension_for(document)
    if not extension and mime_type:
        extension = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}.get(mime_type, "")
    name = drive_name(document, extension)
    if service.drive_name_taken(folder_id, name, except_id=document.drive_file_id):
        stem, dot, ext = name.rpartition(".")
        suffix = document.internal_doc_number[-8:]
        name = f"{stem}_{suffix}.{ext}" if dot else f"{name}_{suffix}"
    return name


def rename_on_drive(app, document: Document) -> None:
    """Keep the Drive name in step with the date and number. Best-effort."""
    service: GoogleSheetsService = app.state.sheet_service
    if not document.drive_file_id or not service.drive_ready:
        return
    folder_id = app.state.settings.documents_folder_id
    if document.drive_file_name == drive_name(document, extension_for(document)):
        return
    try:
        with app.state.drive_lock:
            name = unique_drive_name(service, folder_id, document)
            if name != document.drive_file_name:
                service.update_drive_file(document.drive_file_id, name=name)
                document.drive_file_name = name
    except Exception:  # noqa: BLE001
        logger.warning("Could not rename Drive file for %s", document.internal_doc_number, exc_info=True)


# ── Sheet sync ───────────────────────────────────────────────────────────────


def document_snapshot(document: Document) -> dict[str, Any]:
    return snapshot_values(sheet_values(document))


def push_document(app, session: Session, document: Document) -> str | None:
    """Write one entry to its row (or a new one). Returns an error, or ``None``.

    Rows are found by reference every time, so a person sorting or inserting
    rows in the sheet never makes this overwrite the wrong one. A row edited in
    the sheet since it was last in step is never overwritten here: those edits
    wait for someone to integrate (or discard) them deliberately.
    """
    service: GoogleSheetsService = app.state.sheet_service
    workspace = get_workspace_setting(session)
    if not service.is_ready(workspace):
        document.sheet_state = "pending"
        return None
    with app.state.register_lock:
        try:
            row = next(
                (r for r in service.read_register(workspace)
                 if r.values.get("num_doc_intern") == document.internal_doc_number),
                None,
            )
            if row is not None and document.sheet_snapshot is not None:
                if snapshot_values(row.values) != document.sheet_snapshot:
                    document.sheet_state = "pending"
                    return (
                        "Aquest document també s'ha editat al full de càlcul i aquells canvis "
                        "encara no s'han integrat. Revisa'ls a «Sincronització» abans d'enviar-hi els teus."
                    )
            if row is not None:
                row_number = service.write_row(workspace, row.row_number, sheet_values(document))
            else:
                row_number = service.append_row(workspace, sheet_values(document))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not write %s to Google Sheets", document.internal_doc_number)
            document.sheet_state = "pending"
            return f"No s'ha pogut escriure al full de càlcul: {exc}"
    document.sheet_state = "synced"
    document.sheet_row_ref = row_number
    document.sheet_snapshot = document_snapshot(document)
    return None


def sync_register(app, session: Session, *, force: bool = False) -> SyncResult:
    """The automatic, safe half of syncing; see :func:`.sync.auto_sync`."""
    from .sync import auto_sync

    return auto_sync(app, session, force=force)


# ── Extraction pipeline ──────────────────────────────────────────────────────


def process_job(app, job_id: str) -> None:
    """Extract, file on Drive, then write to the database and the sheet.

    Runs as a background task, so nothing here may raise: every failure is
    recorded on the job and the entry for the client to poll.
    """
    session_factory = app.state.session_factory
    settings = app.state.settings
    extraction = DocumentExtractionService(app.state.llm_registry, app.state.classifier)
    sheet_service: GoogleSheetsService = app.state.sheet_service
    session = session_factory()
    try:
        job = session.get(ExtractionJob, job_id)
        if job is None:
            return
        upload = job.upload
        document = session.query(Document).filter(Document.upload_id == upload.id).first()
        if document is None:
            document = Document(
                internal_doc_number=upload.internal_doc_number,
                upload_id=upload.id,
                created_by_id=upload.user_id,
            )
            session.add(document)
        workspace = get_workspace_setting(session)
        job.status = upload.status = document.status = "processing"
        session.commit()

        extracted = extraction.extract(
            Path(upload.stored_path),
            upload.source_file_type,
            model=workspace.openai_model or settings.openai_model,
            prompt_override=workspace.extraction_prompt,
        )
        apply_extraction(document, extracted, only_empty=False)
        document.origen = "Foto" if upload.capture_source == "camera" else "Original"
        job.extracted_payload = {
            **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in extracted.fields.items()},
            "transcripcio": extracted.transcription,
        }
        job.status = document.status = "written_to_sheet"
        session.commit()

        if sheet_service.drive_ready:
            try:
                folder_id = settings.documents_folder_id
                with app.state.drive_lock:
                    name = unique_drive_name(sheet_service, folder_id, document)
                    _, drive_file_id = sheet_service.upload_file_to_drive(
                        Path(upload.stored_path), name, upload.source_file_type, folder_id=folder_id
                    )
                upload.drive_file_id = document.drive_file_id = drive_file_id
                document.drive_file_name = name
                document.file_link = file_cell(drive_file_id, upload.source_file_type)
            except Exception:  # noqa: BLE001
                # The extraction is the valuable part; a missing Drive copy only
                # costs the sheet its thumbnail.
                logger.warning("Drive upload failed for %s", upload.internal_doc_number, exc_info=True)

        document.status = "needs_validation"
        document.error_message = None
        document.sheet_state = "pending"
        sheet_error = push_document(app, session, document)
        job.sheet_row_ref = document.sheet_row_ref
        job.status = "needs_validation"
        job.error_message = sheet_error
        upload.status = "written_to_sheet" if document.sheet_state == "synced" else "extracted"
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("Extraction job %s failed", job_id, exc_info=True)
        failed_job = session.get(ExtractionJob, job_id)
        if failed_job is not None:
            failed_job.status = "error"
            failed_job.error_message = str(exc)
            failed_job.upload.status = "error"
            failed_document = (
                session.query(Document).filter(Document.upload_id == failed_job.upload_id).first()
            )
            if failed_document is not None:
                failed_document.status = "error"
                failed_document.error_message = str(exc)
            session.commit()
    finally:
        session.close()
