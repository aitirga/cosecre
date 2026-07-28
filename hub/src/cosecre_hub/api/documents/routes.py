"""Invoice and ticket intake — the first domain module on top of the hub core.

Both document types behave identically apart from their label, sheet tab and
reference prefix, so one router factory serves both rather than two near-copies.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...deps import get_current_user, get_db, get_settings, get_workspace_setting
from ...models import ExtractionJob, Upload, User
from ...schemas import (
    DocumentType,
    InvoiceExtraction,
    InvoiceRecord,
    InvoiceUpdate,
    JobRead,
    RefreshResult,
    UploadResponse,
)
from ...services.extraction import DocumentExtractionService
from ...services.sheets import GoogleSheetsService
from ...services.storage import save_upload_file

DOCUMENT_META = {
    "invoice": {
        "label": "Invoice",
        "route_segment": "documents/invoices",
        "prefix": "INV",
    },
    "ticket": {
        "label": "Ticket",
        "route_segment": "documents/tickets",
        "prefix": "TKT",
    },
}

_IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_internal_doc_number(document_type: DocumentType) -> str:
    prefix = DOCUMENT_META[document_type]["prefix"]
    return f"{prefix}-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def document_sort_value(document: InvoiceRecord) -> float:
    reference = document.updated_at or document.created_at
    if reference is None:
        return 0
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference.timestamp()


def merge_sheet_and_jobs(
    session: Session,
    document_type: DocumentType,
    sheet_records: list[InvoiceRecord],
) -> list[InvoiceRecord]:
    """Overlay in-flight local jobs on top of what the spreadsheet says.

    The sheet is the source of truth for anything that made it there; jobs that
    have not landed yet only exist locally, and would otherwise be invisible
    between upload and sync.
    """
    route_segment = DOCUMENT_META[document_type]["route_segment"]
    merged = {record.num_doc_intern: record for record in sheet_records}

    uploads_by_doc: dict[str, Upload] = {
        upload.internal_doc_number: upload
        for upload in session.query(Upload).filter(Upload.document_type == document_type).all()
    }

    jobs = (
        session.query(ExtractionJob).join(Upload).filter(Upload.document_type == document_type).all()
    )
    for job in jobs:
        internal_doc_number = job.upload.internal_doc_number
        if internal_doc_number in merged:
            # Already in the sheet — the only thing worth adding is a local
            # preview URL for documents we still hold the original of.
            upload = uploads_by_doc.get(internal_doc_number)
            if upload and upload.source_file_type in _IMAGE_MIME_TYPES:
                existing = merged[internal_doc_number]
                merged[internal_doc_number] = existing.model_copy(
                    update={
                        "document_type": document_type,
                        "file_url": f"/{route_segment}/{internal_doc_number}/file",
                        "source_file_type": upload.source_file_type,
                    }
                )
            continue

        if job.status not in {"pending", "processing", "written_to_sheet", "error"}:
            continue

        extracted_payload = job.extracted_payload or {}
        file_url = (
            f"/{route_segment}/{internal_doc_number}/file"
            if job.upload.source_file_type in _IMAGE_MIME_TYPES
            else None
        )
        merged[internal_doc_number] = InvoiceRecord(
            document_type=document_type,
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

    return sorted(merged.values(), key=document_sort_value, reverse=True)


def sync_sheet_records(session: Session, app, document_type: DocumentType) -> list[InvoiceRecord]:
    workspace = get_workspace_setting(session)
    sheet_service = GoogleSheetsService(app.state.settings)
    if not sheet_service.is_ready(workspace, document_type):
        return []
    try:
        return sheet_service.list_documents(workspace, document_type)
    except Exception:  # noqa: BLE001
        # A Sheets outage degrades the list to local jobs only rather than
        # failing the whole request.
        logger.exception("Failed to fetch %s records from Google Sheets", document_type)
        return []


def process_job(app, job_id: str) -> None:
    """Extract, upload to Drive, then append to the sheet.

    Runs as a background task, so nothing here may raise: every failure is
    recorded on the job for the client to poll.
    """
    session_factory = app.state.session_factory
    settings = app.state.settings
    extraction = DocumentExtractionService(app.state.llm_registry)
    sheet_service = GoogleSheetsService(settings)
    session = session_factory()
    try:
        job = session.get(ExtractionJob, job_id)
        if job is None:
            return
        upload = job.upload
        document_type: DocumentType = upload.document_type  # type: ignore[assignment]
        workspace = get_workspace_setting(session)
        job.status = "processing"
        upload.status = "processing"
        session.commit()

        extracted = extraction.extract(
            Path(upload.stored_path),
            upload.source_file_type,
            model=workspace.openai_model or settings.openai_model,
            prompt_override=workspace.extraction_prompt,
            document_type=document_type,
        )
        job.extracted_payload = extracted.model_dump(by_alias=True)
        job.status = "written_to_sheet"
        session.commit()

        drive_link = ""
        drive_file_id = ""
        try:
            folder_id = (
                settings.google_drive_invoices_folder_id
                if document_type == "invoice"
                else settings.google_drive_tickets_folder_id
            )
            drive_link, drive_file_id = sheet_service.upload_file_to_drive(
                Path(upload.stored_path),
                upload.source_file_name,
                upload.source_file_type,
                folder_id=folder_id,
            )
            upload.drive_file_id = drive_file_id
        except Exception:  # noqa: BLE001
            # The extraction is the valuable part; a missing Drive copy only costs
            # the sheet its thumbnail.
            logger.warning("Drive upload failed for %s", upload.internal_doc_number, exc_info=True)

        is_image = upload.source_file_type in {"image/jpeg", "image/jpg", "image/png"}
        if is_image and drive_file_id:
            file_cell = f'=IMAGE("https://drive.google.com/uc?export=view&id={drive_file_id}")'
        else:
            file_cell = drive_link

        document_for_sheet = InvoiceRecord(
            **extracted.model_dump(by_alias=False),
            document_type=document_type,
            num_doc_intern=upload.internal_doc_number,
            file_link=file_cell,
            source_file_type=upload.source_file_type,
        )
        write_result = sheet_service.append_document(workspace, document_type, document_for_sheet)
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


def create_documents_router(document_type: DocumentType) -> APIRouter:
    router = APIRouter()
    document_label = DOCUMENT_META[document_type]["label"]

    @router.post("/upload", response_model=UploadResponse)
    async def upload_document(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
        settings=Depends(get_settings),
    ):
        internal_doc_number = generate_internal_doc_number(document_type)
        stored_path = await save_upload_file(file, internal_doc_number, settings)

        upload = Upload(
            user_id=user.id,
            internal_doc_number=internal_doc_number,
            document_type=document_type,
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
        return UploadResponse(
            job_id=job.id,
            document_type=document_type,
            internal_doc_number=internal_doc_number,
            status="pending",
        )

    @router.get("/refresh", response_model=RefreshResult)
    def refresh_documents(
        request: Request,
        session: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ):
        records = sync_sheet_records(session, request.app, document_type)
        return RefreshResult(refreshed=len(records))

    @router.get("", response_model=list[InvoiceRecord])
    def list_documents(
        request: Request,
        session: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ):
        records = sync_sheet_records(session, request.app, document_type)
        return merge_sheet_and_jobs(session, document_type, records)

    @router.get("/jobs/{job_id}", response_model=JobRead)
    def get_job(
        job_id: str, session: Session = Depends(get_db), _: User = Depends(get_current_user)
    ):
        job = (
            session.query(ExtractionJob)
            .join(Upload)
            .filter(ExtractionJob.id == job_id, Upload.document_type == document_type)
            .first()
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        extracted_payload = (
            InvoiceExtraction.model_validate(job.extracted_payload)
            if job.extracted_payload is not None
            else None
        )
        return JobRead(
            id=job.id,
            document_type=document_type,
            internal_doc_number=job.upload.internal_doc_number,
            status=job.status,
            error_message=job.error_message,
            extracted_payload=extracted_payload,
            sheet_row_ref=job.sheet_row_ref,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @router.get("/{internal_doc_number}", response_model=InvoiceRecord)
    def get_document(
        internal_doc_number: str,
        request: Request,
        session: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ):
        records = merge_sheet_and_jobs(
            session, document_type, sync_sheet_records(session, request.app, document_type)
        )
        for record in records:
            if record.num_doc_intern == internal_doc_number:
                return record
        raise HTTPException(status_code=404, detail=f"{document_label} not found")

    @router.patch("/{internal_doc_number}", response_model=InvoiceRecord)
    def update_document(
        internal_doc_number: str,
        payload: InvoiceUpdate,
        request: Request,
        session: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ):
        workspace = get_workspace_setting(session)
        sheet_service = GoogleSheetsService(request.app.state.settings)
        if not sheet_service.is_ready(workspace, document_type):
            raise HTTPException(status_code=400, detail="Google Sheets is not configured")
        records = {
            record.num_doc_intern: record
            for record in sync_sheet_records(session, request.app, document_type)
        }
        record = records.get(internal_doc_number)
        if record is None:
            raise HTTPException(status_code=404, detail=f"{document_label} not found")

        updated_record = record.model_copy(
            update={
                "document_type": document_type,
                **payload.model_dump(exclude_none=True, by_alias=False),
            }
        )
        result = sheet_service.update_document(workspace, document_type, updated_record)
        job = (
            session.query(ExtractionJob)
            .join(Upload)
            .filter(
                Upload.internal_doc_number == internal_doc_number,
                Upload.document_type == document_type,
            )
            .first()
        )
        if job is not None:
            job.sheet_row_ref = result.row_number
            job.status = "validated" if updated_record.validat else "needs_validation"
        session.commit()
        refreshed_records = {
            item.num_doc_intern: item
            for item in sync_sheet_records(session, request.app, document_type)
        }
        return refreshed_records.get(internal_doc_number, updated_record)

    @router.post("/{internal_doc_number}/validate", response_model=InvoiceRecord)
    def validate_document(
        internal_doc_number: str,
        request: Request,
        session: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ):
        record = get_document(internal_doc_number, request, session)
        updated = record.model_copy(
            update={
                "document_type": document_type,
                "validat": True,
                "extraction_status": "validated",
            }
        )
        workspace = get_workspace_setting(session)
        sheet_service = GoogleSheetsService(request.app.state.settings)
        sheet_service.update_document(workspace, document_type, updated)
        job = (
            session.query(ExtractionJob)
            .join(Upload)
            .filter(
                Upload.internal_doc_number == internal_doc_number,
                Upload.document_type == document_type,
            )
            .first()
        )
        if job is not None:
            job.status = "validated"
        session.commit()
        refreshed = {
            item.num_doc_intern: item
            for item in sync_sheet_records(session, request.app, document_type)
        }
        return refreshed.get(internal_doc_number, updated)

    @router.get("/{internal_doc_number}/file")
    def get_document_file(
        internal_doc_number: str,
        session: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ):
        upload = (
            session.query(Upload)
            .filter(
                Upload.internal_doc_number == internal_doc_number,
                Upload.document_type == document_type,
            )
            .first()
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

    @router.delete("/{internal_doc_number}", status_code=204, response_model=None)
    def delete_document_record(
        internal_doc_number: str,
        request: Request,
        session: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ) -> None:
        workspace = get_workspace_setting(session)
        sheet_service = GoogleSheetsService(request.app.state.settings)
        if sheet_service.is_ready(workspace, document_type):
            try:
                sheet_service.delete_document(workspace, document_type, internal_doc_number)
            except RuntimeError:
                pass

        upload = (
            session.query(Upload)
            .filter(
                Upload.internal_doc_number == internal_doc_number,
                Upload.document_type == document_type,
            )
            .first()
        )
        if upload is not None:
            if upload.drive_file_id:
                try:
                    sheet_service.delete_drive_file(upload.drive_file_id)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Could not remove Drive file for %s", internal_doc_number, exc_info=True
                    )
            if upload.job is not None:
                session.delete(upload.job)
                session.flush()
            session.delete(upload)

        session.commit()

    return router
