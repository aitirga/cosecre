"""Keeping the caixeta's movements in step with its spreadsheet.

The machine sleeps when nobody uses the app, so there is no timer: the sheet is
checked when the hub starts and whenever someone opens the app, at most once
every :data:`MIN_INTERVAL_SECONDS`. Reading costs one batched Sheets call; the
database is only touched when the sheet's content actually changed.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ...deps import get_workspace_setting
from ...models import StatementImport
from ...services.sheets import parse_spreadsheet_id
from ...services.statements import SOURCE_CAIXETA, caixeta, store

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 120

_lock = threading.Lock()


def configured(app, session: Session) -> bool:
    workspace = get_workspace_setting(session)
    return bool(workspace.caixeta_spreadsheet_url and app.state.sheet_service.drive_ready)


def living_statement(session: Session) -> StatementImport | None:
    return (
        session.query(StatementImport)
        .filter(StatementImport.source == SOURCE_CAIXETA)
        .order_by(StatementImport.id)
        .first()
    )


def sync(app, session: Session, *, force: bool = False) -> bool | None:
    """Read the sheet; store it if it changed. ``None`` when not configured.

    Returns whether anything changed. Serialised: two people opening the app at
    once trigger one read, not two writers.
    """
    workspace = get_workspace_setting(session)
    if not configured(app, session):
        return None
    with _lock:
        app.state.caixeta_checked_at = time.monotonic()
        app.state.caixeta_error = None
        try:
            spreadsheet_id = parse_spreadsheet_id(workspace.caixeta_spreadsheet_url)
            tabs = app.state.sheet_service.read_tabs(spreadsheet_id, caixeta.TAB_PATTERN)
        except Exception as exc:  # noqa: BLE001 — Google errors become a status line
            logger.warning("Could not read the caixeta sheet", exc_info=True)
            app.state.caixeta_error = f"No s'ha pogut llegir el full de la caixeta: {exc}"[:300]
            return False
        fingerprint = caixeta.content_fingerprint(tabs)
        statement = living_statement(session)
        workspace.caixeta_synced_at = datetime.now(UTC)
        if fingerprint == workspace.caixeta_fingerprint and statement is not None and not force:
            session.commit()
            return False
        parsed = caixeta.parse(tabs)
        statement = store.save(
            session,
            parsed,
            compte="Caixeta",
            file_name="Caixeta d'efectiu (Google Sheets)",
            statement=statement,
        )
        workspace.caixeta_fingerprint = fingerprint
        session.commit()
        from ..statements_mirror import schedule  # the mirror imports the reconciliation, which imports us

        schedule(app)
        logger.info("Caixeta synced: %d movements, %d new", statement.rows_total, statement.rows_new)
        return True


def sync_if_due(app) -> None:
    """The fire-and-forget trigger: throttled, and never raises."""
    last = getattr(app.state, "caixeta_checked_at", 0.0)
    if time.monotonic() - last < MIN_INTERVAL_SECONDS or _lock.locked():
        return
    session = app.state.session_factory()
    try:
        sync(app, session)
    except Exception:  # noqa: BLE001
        logger.exception("Caixeta sync failed")
        session.rollback()
    finally:
        session.close()
