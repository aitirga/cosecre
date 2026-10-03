"""The accounting register — one list for every kind of document.

Invoices and tickets used to be two routers writing to two tabs. The models now
tell the kinds apart (``tipus_document``), so there is one register, one tab
and one Drive folder.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
import zipfile
from datetime import date
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from ...deps import get_current_user, get_db, get_settings, get_workspace_setting
from ...models import Document, ExtractionJob, Upload, User
from ...schemas import DocumentRecord, DocumentUpdate, JobRead, SyncResult, UploadResponse
from ...schemas.documents import DiffEntryRead, FieldChangeRead, SyncApplied, SyncApply, SyncDiff
from ...schemas.documents import CaptureSource
from ...services.sheets import GoogleSheetsService, SheetDocumentNotFound
from ...services.storage import save_upload_file
from .register import (
    confirm_hints,
    drive_name,
    extension_for,
    generate_reference,
    process_job,
    push_document,
    rename_on_drive,
    status_after_review,
    sync_register,
    to_record,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _document(session: Session, reference: str) -> Document:
    document = (
        session.query(Document).filter(Document.internal_doc_number == reference).first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat el document.")
    return document


def _sort_key(document: Document):
    when = document.data_factura or (document.created_at.date() if document.created_at else None)
    return (when.toordinal() if when else 0, document.created_at.timestamp() if document.created_at else 0)


async def process_job_in_background(app, job_id: str) -> None:
    # Wait outside the thread pool: queued uploads must not starve health,
    # authentication or job polling while a large document is being extracted.
    async with app.state.extraction_limiter:
        await run_in_threadpool(process_job, app, job_id)


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source: CaptureSource = Form("file"),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings=Depends(get_settings),
):
    """Queue one file. Several can be in flight at once; they are read in order."""
    reference = generate_reference()
    stored_path = await save_upload_file(file, reference, settings)

    upload = Upload(
        user_id=user.id,
        internal_doc_number=reference,
        document_type="document",
        source_file_name=file.filename or stored_path.name,
        source_file_type=file.content_type or "application/octet-stream",
        stored_path=str(stored_path),
        capture_source=source,
        status="pending",
    )
    job = ExtractionJob(id=str(uuid.uuid4()), user_id=user.id, upload=upload, status="pending")
    document = Document(
        internal_doc_number=reference,
        upload=upload,
        created_by_id=user.id,
        origen="Foto" if source == "camera" else "Original",
        status="pending",
        sheet_state="pending",
    )
    session.add_all([upload, job, document])
    session.commit()
    background_tasks.add_task(process_job_in_background, request.app, job.id)
    return UploadResponse(job_id=job.id, internal_doc_number=reference, status="pending")


@router.post("/sync", response_model=SyncResult)
def sync_documents(
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Pull the sheet now, rather than waiting for the next list to do it."""
    return sync_register(request.app, session, force=True)


