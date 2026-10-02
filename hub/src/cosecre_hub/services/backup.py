"""Backups as versions of the register.

Each backup is one zip:

* ``cosecre.db`` — a consistent SQLite snapshot (the online backup API, so it is
  safe while the hub is writing), integrity-checked before it is kept;
* ``registre.json`` and ``registre.csv`` — every register entry, readable
  without the hub: the CSV opens in Excel with dates as ``dd/mm/yyyy``;
* ``full.json`` — the sheet's rows at that moment, when the backup was taken
  just before the sheet and the database were reconciled;
* ``manifest.json`` — when, why, who, and a fingerprint of every entry, which is
  what lets each version say what changed since the one before it.

They are taken once a day while the machine is up, once more before it stops
for idleness if anything changed, and always right before something rewrites
data in bulk: integrating the sheet, overwriting the sheet, restoring. A version
can be compared with the present, restored, downloaded, or uploaded from outside.

Restoring brings back the register (documents, uploads, extraction jobs) and
leaves accounts, sessions and settings alone, so nobody is locked out by
restoring a version older than their account.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func

from .. import __version__
from ..config import Settings
from ..models import Document, ExtractionJob, Upload, User
from .sheets import (
    COLUMNS_BY_FIELD,
    COMPARED_FIELDS,
    REGISTER_COLUMNS,
    GoogleSheetsService,
    changed_fields,
    snapshot_values,
)
from .text_format import format_date, parse_date

logger = logging.getLogger(__name__)

PREFIX = "cosecre-backup-"
NAME_PATTERN = re.compile(rf"^{PREFIX}\d{{8}}T\d{{6}}(\d{{3}})?Z\.zip$")
#: Changes are backed up at most this often; quiet days get one daily backup.
MIN_GAP = timedelta(hours=1)
#: What a restore replaces, children first for deleting and parents first for inserting.
RESTORED_TABLES = ("extraction_jobs", "documents", "uploads")
#: Fingerprints and the register exports are expensive to rebuild; cache by name.
_MANIFESTS: dict[str, dict[str, Any]] = {}

KIND_LABELS = {
    "auto": "Automàtica",
    "manual": "Manual",
    "pre-pull": "Abans d'integrar el full",
    "pre-push": "Abans d'escriure al full",
    "pre-restore": "Abans de restaurar",
    "pre-migration": "Abans de la migració",
    "shutdown": "Abans d'aturar",
    "upload": "Pujada",
}


class BackupError(RuntimeError):
    """A backup operation refused or failed, with a message for a person."""


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class BackupInfo:
    name: str
    size: int
    created_at: datetime
    kind: str = "auto"
    reason: str = ""
    author: str | None = None
    documents: int | None = None
    #: Compared with the version before it: references added, removed, changed.
    added: int | None = None
    removed: int | None = None
    changed: int | None = None
    has_sheet: bool = False


@dataclass
class EntryDiff:
    reference: str
    status: str  # "only_in_backup" | "only_now" | "changed"
    num_factura: str = ""
    proveidor: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)


# ── Reading register entries out of a SQLite file ────────────────────────────


def _rows(db_path: Path, table: str) -> list[dict[str, Any]]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return []
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


def _entry_values(entry: dict[str, Any]) -> dict[str, Any]:
    """A stored row → comparable register values (dates arrive as strings)."""
    return snapshot_values({name: entry.get(name) for name in COMPARED_FIELDS})


def fingerprints(entries: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(entry["internal_doc_number"]): hashlib.sha1(
            json.dumps(_entry_values(entry), sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        for entry in entries
    }


def _validate_sqlite(path: Path) -> None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("La base de dades no supera la comprovació d'integritat.")
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise BackupError("El fitxer no és una base de dades SQLite vàlida.") from exc
    if "documents" not in tables:
        raise BackupError(
            "Aquesta base de dades no té el registre de documents (és d'abans del registre unificat)."
        )


class BackupService:
    def __init__(self, settings: Settings, session_factory, sheet_service: GoogleSheetsService):
        self.settings = settings
        self.session_factory = session_factory
        self.sheet_service = sheet_service
        self.directory: Path = settings.backup_dir  # type: ignore[assignment]
        self._lock = threading.RLock()
        self.last_error: str | None = None
        self.last_offsite_at: datetime | None = None

    # ── Listing ──────────────────────────────────────────────────────────────

    def _manifest(self, path: Path) -> dict[str, Any]:
        cached = _MANIFESTS.get(path.name)
        if cached is not None:
            return cached
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                manifest["_has_sheet"] = "full.json" in archive.namelist()
        except (KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            manifest = {}
        _MANIFESTS[path.name] = manifest
        return manifest

    def list(self) -> list[BackupInfo]:
        if not self.directory.exists():
            return []
        items = []
        for path in self.directory.glob(f"{PREFIX}*.zip"):
            if not NAME_PATTERN.match(path.name):
                continue
            stamp = path.name.removeprefix(PREFIX).removesuffix(".zip").rstrip("Z")
            created = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
            if len(stamp) > 15:
                created = created.replace(microsecond=int(stamp[15:]) * 1000)
            manifest = self._manifest(path)
            diff = manifest.get("since_previous") or {}
            items.append(BackupInfo(
                name=path.name,
                size=path.stat().st_size,
                created_at=created,
                kind=manifest.get("kind", "auto"),
                reason=manifest.get("reason", ""),
                author=manifest.get("author"),
                documents=manifest.get("documents"),
                added=diff.get("added"),
                removed=diff.get("removed"),
                changed=diff.get("changed"),
                has_sheet=bool(manifest.get("_has_sheet")),
            ))
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def path_for(self, name: str) -> Path | None:
        if not NAME_PATTERN.match(name):
            return None
        path = self.directory / name
        return path if path.is_file() else None

    @property
    def offsite_configured(self) -> bool:
        return bool(self.settings.google_drive_backup_folder_id and self.sheet_service.drive_ready)

    # ── Scheduling ───────────────────────────────────────────────────────────

    def last_change(self) -> datetime | None:
        with self.session_factory() as session:
            stamps = [
                session.query(func.max(model.updated_at)).scalar()
                for model in (Document, Upload, User)
            ]
        stamps = [s.replace(tzinfo=s.tzinfo or UTC) for s in stamps if s is not None]
        return max(stamps, default=None)

    def due(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        backups = self.list()
        if not backups:
            return True
        latest = backups[0].created_at
        if now - latest >= timedelta(hours=self.settings.backup_interval_hours):
            return True
        changed = self.last_change()
        return bool(changed and changed > latest and now - latest >= MIN_GAP)

    def changed_since_last(self) -> bool:
        backups = self.list()
        if not backups:
            return True
        changed = self.last_change()
        return bool(changed and changed > backups[0].created_at)

    # ── Taking one ───────────────────────────────────────────────────────────

    def create(
        self,
        reason: str,
        *,
        kind: str = "manual",
        author: str | None = None,
        sheet_rows: list[dict[str, Any]] | None = None,
        source_db: Path | None = None,
    ) -> BackupInfo:
        """Take a version. ``source_db`` packs an uploaded database instead of the live one."""
        with self._lock:
            try:
                info = self._create(reason, kind, author, sheet_rows, source_db)
                self.last_error = None
            except BackupError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("Backup failed")
                raise
        self._copy_offsite(info)
        return info

    def _unique_name(self) -> tuple[str, datetime]:
        now = utcnow()
        name = f"{PREFIX}{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z.zip"
        while (self.directory / name).exists():
            now += timedelta(milliseconds=1)
            name = f"{PREFIX}{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z.zip"
        return name, now

    def _create(self, reason, kind, author, sheet_rows, source_db) -> BackupInfo:
        self.directory.mkdir(parents=True, exist_ok=True)
        name, now = self._unique_name()
        target = self.directory / name
        partial = target.with_suffix(".zip.partial")
        previous = self.list()

        with tempfile.TemporaryDirectory() as scratch:
            snapshot = source_db or self._snapshot_sqlite(Path(scratch))
            if snapshot is not None:
                entries = _rows(snapshot, "documents")
            else:
                entries = self._export_from_session()
            prints = fingerprints(entries)
            manifest: dict[str, Any] = {
                "created_at": now.isoformat(),
                "kind": kind,
                "reason": reason,
                "author": author,
                "hub_version": __version__,
                "documents": len(entries),
                "fingerprints": prints,
            }
            if previous:
                before = self._manifest(self.directory / previous[0].name).get("fingerprints")
                if isinstance(before, dict):
                    manifest["since_previous"] = {
                        "added": len(prints.keys() - before.keys()),
                        "removed": len(before.keys() - prints.keys()),
                        "changed": sum(1 for k in prints.keys() & before.keys() if prints[k] != before[k]),
                    }
            if snapshot is not None:
                manifest["database_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()

            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                if snapshot is not None:
                    archive.write(snapshot, "cosecre.db")
                archive.writestr(
                    "registre.json", json.dumps(entries, ensure_ascii=False, indent=1, default=str)
                )
                archive.writestr("registre.csv", self._csv(entries))
                if sheet_rows is not None:
                    archive.writestr(
                        "full.json", json.dumps(sheet_rows, ensure_ascii=False, indent=1, default=str)
                    )
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
        with zipfile.ZipFile(partial) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("The backup archive failed its own check")
        partial.rename(target)
        _MANIFESTS.pop(name, None)
        self._prune_local()
        logger.info("Backup %s written (%s: %s)", name, kind, reason)
        return next(item for item in self.list() if item.name == name)

    def _snapshot_sqlite(self, scratch: Path) -> Path | None:
        source_path = self.settings.sqlite_path
        if source_path is None or not source_path.exists():
            return None
        destination = scratch / "cosecre.db"
        with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source:
            with sqlite3.connect(destination) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("The database snapshot failed its integrity check")
        return destination

    def _export_from_session(self) -> list[dict]:
        columns = [c.name for c in Document.__table__.columns]
        with self.session_factory() as session:
            rows = session.query(Document).order_by(Document.id).all()
            return [{name: getattr(row, name) for name in columns} for row in rows]

    def _csv(self, entries: list[dict]) -> str:
        buffer = io.StringIO()
        # BOM + semicolons: what Excel in a Catalan or Spanish locale opens cleanly.
        buffer.write("﻿")
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow([column.header for column in REGISTER_COLUMNS])
        for entry in entries:
            row = []
            for column in REGISTER_COLUMNS:
                key = "internal_doc_number" if column.field == "num_doc_intern" else column.field
                value = entry.get(key)
                if column.kind == "date":
                    value = format_date(parse_date(value))
                elif column.kind == "amount" and value not in (None, ""):
                    value = f"{float(value):.2f}".replace(".", ",")
                elif column.kind == "bool":
                    value = "TRUE" if value else "FALSE"
                row.append("" if value is None else value)
            writer.writerow(row)
        return buffer.getvalue()

    def _prune_local(self) -> None:
        for stale in self.list()[self.settings.backup_keep :]:
            (self.directory / stale.name).unlink(missing_ok=True)
            _MANIFESTS.pop(stale.name, None)

    def _copy_offsite(self, info: BackupInfo) -> None:
        if not self.offsite_configured:
            return
        folder_id = self.settings.google_drive_backup_folder_id
        try:
            self.sheet_service.upload_private_file(
                self.directory / info.name, info.name, "application/zip", folder_id  # type: ignore[arg-type]
            )
            remote = self.sheet_service.list_drive_files(folder_id, PREFIX)  # type: ignore[arg-type]
            for stale in remote[self.settings.backup_keep :]:
                self.sheet_service.delete_drive_file(stale["id"])
            self.last_offsite_at = utcnow()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"Còpia a Drive fallida: {exc}"
            logger.warning("Could not copy backup %s to Drive", info.name, exc_info=True)

    # ── Comparing and restoring ──────────────────────────────────────────────

    def _extract_db(self, name: str, scratch: Path) -> Path:
        path = self.path_for(name)
        if path is None:
            raise BackupError("No s'ha trobat la còpia.")
        with zipfile.ZipFile(path) as archive:
            if "cosecre.db" not in archive.namelist():
                raise BackupError("Aquesta còpia no conté la base de dades.")
            destination = scratch / "snapshot.db"
            with archive.open("cosecre.db") as source, destination.open("wb") as sink:
                shutil.copyfileobj(source, sink)
        return destination

    def compare(self, name: str) -> list[EntryDiff]:
        """What restoring this version would change, entry by entry and field by field."""
        with tempfile.TemporaryDirectory() as scratch:
            then = {str(e["internal_doc_number"]): e for e in _rows(self._extract_db(name, Path(scratch)), "documents")}
        now = {str(e["internal_doc_number"]): e for e in self._export_from_session()}
        diffs: list[EntryDiff] = []
        for reference in sorted(then.keys() | now.keys()):
            old, new = then.get(reference), now.get(reference)
            source = old or new or {}
            entry = EntryDiff(
                reference=reference,
                status="only_in_backup" if new is None else "only_now" if old is None else "changed",
                num_factura=str(source.get("num_factura") or ""),
                proveidor=str(source.get("proveidor") or ""),
            )
            if old is not None and new is not None:
                a, b = _entry_values(old), _entry_values(new)
                fields = changed_fields(a, b)
                if not fields:
                    continue
                entry.changes = [
                    {"field": f, "label": COLUMNS_BY_FIELD[f].header, "backup": a[f], "now": b[f]}
                    for f in fields
                ]
            diffs.append(entry)
        return diffs

    def restore(self, name: str, *, author: str | None, busy: bool) -> dict[str, Any]:
        """Bring back the register as it was in ``name``. Takes a version of the present first."""
        live = self.settings.sqlite_path
        if live is None:
            raise BackupError("Restaurar només és possible amb SQLite.")
        if busy:
            raise BackupError(
                "Hi ha documents llegint-se ara mateix. Espera que acabin i torna-ho a provar."
            )
        with self._lock, tempfile.TemporaryDirectory() as scratch:
            snapshot = self._extract_db(name, Path(scratch))
            _validate_sqlite(snapshot)
            safety = self.create(f"abans de restaurar {name}", kind="pre-restore", author=author)
            restored = 0
            with sqlite3.connect(live, timeout=30) as connection:
                connection.execute("ATTACH DATABASE ? AS snap", (str(snapshot),))
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    for table in RESTORED_TABLES:
                        connection.execute(f"DELETE FROM main.{table}")
                    for table in reversed(RESTORED_TABLES):
                        mine = [r[1] for r in connection.execute(f"PRAGMA main.table_info({table})")]
                        theirs = {r[1] for r in connection.execute(f"PRAGMA snap.table_info({table})")}
                        columns = ", ".join(c for c in mine if c in theirs)
                        if not columns:
                            continue
                        cursor = connection.execute(
                            f"INSERT INTO main.{table} ({columns}) SELECT {columns} FROM snap.{table}"
                        )
                        if table == "documents":
                            restored = cursor.rowcount
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.execute("DETACH DATABASE snap")
        logger.warning("Register restored from %s by %s (%d documents)", name, author, restored)
        return {"restored": restored, "safety_backup": safety.name}

    def import_file(self, upload: Path, filename: str, *, author: str | None) -> BackupInfo:
        """Accept a backup zip or a bare SQLite file from outside as a new version."""
        with tempfile.TemporaryDirectory() as scratch:
            database = Path(scratch) / "uploaded.db"
            if zipfile.is_zipfile(upload):
                with zipfile.ZipFile(upload) as archive:
                    if "cosecre.db" not in archive.namelist():
                        raise BackupError("El zip no conté cap «cosecre.db».")
                    with archive.open("cosecre.db") as source, database.open("wb") as sink:
                        shutil.copyfileobj(source, sink)
            else:
                shutil.copyfile(upload, database)
            _validate_sqlite(database)
            return self.create(f"pujada: {filename}", kind="upload", author=author, source_db=database)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def run_if_due(self) -> None:
        try:
            if self.due():
                self.create("diària", kind="auto")
        except Exception:  # noqa: BLE001
            pass  # already logged; the next check tries again

    def before_shutdown(self) -> None:
        try:
            if self.changed_since_last():
                self.create("abans d'aturar el servidor", kind="shutdown")
        except Exception:  # noqa: BLE001
            pass


def info_dict(info: BackupInfo) -> dict[str, Any]:
    data = asdict(info)
    data["kind_label"] = KIND_LABELS.get(info.kind, info.kind)
    return data


def busy(session_factory, enrichment_running: bool) -> bool:
    if enrichment_running:
        return True
    with session_factory() as session:
        return session.query(ExtractionJob.id).filter(
            ExtractionJob.status.in_(["pending", "processing", "written_to_sheet"])
        ).first() is not None
