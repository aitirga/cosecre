from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..dependencies import get_current_user, get_db, get_settings, get_workspace_setting
from ..models import ExtractionJob, Upload, User
from ..schemas import (
    InvoiceExtraction,
    InvoiceRecord,
    InvoiceUpdate,
    JobRead,
    MessageResponse,
    RefreshResult,
    UploadResponse,
)
from ..services.openai_service import OpenAIExtractionService
from ..services.sheets_service import GoogleSheetsService
from ..services.storage import save_upload_file

router = APIRouter()


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_internal_doc_number() -> str:
    return f"DOC-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"



def invoice_sort_value(invoice: InvoiceRecord) -> float:
    reference = invoice.updated_at or invoice.created_at
    if reference is None:
        return 0
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference.timestamp()


_IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}


def merge_sheet_and_jobs(session: Session, sheet_records: list[InvoiceRecord]) -> list[InvoiceRecord]:
    # Google Sheets is the single source of truth for invoice data.
    # Only inject local jobs for in-flight items not yet written to the sheet.
    merged = {record.num_doc_intern: record for record in sheet_records}

    # Build upload lookup so we can attach file_url and source_file_type
    uploads_by_doc: dict[str, Upload] = {
        u.internal_doc_number: u
        for u in session.query(Upload).all()
    }

    jobs = session.query(ExtractionJob).join(Upload).all()
    for job in jobs:
        internal_doc_number = job.upload.internal_doc_number
        if internal_doc_number in merged:
            # Sheet record exists — enrich it with local file_url if available
            upload = uploads_by_doc.get(internal_doc_number)
            if upload and upload.source_file_type in _IMAGE_MIME_TYPES:
                existing = merged[internal_doc_number]
                merged[internal_doc_number] = existing.model_copy(
                    update={
                        "file_url": f"/invoices/{internal_doc_number}/file",
                        "source_file_type": upload.source_file_type,
                    }
                )
            continue
        if job.status not in {"pending", "processing", "written_to_sheet", "error"}:
            continue  # terminal and not in sheet means it was deleted from the sheet
        extracted_payload = job.extracted_payload or {}
        file_url = (
            f"/invoices/{internal_doc_number}/file"
            if job.upload.source_file_type in _IMAGE_MIME_TYPES
            else None
        )
        merged[internal_doc_number] = InvoiceRecord(
            num_doc_intern=internal_doc_number,
            source_file_name=job.upload.source_file_name,
            source_file_type=job.upload.source_file_type,
            file_url=file_url,
            extraction_status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            error_message=job.error_message,
            **{
                "num_factura": extracted_payload.get("num_factura", ""),
                "data_factura": extracted_payload.get("data_factura", ""),
                "proveidor": extracted_payload.get("proveidor", ""),
                "cif_proveidor": extracted_payload.get("cif_proveidor", ""),
                "adreca_proveidor": extracted_payload.get("adreca_proveidor", ""),
                "import": extracted_payload.get("import", ""),
                "cif_proveit": extracted_payload.get("cif_proveit", ""),
                "descripcio": extracted_payload.get("descripcio", ""),
                "pressupost_afectat": extracted_payload.get("pressupost_afectat", ""),
            },
        )
    return sorted(
        merged.values(),
        key=invoice_sort_value,
        reverse=True,
    )


def sync_sheet_records(session: Session, app) -> list[InvoiceRecord]:
    workspace = get_workspace_setting(session)
    sheet_service = GoogleSheetsService(app.state.settings)
    if not sheet_service.is_ready(workspace):
        return []
    return sheet_service.list_invoices(workspace)


def process_job(app, job_id: str) -> None:
    session_factory = app.state.session_factory
    settings = app.state.settings
    openai_service = OpenAIExtractionService(settings)
    sheet_service = GoogleSheetsService(settings)
    session = session_factory()
    try:
        job = session.get(ExtractionJob, job_id)
        if job is None:
            return
        upload = job.upload
        workspace = get_workspace_setting(session)
        job.status = "processing"
        upload.status = "processing"
        session.commit()

        extracted = openai_service.extract_invoice(
            Path(upload.stored_path),
            upload.source_file_type,
            workspace.openai_model or settings.openai_model,
            workspace.extraction_prompt,
        )
        job.extracted_payload = extracted.model_dump(by_alias=True)
        job.status = "written_to_sheet"
        session.commit()

        drive_link = ""
        drive_file_id = ""
        try:
            drive_link, drive_file_id = sheet_service.upload_file_to_drive(
                Path(upload.stored_path),
                upload.source_file_name,
                upload.source_file_type,
            )
        except Exception:  # noqa: BLE001
            pass  # Drive upload is best-effort; proceed without a link

        is_image = upload.source_file_type in {"image/jpeg", "image/jpg", "image/png"}
        if is_image and drive_file_id:
            file_cell = f'=IMAGE("https://drive.google.com/uc?export=view&id={drive_file_id}")'
        else:
            file_cell = drive_link

        invoice_for_sheet = InvoiceRecord(
            **extracted.model_dump(by_alias=False),
            file_link=file_cell,
            source_file_type=upload.source_file_type,
        )
        write_result = sheet_service.append_invoice(workspace, invoice_for_sheet)
        job.sheet_row_ref = write_result.row_number
        job.status = "needs_validation"
        job.error_message = None
        upload.status = "written_to_sheet"
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        failed_job = session.get(ExtractionJob, job_id)
        if failed_job is not None:
            failed_job.status = "error"
            failed_job.error_message = str(exc)
            failed_job.upload.status = "error"
            session.commit()
    finally:
        session.close()