@router.get("/sync/diff", response_model=SyncDiff)
def sync_diff(
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Every difference between the sheet and the database, and who made it."""
    from . import sync

    workspace = get_workspace_setting(session)
    if not request.app.state.sheet_service.is_ready(workspace):
        return SyncDiff(sheet_configured=False)
    try:
        entries = sync.diff(request.app, session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not compare the sheet with the database")
        raise HTTPException(status_code=502, detail=f"No s'ha pogut llegir el full: {exc}") from exc
    return SyncDiff(
        entries=[
            DiffEntryRead(
                reference=e.reference, status=e.status, row=e.row,
                num_factura=e.num_factura, proveidor=e.proveidor,
                changes=[FieldChangeRead(**vars(c)) for c in e.changes],
            )
            for e in entries
        ],
        counts=sync.summarize(entries),
    )


def _apply(request: Request, session: Session, user: User, payload: SyncApply, direction: str):
    from . import sync

    workspace = get_workspace_setting(session)
    if not request.app.state.sheet_service.is_ready(workspace):
        raise HTTPException(status_code=400, detail="No hi ha cap full de càlcul configurat.")
    action = sync.pull if direction == "pull" else sync.push
    try:
        return SyncApplied(**action(request.app, session, references=payload.references, author=user.email))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.exception("Sync %s failed", direction)
        raise HTTPException(status_code=502, detail=f"No s'ha pogut completar: {exc}") from exc


@router.post("/sync/pull", response_model=SyncApplied)
def sync_pull(
    request: Request,
    payload: SyncApply,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Integrate the sheet's changes into the database. Takes a backup first."""
    return _apply(request, session, user, payload, "pull")


@router.post("/sync/push", response_model=SyncApplied)
def sync_push(
    request: Request,
    payload: SyncApply,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Write the database's version over the sheet's. Takes a backup first."""
    return _apply(request, session, user, payload, "push")


@router.get("", response_model=list[DocumentRecord])
def list_documents(
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    sync_register(request.app, session)
    documents = session.query(Document).all()
    return [to_record(d) for d in sorted(documents, key=_sort_key, reverse=True)]


@router.get("/files.zip")
def download_all_files(
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Every original kept on the server, in one zip named like the Drive folder.

    Built in a temporary file rather than in memory: the machine has 1 GB and
    the photos together can be several times that. Photos are already
    compressed, so they are stored as they are.
    """
    documents = [d for d in session.query(Document).all() if d.upload is not None]
    handle, temp_path = tempfile.mkstemp(prefix="cosecre-originals-", suffix=".zip")
    os.close(handle)
    taken: set[str] = set()
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for document in sorted(documents, key=_sort_key):
                source = Path(document.upload.stored_path)
                if not source.exists():
                    continue
                name = drive_name(document, extension_for(document))
                if name in taken:
                    stem, dot, ext = name.rpartition(".")
                    suffix = document.internal_doc_number[-8:]
                    name = f"{stem}_{suffix}.{ext}" if dot else f"{name}_{suffix}"
                taken.add(name)
                archive.write(source, arcname=name)
    except Exception:
        os.unlink(temp_path)
        raise
    if not taken:
        os.unlink(temp_path)
        raise HTTPException(status_code=404, detail="No hi ha cap original al servidor.")
    return FileResponse(
        path=temp_path,
        media_type="application/zip",
        filename=f"cosecre-originals-{date.today():%Y-%m-%d}.zip",
        background=BackgroundTask(os.unlink, temp_path),
    )


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    job = session.get(ExtractionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat la tasca.")
    return JobRead(
        id=job.id,
        internal_doc_number=job.upload.internal_doc_number,
        status=job.status,
        error_message=job.error_message,
        sheet_row_ref=job.sheet_row_ref,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/{reference}", response_model=DocumentRecord)
def get_document(
    reference: str,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    sync_register(request.app, session)
    return to_record(_document(session, reference))


def _save(app, session: Session, document: Document, changes: dict) -> DocumentRecord:
    if document.status in {"pending", "processing", "written_to_sheet"}:
        raise HTTPException(
            status_code=409,
            detail="El document encara s'està processant. Espera que acabi abans d'editar-lo.",
        )
    changed = [name for name, value in changes.items() if getattr(document, name) != value]
    for name, value in changes.items():
        setattr(document, name, "" if value is None and isinstance(getattr(document, name), str) else value)
    if document.validat:
        confirm_hints(document)
    else:
        confirm_hints(document, changed)
    # A person saving an entry has the document in hand — even one the models
    # could not read becomes an ordinary entry to review.
    document.status = status_after_review(document)
    document.error_message = None
    # Database first: from here on the edit survives whatever Google does.
    document.sheet_state = "pending"
    session.commit()

    if {"data_factura", "num_factura"} & set(changed):
        rename_on_drive(app, document)
    error = push_document(app, session, document)
    session.commit()
    record = to_record(document)
    if error:
        record.error_message = error
    return record


@router.patch("/{reference}", response_model=DocumentRecord)
def update_document(
    reference: str,
    payload: DocumentUpdate,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    return _save(request.app, session, _document(session, reference), changes)


@router.post("/{reference}/validate", response_model=DocumentRecord)
def validate_document(
    reference: str,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return _save(request.app, session, _document(session, reference), {"validat": True})


@router.get("/{reference}/file")
def get_document_file(
    reference: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    document = _document(session, reference)
    upload = document.upload
    if upload is None:
        raise HTTPException(status_code=404, detail="Aquest document no té cap fitxer local.")
    file_path = Path(upload.stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="El fitxer ja no és al servidor.")
    return FileResponse(
        path=file_path,
        media_type=upload.source_file_type,
        filename=drive_name(document, extension_for(document)),
    )


@router.delete("/{reference}", status_code=204, response_model=None)
def delete_document(
    reference: str,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    app = request.app
    document = _document(session, reference)
    workspace = get_workspace_setting(session)
    service: GoogleSheetsService = app.state.sheet_service
    if service.is_ready(workspace) and document.sheet_state != "removed":
        with app.state.register_lock:
            try:
                service.delete_row(workspace, service.find_row(workspace, reference))
            except SheetDocumentNotFound:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.exception("Could not delete %s from Google Sheets", reference)
                raise HTTPException(
                    status_code=502,
                    detail="No s'ha pogut esborrar la fila del full. Torna-ho a provar.",
                ) from exc

    if document.drive_file_id and service.drive_ready:
        try:
            service.delete_drive_file(document.drive_file_id)
        except Exception:  # noqa: BLE001
            logger.warning("Could not remove Drive file for %s", reference, exc_info=True)

    upload = document.upload
    session.delete(document)
    if upload is not None:
        if upload.job is not None:
            session.delete(upload.job)
        session.flush()
        session.delete(upload)
    session.commit()
