"""Moving the two old tabs into the register, without losing anything.

Two phases:

1. **Copy.** Every row of "Factures" and "Tiquets" becomes a register entry:
   fields converted (dates, amounts, the address split in three, casing), the
   person's values kept as they are. The old tabs are left in place; the only
   thing written to them is a reference in rows that had none, which is what
   makes running the migration twice safe.
2. **Enrich.** Entries whose original can still be found — on this server or on
   Drive — are read again by the models, to fill the fields the old tabs never
   had (type, payment, bank account…). They only fill gaps: a value a person
   entered or validated is never replaced.
"""

from __future__ import annotations

import logging
import tempfile

import anyio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ...deps import get_db, get_workspace_setting, require_admin
from ...models import Document, Upload, User
from ...schemas import AiHint, MigrationReport
from ...schemas.documents import MigrationIssue
from ...services.extraction import DocumentExtractionService
from ...services.sheets import GoogleSheetsService, LegacyTab, drive_file_id_from_link, parse_bool
from ...services.text_format import (
    compact_code,
    name_case,
    parse_amount,
    parse_date,
    sentence_case,
    split_address,
)
from .register import (
    IMAGE_MIME_TYPES,
    apply_extraction,
    file_cell,
    generate_reference,
    push_document,
    sheet_values,
    status_after_review,
    unique_drive_name,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: What a row's old tab says about its type, when no original is left to read.
LEGACY_TYPE_GUESS = {"invoice": "Factura", "ticket": "Factura simplificada"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _legacy_tabs(service: GoogleSheetsService, workspace) -> list[tuple[str, LegacyTab | None]]:
    return [
        ("invoice", service.read_legacy_tab(workspace, workspace.sheet_name)),
        ("ticket", service.read_legacy_tab(workspace, workspace.ticket_sheet_name)),
    ]


def _origin(upload: Upload | None, file_link: str) -> str:
    if upload is not None:
        if upload.capture_source:
            return "Foto" if upload.capture_source == "camera" else "Original"
        return "Foto" if upload.source_file_type in IMAGE_MIME_TYPES else "Original"
    if file_link.startswith("=IMAGE"):
        return "Foto"
    return "Original" if file_link else ""


def convert_row(values: dict, legacy_type: str, upload: Upload | None) -> tuple[dict, dict, list[str]]:
    """An old-tab row → register fields, hints, and problems worth reporting."""
    problems: list[str] = []
    hints: dict[str, dict] = {}

    raw_date = values.get("data_factura")
    data_factura = parse_date(raw_date)
    if raw_date not in (None, "") and data_factura is None:
        problems.append(f"Data no reconeguda: {raw_date!r}")
        hints["data_factura"] = AiHint(
            source="migracio", alternative=str(raw_date), review=True
        ).model_dump(exclude_none=True)

    street, postcode, city = split_address(str(values.get("adreca_proveidor") or ""))
    file_link = str(values.get("file_link") or "").strip()
    fields = {
        "num_factura": str(values.get("num_factura") or "").strip(),
        "data_factura": data_factura,
        "proveidor": name_case(str(values.get("proveidor") or "")),
        "cif_proveidor": compact_code(str(values.get("cif_proveidor") or "")),
        "carrer": name_case(street),
        "codi_postal": postcode,
        "ciutat": name_case(city),
        "cif_proveit": compact_code(str(values.get("cif_proveit") or "")),
        "import_value": parse_amount(values.get("import_value")),
        "descripcio": sentence_case(str(values.get("descripcio") or "")),
        "pressupost_afectat": str(values.get("pressupost_afectat") or "").strip(),
        "file_link": file_link,
        "validat": parse_bool(values.get("validat")) if values.get("validat") not in (None, "") else False,
        "origen": _origin(upload, file_link),
    }
    if fields["import_value"] is None and values.get("import_value") not in (None, ""):
        problems.append(f"Import no reconegut: {values.get('import_value')!r}")
    return fields, hints, problems


def migrate(app, session: Session, *, dry_run: bool) -> MigrationReport:
    service: GoogleSheetsService = app.state.sheet_service
    workspace = get_workspace_setting(session)
    if not service.is_ready(workspace):
        raise HTTPException(status_code=400, detail="Google Sheets no està configurat.")

    report = MigrationReport(dry_run=dry_run)
    existing = {ref for (ref,) in session.query(Document.internal_doc_number).all()}
    uploads = {u.internal_doc_number: u for u in session.query(Upload).all()}
    created: list[Document] = []
    seen: set[str] = set()

    with app.state.register_lock:
        for legacy_type, tab in _legacy_tabs(service, workspace):
            label = workspace.sheet_name if legacy_type == "invoice" else workspace.ticket_sheet_name
            if tab is None:
                report.issues.append(MigrationIssue(tab=label, message="No s'ha trobat la pestanya."))
                continue
            report.tabs[tab.title] = len(tab.rows)
            written_back: list[tuple[int, str]] = []
            for row in tab.rows:
                if not any(
                    value not in (None, "")
                    for name, value in row.values.items()
                    if name not in {"validat", "num_doc_intern"}
                ):
                    continue  # a pre-ticked checkbox row, not a document
                reference = str(row.values.get("num_doc_intern") or "").strip()
                if reference and reference in existing:
                    report.already_migrated += 1
                    continue
                if not reference or reference in seen:
                    reference = generate_reference()
                    written_back.append((row.row_number, reference))
                    report.references_generated += 1
                seen.add(reference)
                upload = uploads.get(reference)
                fields, hints, problems = convert_row(row.values, legacy_type, upload)
                for message in problems:
                    report.issues.append(
                        MigrationIssue(tab=tab.title, row=row.row_number, reference=reference, message=message)
                    )
                report.to_create += 1
                has_file = bool(
                    (upload is not None and Path(upload.stored_path).exists())
                    or drive_file_id_from_link(fields["file_link"])
                    or (upload is not None and upload.drive_file_id)
                )
                report.with_file += int(has_file)
                if dry_run:
                    continue
                document = Document(
                    internal_doc_number=reference,
                    upload_id=upload.id if upload else None,
                    legacy_type=legacy_type,
                    ai_hints=hints,
                    sheet_state="pending",
                    drive_file_id=(upload.drive_file_id if upload else None)
                    or drive_file_id_from_link(fields["file_link"]),
                    **fields,
                )
                document.status = status_after_review(document)
                if upload is not None and upload.created_at:
                    document.created_at = upload.created_at
                session.add(document)
                created.append(document)
            if written_back and not dry_run:
                service.write_legacy_references(workspace, tab, written_back)

        # Uploads that never reached either tab — an extraction that failed or
        # was interrupted — exist only in the database. They come across too.
        for reference, upload in uploads.items():
            if reference in existing or reference in seen or upload.document_type not in LEGACY_TYPE_GUESS:
                continue
            seen.add(reference)
            payload = dict((upload.job.extracted_payload if upload.job else None) or {})
            payload["import_value"] = payload.pop("import", None)
            fields, hints, problems = convert_row(payload, upload.document_type, upload)
            report.to_create += 1
            report.from_database += 1
            report.with_file += int(Path(upload.stored_path).exists())
            report.issues.append(
                MigrationIssue(
                    tab="base de dades",
                    reference=reference,
                    message="No era a cap pestanya (la lectura no va acabar); es recupera de la base de dades.",
                )
            )
            if dry_run:
                continue
            document = Document(
                internal_doc_number=reference,
                upload_id=upload.id,
                legacy_type=upload.document_type,
                ai_hints=hints,
                sheet_state="pending",
                **fields,
            )
            document.status = "needs_validation"
            document.created_at = upload.created_at
            session.add(document)
            created.append(document)

        if dry_run:
            return report

        session.flush()
        if created:
            numbers = service.append_rows(workspace, [sheet_values(d) for d in created])
            for document, row_number in zip(created, numbers):
                document.sheet_row_ref = row_number
                document.sheet_state = "synced"
        report.created = len(created)
        workspace.migration_completed_at = utcnow()
        report.completed_at = workspace.migration_completed_at
        session.commit()
    return report


# ── Enrichment ───────────────────────────────────────────────────────────────

ADDRESS_FIELDS = ("carrer", "codi_postal", "ciutat")


def _original_file(service: GoogleSheetsService, document: Document, scratch: Path) -> tuple[Path, str] | None:
    upload = document.upload
    if upload is not None and Path(upload.stored_path).exists():
        return Path(upload.stored_path), upload.source_file_type
    if document.drive_file_id and service.drive_ready:
        destination = scratch / document.internal_doc_number
        mime = service.download_drive_file(document.drive_file_id, destination)
        return destination, mime
    return None


def enrich_one(app, document_id: int) -> None:
    session = app.state.session_factory()
    service: GoogleSheetsService = app.state.sheet_service
    try:
        document = session.get(Document, document_id)
        if document is None or document.enriched_at is not None:
            return
        workspace = get_workspace_setting(session)
        original_mime: str | None = None
        with tempfile.TemporaryDirectory() as scratch:
            try:
                original = _original_file(service, document, Path(scratch))
            except Exception:  # noqa: BLE001
                logger.warning("Could not fetch the original of %s", document.internal_doc_number, exc_info=True)
                original = None
            if original is not None:
                original_mime = original[1]
            if original is not None and original[1] in IMAGE_MIME_TYPES | {"application/pdf"}:
                extraction = DocumentExtractionService(app.state.llm_registry, app.state.classifier)
                extracted = extraction.extract(
                    original[0],
                    original[1],
                    model=workspace.openai_model or app.state.settings.openai_model,
                    prompt_override=workspace.extraction_prompt,
                )
                # When the old single address column could not be split cleanly,
                # the model's reading of the document is the better source.
                split_cleanly = all(getattr(document, name) for name in ADDRESS_FIELDS)
                if not split_cleanly and all(extracted.fields.get(name) for name in ADDRESS_FIELDS):
                    for name in ADDRESS_FIELDS:
                        setattr(document, name, "")
                apply_extraction(document, extracted, only_empty=True)

        if not document.tipus_document and document.legacy_type in LEGACY_TYPE_GUESS:
            document.tipus_document = LEGACY_TYPE_GUESS[document.legacy_type]
            hints = dict(document.ai_hints or {})
            hints["tipus_document"] = AiHint(source="migracio", review=True).model_dump(exclude_none=True)
            document.ai_hints = hints

        if document.drive_file_id and service.drive_ready:
            try:
                folder_id = app.state.settings.documents_folder_id
                with app.state.drive_lock:
                    name = unique_drive_name(service, folder_id, document, mime_type=original_mime)
                    service.update_drive_file(document.drive_file_id, name=name, folder_id=folder_id)
                document.drive_file_name = name
            except Exception:  # noqa: BLE001
                logger.warning("Could not rename/move %s on Drive", document.internal_doc_number, exc_info=True)

        document.enriched_at = utcnow()
        document.sheet_state = "pending"
        session.commit()
        push_document(app, session, document)
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("Enrichment of document %s failed", document_id)
    finally:
        session.close()


def pending_enrichment(session: Session) -> list[int]:
    return [
        doc_id
        for (doc_id,) in session.query(Document.id)
        .filter(Document.legacy_type.isnot(None), Document.enriched_at.is_(None))
        .order_by(Document.id)
        .all()
    ]


async def enrich_all(app) -> None:
    """Several entries at once, always leaving one reading slot to live uploads."""
    if app.state.enrichment_running:
        return
    app.state.enrichment_running = True

    async def enrich(document_id: int) -> None:
        async with app.state.enrichment_limiter, app.state.extraction_limiter:
            await run_in_threadpool(enrich_one, app, document_id)

    try:
        with app.state.session_factory() as session:
            ids = pending_enrichment(session)
        async with anyio.create_task_group() as group:
            for document_id in ids:
                group.start_soon(enrich, document_id)
    finally:
        app.state.enrichment_running = False


# ── Originals that never reached Drive ───────────────────────────────────────


def missing_on_drive(session: Session) -> list[int]:
    return [
        doc_id
        for (doc_id,) in session.query(Document.id)
        .join(Upload, Document.upload_id == Upload.id)
        .filter(Document.drive_file_id.is_(None))
        .order_by(Document.id)
        .all()
    ]


def upload_original(app, document_id: int) -> bool:
    """Put one entry's original in the documents folder and link it in the sheet."""
    service: GoogleSheetsService = app.state.sheet_service
    session = app.state.session_factory()
    try:
        document = session.get(Document, document_id)
        upload = document.upload if document else None
        if document is None or upload is None or document.drive_file_id:
            return False
        path = Path(upload.stored_path)
        if not path.exists():
            return False
        folder_id = app.state.settings.documents_folder_id
        with app.state.drive_lock:
            name = unique_drive_name(service, folder_id, document, mime_type=upload.source_file_type)
            _, file_id = service.upload_file_to_drive(path, name, upload.source_file_type, folder_id=folder_id)
        upload.drive_file_id = document.drive_file_id = file_id
        document.drive_file_name = name
        document.file_link = file_cell(file_id, upload.source_file_type)
        session.commit()
        push_document(app, session, document)
        session.commit()
        return True
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.warning("Could not put the original of %s on Drive", document_id, exc_info=True)
        return False
    finally:
        session.close()


async def upload_missing_originals(app) -> None:
    if app.state.drive_backfill_running:
        return
    app.state.drive_backfill_running = True
    try:
        with app.state.session_factory() as session:
            ids = missing_on_drive(session)
        limiter = anyio.CapacityLimiter(4)

        async def one(document_id: int) -> None:
            async with limiter:
                await run_in_threadpool(upload_original, app, document_id)

        async with anyio.create_task_group() as group:
            for document_id in ids:
                group.start_soon(one, document_id)
    finally:
        app.state.drive_backfill_running = False


def _status(app, session: Session, report: MigrationReport) -> MigrationReport:
    workspace = get_workspace_setting(session)
    legacy = session.query(Document).filter(Document.legacy_type.isnot(None))
    report.enrichment_pending = legacy.filter(Document.enriched_at.is_(None)).count()
    report.enrichment_done = legacy.filter(Document.enriched_at.isnot(None)).count()
    report.enrichment_running = app.state.enrichment_running
    report.completed_at = report.completed_at or workspace.migration_completed_at
    report.drive_missing = len(missing_on_drive(session))
    report.drive_running = app.state.drive_backfill_running
    report.drive_configured = (
        app.state.sheet_service.drive_ready and app.state.settings.documents_folder_id is not None
    )
    return report


@router.get("/status", response_model=MigrationReport)
def migration_status(
    request: Request, session: Session = Depends(get_db), _: User = Depends(require_admin)
):
    """Progress only — cheap enough to poll, unlike the preview."""
    return _status(request.app, session, MigrationReport(dry_run=True))


@router.get("", response_model=MigrationReport)
def preview_migration(
    request: Request, session: Session = Depends(get_db), _: User = Depends(require_admin)
):
    """What a migration would do now. Reads the sheet; writes nothing."""
    return _status(request.app, session, migrate(request.app, session, dry_run=True))


@router.post("", response_model=MigrationReport)
def run_migration(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        request.app.state.backup_service.create("abans de la migració", kind="pre-migration")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"No s'ha pogut fer la còpia de seguretat prèvia; no s'ha migrat res: {exc}",
        ) from exc
    report = migrate(request.app, session, dry_run=False)
    background_tasks.add_task(enrich_all, request.app)
    report = _status(request.app, session, report)
    report.enrichment_running = report.enrichment_pending > 0
    return report


@router.post("/drive", response_model=MigrationReport)
def upload_originals(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Put every original that only lives on this server into the Drive folder."""
    if request.app.state.settings.documents_folder_id is None:
        raise HTTPException(status_code=400, detail="No hi ha cap carpeta de Drive configurada.")
    background_tasks.add_task(upload_missing_originals, request.app)
    report = _status(request.app, session, MigrationReport(dry_run=False))
    report.drive_running = report.drive_missing > 0
    return report


@router.post("/enrich", response_model=MigrationReport)
def resume_enrichment(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Pick enrichment up again, e.g. after a restart interrupted it."""
    background_tasks.add_task(enrich_all, request.app)
    report = _status(request.app, session, MigrationReport(dry_run=False))
    report.enrichment_running = report.enrichment_pending > 0
    return report
