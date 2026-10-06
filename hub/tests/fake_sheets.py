"""An in-memory stand-in for Google Sheets and Drive.

It subclasses the real service and replaces only the methods that talk to
Google, so the register logic under test is exactly what runs in production.
Rows behave like a sheet's: deleting one shifts the ones below it up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cosecre_hub.services.sheets import (
    has_substance,
    REGISTER_COLUMNS,
    GoogleSheetsService,
    LegacyTab,
    RegisterLayout,
    SheetDocumentNotFound,
    SheetRow,
)


class FakeSheets(GoogleSheetsService):
    def __init__(self, settings=None):
        self._lock = __import__("threading").RLock()
        self.settings = settings
        self.ready = True
        self.fail_writes = False
        self.rows: dict[int, dict[str, Any]] = {}
        self.legacy: dict[str, LegacyTab] = {}
        self.legacy_references: list[tuple[str, int, str]] = []
        self.drive: dict[str, dict[str, Any]] = {}
        #: Files in Drive's bin, which an undo can bring back.
        self.trash: dict[str, dict[str, Any]] = {}
        self.uploads = 0
        #: Tab title → rows, for ``read_tabs`` (the caixeta).
        self.tabs: dict[str, list[list[Any]]] = {}
        self.tab_reads = 0
        #: The statements mirror: tab title → grid (header first), as Sheets
        #: reads it back unformatted; and each written row's tone.
        self.mirror: dict[str, list[list[Any]]] = {}
        self.mirror_tones: dict[str, list[str]] = {}
        self.mirror_writes = 0

    # ── Register ─────────────────────────────────────────────────────────────

    def is_ready(self, workspace) -> bool:
        return self.ready

    @property
    def drive_ready(self) -> bool:
        return True

    def close(self):
        pass

    def register_layout(self, workspace, *, fresh: bool = False) -> RegisterLayout:
        return RegisterLayout("fake", 1, "Registre", {c.field: i for i, c in enumerate(REGISTER_COLUMNS)}, len(REGISTER_COLUMNS), 1000)

    def read_register(self, workspace) -> list[SheetRow]:
        # Like the real sheet: a row is read when it says something, or carries a code.
        return [
            SheetRow(n, dict(values)) for n, values in sorted(self.rows.items())
            if has_substance(values) or values.get("num_doc_intern")
        ]

    def write_row(self, workspace, row_number: int, values: dict[str, Any]) -> int:
        if self.fail_writes:
            raise RuntimeError("Google is down")
        self.rows[row_number] = {**self.rows.get(row_number, {}), **values}
        return row_number

    def append_row(self, workspace, values):
        return self.write_row(workspace, max(self.rows, default=1) + 1, values)

    def append_rows(self, workspace, rows):
        return [self.append_row(workspace, values) for values in rows]

    def write_cells(self, workspace, updates):
        for row_number, values in updates:
            self.rows[row_number].update(values)

    def find_row(self, workspace, internal_doc_number: str) -> int:
        for n, values in self.rows.items():
            if values.get("num_doc_intern") == internal_doc_number:
                return n
        raise SheetDocumentNotFound(internal_doc_number)

    def delete_row(self, workspace, row_number: int) -> None:
        del self.rows[row_number]
        self.rows = {(n - 1 if n > row_number else n): v for n, v in sorted(self.rows.items())}

    def row_for(self, reference: str) -> dict[str, Any]:
        return self.rows[self.find_row(None, reference)]

    # ── Legacy tabs ──────────────────────────────────────────────────────────

    def read_legacy_tab(self, workspace, title):
        return self.legacy.get(title)

    def write_legacy_references(self, workspace, tab, references):
        for row_number, reference in references:
            self.legacy_references.append((tab.title, row_number, reference))
            for row in tab.rows:
                if row.row_number == row_number:
                    row.values["num_doc_intern"] = reference

    # ── Drive ────────────────────────────────────────────────────────────────

    def upload_file_to_drive(self, file_path: Path, filename, mime_type, folder_id=None):
        self.uploads += 1
        file_id = f"drive-file-{self.uploads:04d}"
        self.drive[file_id] = {"name": filename, "folder": folder_id, "bytes": Path(file_path).read_bytes()}
        return f"https://drive.example/{file_id}", file_id

    def drive_name_taken(self, folder_id, name, *, except_id=None):
        return any(f["name"] == name and i != except_id for i, f in self.drive.items())

    def update_drive_file(self, file_id, *, name=None, folder_id=None):
        if name:
            self.drive[file_id]["name"] = name
        if folder_id:
            self.drive[file_id]["folder"] = folder_id

    def download_drive_file(self, file_id, destination: Path) -> str:
        destination.write_bytes(self.drive[file_id]["bytes"])
        return "image/jpeg"

    def delete_drive_file(self, file_id):
        self.drive.pop(file_id, None)

    def trash_drive_file(self, file_id, *, trashed=True):
        source, target = (self.drive, self.trash) if trashed else (self.trash, self.drive)
        if file_id in source:
            target[file_id] = source.pop(file_id)

    def list_drive_files(self, folder_id, prefix):
        return []

    def upload_private_file(self, file_path, filename, mime_type, folder_id):
        return "backup-id"

    # ── Other spreadsheets ───────────────────────────────────────────────────

    # ── Statements mirror ───────────────────────────────────────────────────

    def read_mirror(self, workspace, titles):
        if self.fail_writes:
            raise RuntimeError("Google is down")
        return {t: [list(r) for r in self.mirror[t]] for t in titles if t in self.mirror}

    def write_mirror(self, workspace, tabs):
        from datetime import date

        from cosecre_hub.services.text_format import to_sheets_serial

        if self.fail_writes:
            raise RuntimeError("Google is down")
        self.mirror_writes += 1
        for tab in tabs:
            def plain(value):
                if isinstance(value, date):
                    return to_sheets_serial(value)
                return "" if value is None else value
            self.mirror[tab.title] = [list(tab.headers)] + [[plain(v) for v in row] for row in tab.rows]
            self.mirror_tones[tab.title] = list(tab.tones)

    def set_mirror_cell(self, title: str, codi: str, header: str, value: Any) -> None:
        """A person typing in the sheet."""
        grid = self.mirror[title]
        column = grid[0].index(header)
        row = next(r for r in grid[1:] if r[0] == codi)
        row[column] = value

    def mirror_cell(self, title: str, codi: str, header: str) -> Any:
        grid = self.mirror[title]
        return next(r for r in grid[1:] if r[0] == codi)[grid[0].index(header)]

    def read_tabs(self, spreadsheet_id, pattern):
        import re

        self.tab_reads += 1
        return {t: [list(r) for r in rows] for t, rows in self.tabs.items() if re.fullmatch(pattern, t)}
