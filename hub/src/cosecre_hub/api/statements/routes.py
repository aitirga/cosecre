"""Bringing statements in. Nothing here matches anything — see ``api.reconciliation``.

One dropzone takes both files: a CaixaBank Excel (any of the three accounts)
or the prepaid card's PDF. The caixeta needs no upload at all; it is read from
its spreadsheet.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from ...deps import get_current_user, get_db, get_settings, get_workspace_setting
from ...models import BankMovement, PaymentMatch, StatementImport, User
from ...schemas.documents import COMPTES, METODES_PAGAMENT
from ...schemas.statements import (
    AccountNeeded,
    CaixetaStatus,
    MovementRead,
    MovementUpdate,
    StatementRead,
)
from ...services.llm import LLMError
from ...services.statements import (
    PAYMENT,
    SOURCE_CAIXA,
    SOURCE_PREPAID,
    StatementError,
    caixa_xls,
    format_check,
    prepaid_pdf,
    store,
)
from ...services.storage import MAX_UPLOAD_BYTES, sanitize_filename
from . import caixeta_sync

logger = logging.getLogger(__name__)

router = APIRouter()

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def detect(content: bytes, file_name: str) -> str:
    """Which reader a dropped file needs, from its bytes first and its name second."""
    name = file_name.lower()
    if content.startswith(_OLE2) or name.endswith((".xls", ".xlsx", ".xlsm")) or (
        content.startswith(b"PK") and name.endswith((".xlsx", ".xlsm"))
    ):
        return SOURCE_CAIXA
    if content.startswith(b"%PDF") or name.endswith(".pdf"):
        return SOURCE_PREPAID
    raise HTTPException(
        status_code=415,
        detail="Només s'accepten l'Excel de moviments de La Caixa o el PDF de la targeta de prepagament.",
    )


def to_statement_read(statement: StatementImport, warnings: list[str] | None = None) -> StatementRead:
    return StatementRead(
        id=statement.id,
        source=statement.source,
        compte=statement.compte,
        account_iban=statement.account_iban or "",
        file_name=statement.file_name or "",
        status=statement.status,
        error_message=statement.error_message,
        period_from=statement.period_from,
        period_to=statement.period_to,
        rows_total=statement.rows_total,
        rows_new=statement.rows_new,
        rows_duplicate=statement.rows_duplicate,
        created_by=(statement.created_by.display_name or statement.created_by.email)
        if statement.created_by
        else None,
        created_at=statement.created_at,
        updated_at=statement.updated_at,
        has_file=bool(statement.stored_path and Path(statement.stored_path).exists()),
        warnings=warnings or [],
    )


def to_movement_read(movement: BankMovement) -> MovementRead:
    live = [m for m in movement.matches if m.status in {"proposed", "confirmed"}]
    lead = [m for m in live if m.rank == 0] or live
    return MovementRead(
        id=movement.id,
        import_id=movement.import_id,
        source=movement.source,
        compte=movement.compte,
        tipus=movement.tipus,
        categoria=movement.categoria,
        data=movement.data,
        data_valor=movement.data_valor,
        concepte=movement.concepte,
        mes_dades=movement.mes_dades,
        import_value=movement.import_value,
        saldo=movement.saldo,
        num_factura_hint=movement.num_factura_hint,
        cif_hint=movement.cif_hint,
        iban_hint=movement.iban_hint,
        external_ref=movement.external_ref,
        raw=movement.raw or {},
        match_status=movement.match_status,
        linked_movement_id=movement.linked_movement_id,
        confidence=min((m.confidence for m in lead), default=None),
        documents=[m.document.internal_doc_number for m in lead if m.document is not None],
    )


@router.post("/upload", response_model=StatementRead, responses={409: {"model": AccountNeeded}})
async def upload_statement(
    request: Request,
    file: UploadFile = File(...),
    compte: str | None = Form(None),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings=Depends(get_settings),
):
    """Detect what was dropped, read it, and store its movements."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El fitxer és massa gran.")
    if not content:
        raise HTTPException(status_code=400, detail="El fitxer és buit.")
    file_name = file.filename or "extracte"
    kind = detect(content, file_name)
    workspace = get_workspace_setting(session)
    if compte is not None and compte not in COMPTES:
        raise HTTPException(status_code=400, detail="Compte desconegut.")

    warnings: list[str] = []
    try:
        if kind == SOURCE_CAIXA:
            # gpt-6-luna looks at the first rows before anything is parsed: right
            # structure is not the same as the right file.
            rows = caixa_xls.read_rows(content, file_name)
            async with request.app.state.extraction_limiter:
                checked = await run_in_threadpool(
                    format_check.check, request.app.state.llm_registry, rows, model=workspace.openai_model
                )
            if checked.rejected:
                raise HTTPException(status_code=422, detail=checked.message())
            warnings.extend(checked.warnings)
            parsed = caixa_xls.parse(content, file_name)
            seen_iban = checked.verdict.account_iban if checked.verdict else ""
            if seen_iban and parsed.account_iban and (
                seen_iban.replace(" ", "").upper() != parsed.account_iban.replace(" ", "").upper()
            ):
                warnings.append(
                    f"La comprovació amb IA ha llegit l'IBAN {seen_iban}, però el fitxer diu {parsed.account_iban}."
                )
            account = compte or store.account_for_iban(workspace, parsed.account_iban)
            if account is None:
                return JSONResponse(
                    status_code=409,
                    content=AccountNeeded(
                        iban=parsed.account_iban,
                        message=(
                            f"No sabem de quin compte és l'IBAN {parsed.account_iban or '(sense IBAN)'}. "
                            "Tria'l i el recordarem."
                        ),
                    ).model_dump(),
                )
            if compte and parsed.account_iban and not store.account_for_iban(workspace, parsed.account_iban):
                store.remember_iban(workspace, compte, parsed.account_iban)
        else:
            path = _keep(content, file_name, settings)
            async with request.app.state.extraction_limiter:
                parsed = await run_in_threadpool(
                    prepaid_pdf.read, request.app.state.llm_registry, path, model=workspace.openai_model
                )
            account = "Targeta Prepagament"
            card = parsed.meta.get("card_number") or ""
            if card and not workspace.prepaid_card_number:
                workspace.prepaid_card_number = card
            elif card and workspace.prepaid_card_number.replace(" ", "") != card.replace(" ", ""):
                parsed.meta.setdefault("warnings", []).append(
                    f"La targeta de l'extracte ({card}) no és la configurada ({workspace.prepaid_card_number})."
                )
    except StatementError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        logger.exception("The model could not read the prepaid statement")
        raise HTTPException(status_code=502, detail=f"El model no ha pogut llegir el PDF: {exc}") from exc

    stored_path = str(path) if kind == SOURCE_PREPAID else str(_keep(content, file_name, settings))
    statement = store.save(
        session,
        parsed,
        compte=account,
        file_name=file_name,
        stored_path=stored_path,
        user_id=user.id,
    )
    return to_statement_read(statement, warnings + list(parsed.meta.get("warnings") or []))


