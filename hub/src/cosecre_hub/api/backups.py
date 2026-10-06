"""Versions of the register, for administrators.

List them with what changed between each, compare one with the present,
restore it, download it, or upload one taken elsewhere.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..deps import require_admin
from ..models import User
from ..services.backup import BackupError, BackupService, busy, info_dict

router = APIRouter()

#: An uploaded database is a few MB today; this leaves room for years of growth.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class BackupRead(BaseModel):
    name: str
    size: int
    created_at: datetime
    kind: str
    kind_label: str
    reason: str = ""
    author: str | None = None
    documents: int | None = None
    added: int | None = None
    removed: int | None = None
    changed: int | None = None
    has_sheet: bool = False


class BackupOverview(BaseModel):
    backups: list[BackupRead]
    directory: str
    keep: int
    interval_hours: float
    offsite_configured: bool
    last_offsite_at: datetime | None = None
    last_error: str | None = None


class BackupComparison(BaseModel):
    name: str
    entries: list[dict[str, Any]]
    counts: dict[str, int]


class RestoreResult(BaseModel):
    restored: int
    safety_backup: str
    overview: BackupOverview


def _service(request: Request) -> BackupService:
    return request.app.state.backup_service


def _overview(service: BackupService) -> BackupOverview:
    return BackupOverview(
        backups=[BackupRead(**info_dict(item)) for item in service.list()],
        directory=str(service.directory),
        keep=service.settings.backup_keep,
        interval_hours=service.settings.backup_interval_hours,
        offsite_configured=service.offsite_configured,
        last_offsite_at=service.last_offsite_at,
        last_error=service.last_error,
    )


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, BackupError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"No s'ha pogut completar: {exc}")


@router.get("", response_model=BackupOverview)
def list_backups(request: Request, _: User = Depends(require_admin)):
    return _overview(_service(request))


@router.post("", response_model=BackupOverview)
async def create_backup(request: Request, admin: User = Depends(require_admin)):
    service = _service(request)
    try:
        await run_in_threadpool(service.create, "feta a mà", kind="manual", author=admin.email)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return _overview(service)


@router.post("/upload", response_model=BackupOverview)
async def upload_backup(
    request: Request, file: UploadFile = File(...), admin: User = Depends(require_admin)
):
    """A backup zip from this hub, or a bare ``cosecre.db``, becomes a new version."""
    service = _service(request)
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "upload"
        written = 0
        with target.open("wb") as sink:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="El fitxer és massa gran.")
                sink.write(chunk)
        try:
            await run_in_threadpool(
                service.import_file, target, file.filename or "fitxer", author=admin.email
            )
        except Exception as exc:  # noqa: BLE001
            raise _fail(exc) from exc
    return _overview(service)


@router.get("/{name}/compare", response_model=BackupComparison)
async def compare_backup(name: str, request: Request, _: User = Depends(require_admin)):
    try:
        entries = await run_in_threadpool(_service(request).compare, name)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return BackupComparison(name=name, entries=[vars(e) for e in entries], counts=counts)


@router.post("/{name}/restore", response_model=RestoreResult)
async def restore_backup(name: str, request: Request, admin: User = Depends(require_admin)):
    """Bring the register back to this version. The present is saved as a version first."""
    app = request.app
    service = _service(request)
    is_busy = busy(app.state.session_factory, app.state.enrichment_running)
    def run() -> dict:
        # Taken in the worker thread: no sheet sync may interleave with a restore.
        with app.state.register_lock:
            result = service.restore(name, author=admin.email, busy=is_busy)
            from .documents.sync import trust_database

            session = app.state.session_factory()
            try:
                trust_database(session)
            finally:
                session.close()
            return result

    try:
        result = await run_in_threadpool(run)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    app.state.register_synced_at = 0.0
    app.state.sheet_status = None
    return RestoreResult(**result, overview=_overview(service))


@router.get("/{name}")
def download_backup(name: str, request: Request, _: User = Depends(require_admin)):
    path = _service(request).path_for(name)
    if path is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat la còpia.")
    return FileResponse(path, media_type="application/zip", filename=name)