@router.post("/upload", response_model=UploadResponse)
async def upload_invoice(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings=Depends(get_settings),
):
    internal_doc_number = generate_internal_doc_number()
    stored_path = await save_upload_file(file, internal_doc_number, settings)

    upload = Upload(
        user_id=user.id,
        internal_doc_number=internal_doc_number,
        source_file_name=file.filename or stored_path.name,
        source_file_type=file.content_type or "application/octet-stream",
        stored_path=str(stored_path),
        status="pending",
    )
    job = ExtractionJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        upload=upload,
        status="pending",
    )
    session.add_all([upload, job])
    session.commit()
    background_tasks.add_task(process_job, request.app, job.id)
    return UploadResponse(job_id=job.id, internal_doc_number=internal_doc_number, status="pending")


@router.get("/refresh", response_model=RefreshResult)
def refresh_invoices(request: Request, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    records = sync_sheet_records(session, request.app)
    return RefreshResult(refreshed=len(records))


@router.get("", response_model=list[InvoiceRecord])
def list_invoices(request: Request, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    records = sync_sheet_records(session, request.app)
    return merge_sheet_and_jobs(session, records)


@router.get("/{internal_doc_number}", response_model=InvoiceRecord)
def get_invoice(
    internal_doc_number: str,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    records = merge_sheet_and_jobs(session, sync_sheet_records(session, request.app))
    for record in records:
        if record.num_doc_intern == internal_doc_number:
            return record
    raise HTTPException(status_code=404, detail="Invoice not found")


@router.patch("/{internal_doc_number}", response_model=InvoiceRecord)
def update_invoice(
    internal_doc_number: str,
    payload: InvoiceUpdate,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    workspace = get_workspace_setting(session)
    sheet_service = GoogleSheetsService(request.app.state.settings)
    if not sheet_service.is_ready(workspace):
        raise HTTPException(status_code=400, detail="Google Sheets is not configured")
    records = {record.num_doc_intern: record for record in sync_sheet_records(session, request.app)}
    record = records.get(internal_doc_number)
    if record is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    updated_record = record.model_copy(update=payload.model_dump(exclude_none=True, by_alias=False))
    result = sheet_service.update_invoice(workspace, updated_record)
    job = (
        session.query(ExtractionJob)
        .join(Upload)
        .filter(Upload.internal_doc_number == internal_doc_number)
        .first()
    )
    if job is not None:
        job.sheet_row_ref = result.row_number
        if updated_record.validat:
            job.status = "validated"
        else:
            job.status = "needs_validation"
    session.commit()
    refreshed_records = {item.num_doc_intern: item for item in sync_sheet_records(session, request.app)}
    return refreshed_records.get(internal_doc_number, updated_record)


@router.post("/{internal_doc_number}/validate", response_model=InvoiceRecord)
def validate_invoice(
    internal_doc_number: str,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = get_invoice(internal_doc_number, request, session)
    updated = record.model_copy(update={"validat": True, "extraction_status": "validated"})
    workspace = get_workspace_setting(session)
    sheet_service = GoogleSheetsService(request.app.state.settings)
    sheet_service.update_invoice(workspace, updated)
    job = (
        session.query(ExtractionJob)
        .join(Upload)
        .filter(Upload.internal_doc_number == internal_doc_number)
        .first()
    )
    if job is not None:
        job.status = "validated"
    session.commit()
    refreshed = {item.num_doc_intern: item for item in sync_sheet_records(session, request.app)}
    return refreshed.get(internal_doc_number, updated)


@router.get("/{internal_doc_number}/file")
def get_invoice_file(
    internal_doc_number: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    upload = (
        session.query(Upload).filter(Upload.internal_doc_number == internal_doc_number).first()
    )
    if upload is None:
        raise HTTPException(status_code=404, detail="File not found")
    file_path = Path(upload.stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        path=file_path,
        media_type=upload.source_file_type,
        filename=upload.source_file_name,
    )


@router.delete("/{internal_doc_number}", status_code=204)
def delete_invoice_record(
    internal_doc_number: str,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    workspace = get_workspace_setting(session)
    sheet_service = GoogleSheetsService(request.app.state.settings)
    if sheet_service.is_ready(workspace):
        try:
            sheet_service.delete_invoice(workspace, internal_doc_number)
        except RuntimeError:
            pass  # not in sheet, proceed with local cleanup

    upload = (
        session.query(Upload).filter(Upload.internal_doc_number == internal_doc_number).first()
    )
    if upload is not None:
        # Delete the job first to avoid NOT NULL FK constraint errors before DB cascade fires
        if upload.job is not None:
            session.delete(upload.job)
            session.flush()
        session.delete(upload)

    session.commit()


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    job = session.get(ExtractionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    extracted_payload = (
        InvoiceExtraction.model_validate(job.extracted_payload)
        if job.extracted_payload is not None
        else None
    )
    return JobRead(
        id=job.id,
        internal_doc_number=job.upload.internal_doc_number,
        status=job.status,
        error_message=job.error_message,
        extracted_payload=extracted_payload,
        sheet_row_ref=job.sheet_row_ref,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