def _keep(content: bytes, file_name: str, settings) -> Path:
    """The original goes next to the register's, so it can be downloaded again."""
    folder = settings.upload_dir / "statements"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex[:12]}-{sanitize_filename(file_name)}"
    path.write_bytes(content)
    return path


@router.get("/imports", response_model=list[StatementRead])
def list_statements(session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    statements = (
        session.query(StatementImport)
        .options(selectinload(StatementImport.created_by))
        .order_by(StatementImport.created_at.desc())
        .all()
    )
    return [to_statement_read(s) for s in statements]


def _statement(session: Session, statement_id: int) -> StatementImport:
    statement = session.get(StatementImport, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat l'extracte.")
    return statement


@router.get("/imports/{statement_id}/movements", response_model=list[MovementRead])
def list_movements(
    statement_id: int, session: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    _statement(session, statement_id)
    movements = (
        session.query(BankMovement)
        .options(selectinload(BankMovement.matches).selectinload(PaymentMatch.document))
        .filter(BankMovement.import_id == statement_id)
        .order_by(BankMovement.data.desc(), BankMovement.id)
        .all()
    )
    return [to_movement_read(m) for m in movements]


@router.get("/imports/{statement_id}/file")
def download_statement(
    statement_id: int, session: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    statement = _statement(session, statement_id)
    if not statement.stored_path or not Path(statement.stored_path).exists():
        raise HTTPException(status_code=404, detail="L'original ja no és al servidor.")
    return FileResponse(statement.stored_path, filename=statement.file_name or "extracte")


@router.delete("/imports/{statement_id}", status_code=204, response_model=None)
def delete_statement(
    statement_id: int, session: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> None:
    """Remove a statement brought in by mistake. Refused once anything in it is confirmed."""
    statement = _statement(session, statement_id)
    if any(m.match_status == "confirmed" for m in statement.movements):
        raise HTTPException(
            status_code=409,
            detail="Aquest extracte té moviments ja justificats; no es pot esborrar.",
        )
    for movement in statement.movements:
        if movement.linked_movement_id:
            other = session.get(BankMovement, movement.linked_movement_id)
            if other is not None:
                other.linked_movement_id = None
    # The file stays, so undoing this brings the statement back whole.
    for movement in list(statement.movements):
        session.delete(movement)
    session.delete(statement)
    session.commit()


@router.patch("/movements/{movement_id}", response_model=MovementRead)
def update_movement(
    movement_id: int,
    payload: MovementUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Fix what the parser guessed: how the money moved, or what kind of line it is."""
    movement = session.get(BankMovement, movement_id)
    if movement is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat el moviment.")
    if payload.tipus is not None:
        if payload.tipus and payload.tipus not in METODES_PAGAMENT:
            raise HTTPException(status_code=400, detail="Mètode de pagament desconegut.")
        movement.tipus = payload.tipus
    if payload.categoria is not None and payload.categoria != movement.categoria:
        if movement.match_status == "confirmed":
            raise HTTPException(status_code=409, detail="Aquest moviment ja està justificat.")
        movement.categoria = payload.categoria
        for match in session.query(PaymentMatch).filter(PaymentMatch.movement_id == movement.id).all():
            session.delete(match)
        movement.match_status = "unmatched" if payload.categoria == PAYMENT else "not_applicable"
    session.commit()
    session.refresh(movement)
    return to_movement_read(movement)


def _caixeta_status(request: Request, session: Session, changed: bool | None = None) -> CaixetaStatus:
    workspace = get_workspace_setting(session)
    living = caixeta_sync.living_statement(session)
    return CaixetaStatus(
        configured=caixeta_sync.configured(request.app, session),
        synced_at=workspace.caixeta_synced_at,
        running=caixeta_sync._lock.locked(),
        error=getattr(request.app.state, "caixeta_error", None),
        statement_id=living.id if living else None,
        changed=changed,
    )


@router.get("/caixeta", response_model=CaixetaStatus)
def caixeta_status(
    request: Request, session: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    return _caixeta_status(request, session)


@router.post("/caixeta/sync", response_model=CaixetaStatus)
def caixeta_sync_now(
    request: Request,
    if_due: bool = False,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Read the caixeta sheet now; with ``if_due``, only if it was not read recently.

    The app calls this with ``if_due`` whenever someone opens it, which is how
    the caixeta stays current on a machine that sleeps when nobody is around.
    """
    if if_due:
        caixeta_sync.sync_if_due(request.app)
        return _caixeta_status(request, session)
    changed = caixeta_sync.sync(request.app, session, force=True)
    return _caixeta_status(request, session, changed)
