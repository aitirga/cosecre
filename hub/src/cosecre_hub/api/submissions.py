"""Invoices and tickets a teacher sends in — open to every role.

Each upload becomes an ordinary register entry, read by the same models. What
this router adds is the teacher's side of it: sending one, optionally for one
of their requests, filling it in and validating it themselves — their own, and
nobody else's. Once validated it is the office's to change.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, get_settings, get_workspace_setting
from ..models import Document, ExtractionJob, Request as OfficeRequest, User
from ..schemas import DocumentRecord, DocumentUpdate, JobRead, UploadResponse
from ..schemas.common import UtcDatetime
from ..schemas.documents import RESPONSABLE_EMAIL, CaptureSource, ExtractionStatus
from .documents.register import drive_name, extension_for, sync_register, to_record
from .documents.routes import _save, queue_upload
from ..services.text_format import compact_code
from .requests import is_office

router = APIRouter()

_NOT_FOUND = "No s'ha trobat el document."


class SubmissionRead(BaseModel):
    num_doc_intern: str
    tipus_document: str
    num_factura: str
    proveidor: str
    data_factura: date | None = None
    import_value: float | None = None
    status: ExtractionStatus
    validat: bool
    request_id: int | None = None
    request_code: str | None = None
    has_file: bool
    file_name: str | None = None
    source_file_type: str | None = None
    created_at: UtcDatetime | None = None
    updated_at: datetime | None = None


def _own(session: Session, reference: str, user: User) -> Document:
    document = session.query(Document).filter(Document.internal_doc_number == reference).first()
    if document is None or document.created_by_id != user.id:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return document


def _read(document: Document) -> SubmissionRead:
    upload = document.upload
    stored = Path(upload.stored_path) if upload is not None else None
    has_file = stored is not None and stored.exists()
    return SubmissionRead(
        num_doc_intern=document.internal_doc_number,
        tipus_document=document.tipus_document,
        num_factura=document.num_factura,
        proveidor=document.proveidor,
        data_factura=document.data_factura,
        import_value=document.import_value,
        status=document.status,
        validat=document.validat,
        request_id=document.request_id,
        request_code=f"SOL-{document.request_id:04d}" if document.request_id else None,
        has_file=has_file,
        file_name=drive_name(document, extension_for(document)) if has_file else None,
        source_file_type=upload.source_file_type if upload else None,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.post("/upload", response_model=UploadResponse)
async def submit(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source: CaptureSource = Form("file"),
    request_id: int | None = Form(None),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings=Depends(get_settings),
):
    """Send one invoice or ticket in, optionally for one of your requests."""
    if request_id is not None:
        office_request = session.get(OfficeRequest, request_id)
        if office_request is None or not (is_office(user) or office_request.requester_id == user.id):
            raise HTTPException(status_code=404, detail="Aquesta sol·licitud no existeix.")
        if office_request.status == "cancellada":
            raise HTTPException(status_code=409, detail="Aquesta sol·licitud està cancel·lada.")
    # Whoever sends it in is who answers for it, until they say otherwise. The
    # register only takes @xtec.cat addresses, so any other is left for them.
    email = user.email.lower()
    responsable = (user.display_name or "", email if RESPONSABLE_EMAIL.fullmatch(email) else "")
    return await queue_upload(
        request,
        background_tasks,
        session,
        user,
        settings,
        file,
        source,
        request_id=request_id,
        responsable=responsable,
    )


@router.get("", response_model=list[SubmissionRead])
def my_submissions(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    documents = (
        session.query(Document)
        .filter(Document.created_by_id == user.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [_read(document) for document in documents]


@router.get("/jobs/{job_id}", response_model=JobRead)
def my_job(job_id: str, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = session.get(ExtractionJob, job_id)
    if job is None or job.user_id != user.id:
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


@router.get("/{reference}/file")
def my_file(reference: str, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = _own(session, reference, user)
    upload = document.upload
    file_path = Path(upload.stored_path) if upload is not None else None
    if file_path is None or not file_path.exists():
        raise HTTPException(status_code=404, detail="El fitxer ja no és al servidor.")
    return FileResponse(
        path=file_path,
        media_type=upload.source_file_type,
        filename=drive_name(document, extension_for(document)),
    )


class CentreRead(BaseModel):
    """What a teacher needs of the centre: the tax id their invoices must name."""

    cif: str


@router.get("/centre", response_model=CentreRead)
def centre(session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return CentreRead(cif=get_workspace_setting(session).school_cif or "")


@router.get("/{reference}/record", response_model=DocumentRecord)
def my_record(
    reference: str,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The whole entry, as the register's editor shows it."""
    sync_register(request.app, session)
    return to_record(_own(session, reference, user))


@router.patch("/{reference}", response_model=DocumentRecord)
def update_mine(
    reference: str,
    payload: DocumentUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fill in or correct one of your own, and validate it — no office review needed."""
    document = _own(session, reference, user)
    if document.validat:
        raise HTTPException(
            status_code=409,
            detail="Aquest document ja està validat. Per canviar-lo, parla amb secretaria.",
        )
    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    if changes.get("validat"):
        # What the purchase was for is the one thing only the teacher knows.
        if not (changes.get("descripcio_compra", document.descripcio_compra) or "").strip():
            raise HTTPException(
                status_code=409,
                detail="Escriu la descripció de la compra/servei abans d'enviar-la.",
            )
        # Only an invoice made out to the centre is the centre's to pay. With no
        # CIF configured there is nothing to check against.
        school_cif = compact_code(get_workspace_setting(session).school_cif)
        cif = compact_code(changes.get("cif_proveit", document.cif_proveit) or "")
        if school_cif and cif != school_cif:
            raise HTTPException(
                status_code=409,
                detail=f"El CIF proveït ha de ser el del centre ({school_cif}). Si la factura no és a nom del centre, no es pot enviar.",
            )
    return _save(request.app, session, document, changes, user)
