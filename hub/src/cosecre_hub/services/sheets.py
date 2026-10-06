"""Google Sheets and Drive for the accounting register.

The database holds the register; the spreadsheet is where people read and edit
it. Two rules keep the two honest:

* **Typed writes.** Every cell is written with ``updateCells`` as a string,
  number, date serial, boolean or formula — never as text for Sheets to parse.
  "1/2" stays an invoice number instead of becoming the 1st of February, a
  postcode keeps its leading zero, and dates are ``dd/mm/yyyy`` whatever the
  spreadsheet's locale is.
* **Known columns only.** Columns are found by header, and only those cells are
  touched. Someone can add, reorder or rename-by-case columns, and add their
  own, without the sync noticing or overwriting them.
"""

from __future__ import annotations

import io
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlparse

from ..config import Settings
from ..models import WorkspaceSetting
from ..schemas.documents import CHOICES, canonical_choice
from .text_format import parse_amount, parse_date, to_sheets_serial

logger = logging.getLogger(__name__)


def build(*args, **kwargs):
    # Google discovery is only needed for sheet/drive operations, not startup.
    from googleapiclient.discovery import build as google_build

    return google_build(*args, **kwargs)


ColumnKind = Literal["text", "choice", "date", "amount", "bool", "file"]


@dataclass(frozen=True, slots=True)
class Column:
    field: str
    header: str
    kind: ColumnKind = "text"
    width: int = 140
    #: Earlier headers of this column; an existing sheet is relabelled in place.
    aliases: tuple[str, ...] = ()
    hidden: bool = False


#: The register, in the order a new tab is laid out.
REGISTER_COLUMNS: tuple[Column, ...] = (
    # The sync key: still written, but hidden — people don't need to see it.
    Column("num_doc_intern", "Núm. doc. intern", width=170, hidden=True),
    Column("tipus_document", "Tipus document", "choice", 150),
    Column("origen", "Foto o original", "choice", 110),
    Column("num_factura", "Núm. factura"),
    Column("data_factura", "Data factura", "date", 100),
    Column("proveidor", "Proveïdor/a", width=220),
    Column("cif_proveidor", "CIF proveïdor", width=110),
    Column("carrer", "Carrer i núm.", width=200),
    Column("codi_postal", "Codi postal", width=90),
    Column("ciutat", "Ciutat"),
    Column("compte_corrent", "Compte corrent", width=230),
    Column("cif_proveit", "CIF proveït", width=110),
    Column("import_value", "Import", "amount", 100),
    Column("descripcio", "Descripció", width=280),
    Column("descripcio_compra", "Descripció de la compra/servei", width=280),
    Column("pagament", "Pagament", "choice", 160),
    Column("pagament_observacions", "Pagament (altres)", width=180),
    Column("metode_pagament", "Mètode de pagament", "choice", 180),
    Column("data_pagament", "Data de pagament", "date", 110),
    Column("subministrat", "Subministrat", "choice", 130),
    Column("pressupost_afectat", "Compte", "choice", 170, aliases=("Pressupost afectat",)),
    Column("responsable_nom", "Responsable", width=180),
    Column("responsable_email", "Email responsable", width=200),
    Column("file_link", "Fitxer", "file", 120),
    Column("validat", "Validat", "bool", 80),
)
COLUMNS_BY_FIELD = {column.field: column for column in REGISTER_COLUMNS}

#: Headers of the two tabs the register replaced, for the migration.
LEGACY_HEADERS = {
    "num_factura": "Núm. de la factura",
    "data_factura": "Data factura",
    "proveidor": "Proveïdor/a",
    "cif_proveidor": "CIF Proveïdor",
    "adreca_proveidor": "Adreça Proveïdor",
    "import_value": "Import",
    "cif_proveit": "CIF Proveït",
    "descripcio": "Descripció",
    "pressupost_afectat": "Pressupost afectat",
    "num_doc_intern": "Núm. de doc. intern",
    "file_link": "Fitxer",
    "validat": "Validat",
}

#: Full Drive, not ``drive.file``: the latter only reaches files this app
#: created, so a folder someone shares with the service account stays invisible.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_PENDING_COLOUR = {"red": 1.0, "green": 0.95, "blue": 0.8}
_DONE_COLOUR = {"red": 1.0, "green": 1.0, "blue": 1.0}
#: A row a confirmed statement movement pays: justified, whatever else it says.
_JUSTIFIED_COLOUR = {"red": 0.85, "green": 0.94, "blue": 0.83}
_HEADER_COLOUR = {"red": 0.95, "green": 0.94, "blue": 0.92}
_LAYOUT_TTL_SECONDS = 60

#: Not a column: a flag in a row's values that only picks its colour.
JUSTIFIED_KEY = "justificat"

#: Row tones of the statements mirror: a justified line, and a payment whose
#: invoice cells are still empty.
_MIRROR_TONES = {"justified": _JUSTIFIED_COLOUR, "pending": _PENDING_COLOUR}


@dataclass(slots=True)
class MirrorTabData:
    """One statements tab to write. ``kinds``: ``text``, ``date`` or ``money`` per column."""

    title: str
    headers: list[str]
    kinds: list[str]
    widths: tuple[int, ...]
    #: Leading columns that get a warning-only protection when the tab is created.
    protected_columns: int
    rows: list[list[Any]]
    tones: list[str]


class SheetDocumentNotFound(RuntimeError):
    """A successful sheet read did not find this document's reference."""


@dataclass
class RegisterLayout:
    spreadsheet_id: str
    sheet_id: int
    title: str
    #: field → zero-based column index, for the register columns present.
    columns: dict[str, int]
    width: int
    row_count: int
    loaded_at: float = field(default_factory=time.monotonic)


@dataclass
class SheetRow:
    row_number: int
    values: dict[str, Any]


@dataclass
class LegacyTab:
    title: str
    rows: list[SheetRow]
    #: Zero-based column of "Núm. de doc. intern", where the migration writes
    #: back the references it had to generate, so a second run skips those rows.
    reference_column: int | None


def parse_spreadsheet_id(spreadsheet_url: str) -> str:
    if "/spreadsheets/d/" in spreadsheet_url:
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", spreadsheet_url)
        if match:
            return match.group(1)
    parsed = urlparse(spreadsheet_url)
    if parsed.scheme or parsed.netloc:
        raise ValueError("No s'ha pogut llegir l'identificador del full a partir de l'URL.")
    return spreadsheet_url


def column_letter(column_number: int) -> str:
    result = []
    current = column_number
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def quote_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def fold_header(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text).lower())
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", bare).strip()


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "si", "sí", "x", "verdadero", "cert"}


def drive_file_id_from_link(link: str) -> str | None:
    """Recover a Drive id from an ``=IMAGE(...)`` formula or a Drive URL."""
    if not link:
        return None
    match = re.search(r"[?&]id=([\w-]{10,})", link) or re.search(r"/d/([\w-]{10,})", link)
    return match.group(1) if match else None


def file_cell(drive_file_id: str, mime_type: str | None) -> str:
    """What the "Fitxer" column shows: the photo itself, or a link to a PDF."""
    if mime_type and mime_type.startswith("image/"):
        return f'=IMAGE("https://drive.google.com/uc?export=view&id={drive_file_id}")'
    return f"https://drive.google.com/file/d/{drive_file_id}/view"


def cell_to_value(kind: ColumnKind, field_name: str, raw: Any) -> Any:
    """A cell as read with ``FORMULA`` + ``SERIAL_NUMBER`` → the stored value."""
    if kind == "bool":
        return parse_bool(raw) if raw not in (None, "") else False
    # A checkbox in a column that is not one (a table can type a whole column
    # that way) says nothing: unticked, it would read as "False" — or as 0 €.
    if isinstance(raw, bool):
        raw = None
    if kind == "date":
        return parse_date(raw)
    if kind == "amount":
        return parse_amount(raw)
    if raw is None:
        return ""
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    text = str(raw).strip()
    if field_name == "codi_postal" and text.isdigit() and len(text) < 5:
        text = text.zfill(5)  # typed by hand as a number, lost its zero
    if kind == "choice":
        return canonical_choice(field_name, text)
    return text


def value_to_cell(kind: ColumnKind, value: Any) -> dict[str, Any]:
    """A stored value → ``CellData``. An empty dict clears the cell."""
    if kind == "date":
        if not isinstance(value, date):
            return {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}}
        return {
            "userEnteredValue": {"numberValue": to_sheets_serial(value)},
            "userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}},
        }
    if kind == "amount":
        amount = parse_amount(value)
        if amount is None:
            return {}
        return {
            "userEnteredValue": {"numberValue": amount},
            "userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00 €"}},
        }
    if kind == "bool":
        return {"userEnteredValue": {"boolValue": bool(value)}}
    text = "" if value is None else str(value)
    if not text:
        return {}
    if kind == "file" and text.startswith("="):
        return {"userEnteredValue": {"formulaValue": text}}
    return {
        "userEnteredValue": {"stringValue": text},
        "userEnteredFormat": {"numberFormat": {"type": "TEXT"}},
    }


def row_colour(values: dict[str, Any]) -> dict[str, float]:
    """Green once justified by a statement, white once validated, else pending."""
    if values.get(JUSTIFIED_KEY):
        return _JUSTIFIED_COLOUR
    return _DONE_COLOUR if values.get("validat") else _PENDING_COLOUR


def serialized(method):
    """Reuse Google transports safely; httplib2 clients are not thread-safe.

    Lock the whole operation, including nested reads, so appends cannot select
    the same empty row. RLock lets those nested calls reuse the same clients.
    """

    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


class GoogleSheetsService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = RLock()
        self._clients: dict[str, Any] = {}
        self._resources: dict[str, Any] = {}
        self._layouts: dict[tuple[str, str], RegisterLayout] = {}

    @serialized
    def close(self):
        for client in self._clients.values():
            client.close()
        self._resources.clear()
        self._clients.clear()

    # ── Clients ──────────────────────────────────────────────────────────────

    def is_ready(self, workspace: WorkspaceSetting) -> bool:
        return bool(
            workspace.spreadsheet_url
            and workspace.registry_sheet_name
            and self.settings.google_service_account_file
        )

    @property
    def drive_ready(self) -> bool:
        return self.settings.google_service_account_file is not None

    def _credentials(self):
        if self.settings.google_service_account_file is None:
            raise RuntimeError("Google service account file is not configured.")
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(
            self.settings.google_service_account_file,
            scopes=SCOPES,
        )

    def _service(self):
        if "sheets" not in self._clients:
            self._clients["sheets"] = build(
                "sheets", "v4", credentials=self._credentials(), cache_discovery=False
            )
        return self._clients["sheets"]

    def _drive_service(self):
        if "drive" not in self._clients:
            self._clients["drive"] = build(
                "drive", "v3", credentials=self._credentials(), cache_discovery=False
            )
        return self._clients["drive"]

    def _spreadsheets(self):
        if "spreadsheets" not in self._resources:
            self._resources["spreadsheets"] = self._service().spreadsheets()
        return self._resources["spreadsheets"]

    def _values(self):
        # Nested discovery resources also build method/schema graphs. Reusing
        # only the root client still creates megabytes of cycles per poll.
        if "values" not in self._resources:
            self._resources["values"] = self._spreadsheets().values()
        return self._resources["values"]

    def _files(self):
        if "files" not in self._resources:
            self._resources["files"] = self._drive_service().files()
        return self._resources["files"]

    def _permissions(self):
        if "permissions" not in self._resources:
            self._resources["permissions"] = self._drive_service().permissions()
        return self._resources["permissions"]

    def _spreadsheet_id(self, workspace: WorkspaceSetting) -> str:
        if workspace.spreadsheet_id:
            return workspace.spreadsheet_id
        if not workspace.spreadsheet_url:
            raise RuntimeError("Spreadsheet URL is not configured.")
        return parse_spreadsheet_id(workspace.spreadsheet_url)

    def _batch(self, spreadsheet_id: str, requests: list[dict[str, Any]]) -> None:
        if requests:
            self._spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": requests}
            ).execute()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _tabs(self, spreadsheet_id: str) -> list[dict[str, Any]]:
        metadata = (
            self._spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties))",
            )
            .execute()
        )
        return [sheet.get("properties", {}) for sheet in metadata.get("sheets", [])]

    @serialized
    def register_layout(self, workspace: WorkspaceSetting, *, fresh: bool = False) -> RegisterLayout:
        """Find (or create) the register tab and map its columns.

        Missing register headers are appended at the right, never inserted, so
        nothing a person placed in the sheet moves.
        """
        spreadsheet_id = self._spreadsheet_id(workspace)
        title = workspace.registry_sheet_name
        key = (spreadsheet_id, fold_header(title))
        cached = self._layouts.get(key)
        if cached and not fresh and time.monotonic() - cached.loaded_at < _LAYOUT_TTL_SECONDS:
            return cached

        tab = next(
            (t for t in self._tabs(spreadsheet_id) if fold_header(t.get("title", "")) == key[1]),
            None,
        )
        if tab is None:
            layout = self._create_register(spreadsheet_id, title)
        else:
            layout = self._map_register(spreadsheet_id, tab)
        self._layouts[key] = layout
        return layout

    def _map_register(self, spreadsheet_id: str, tab: dict[str, Any]) -> RegisterLayout:
        title = tab["title"]
        grid = tab.get("gridProperties", {})
        response = (
            self._values()
            .get(spreadsheetId=spreadsheet_id, range=f"{quote_title(title)}!1:1")
            .execute()
        )
        headers = (response.get("values") or [[]])[0]
        by_header = {fold_header(header): index for index, header in enumerate(headers) if header}
        columns: dict[str, int] = {}
        missing: list[Column] = []
        upgrades: list[dict[str, Any]] = []
        dropdowns: list[tuple[int, Column]] = []
        for column in REGISTER_COLUMNS:
            index = by_header.get(fold_header(column.header))
            if index is None:
                index = next(
                    (by_header[fold_header(a)] for a in column.aliases if fold_header(a) in by_header),
                    None,
                )
                if index is not None:
                    # A renamed column: relabel it and give it its current rules.
                    upgrades.append(self._rename_request(tab["sheetId"], index, column.header))
                    dropdowns.append((index, column))
            if index is None:
                missing.append(column)
            else:
                columns[column.field] = index
        if upgrades:
            # The same one-off upgrade hides the columns that are now hidden.
            for column in REGISTER_COLUMNS:
                if column.hidden and column.field in columns:
                    upgrades.append(self._hide_request(tab["sheetId"], columns[column.field]))
            try:
                self._batch(spreadsheet_id, upgrades)
            except Exception:  # noqa: BLE001 — a cosmetic upgrade never blocks reading
                logger.warning("Could not relabel the register's renamed columns", exc_info=True)
            for index, column in dropdowns:
                self._add_dropdown(spreadsheet_id, int(tab["sheetId"]), index, column)

        width = max(len(headers), int(grid.get("columnCount", 26)))
        if missing:
            start = len(headers)
            needed = start + len(missing)
            requests: list[dict[str, Any]] = []
            if needed > int(grid.get("columnCount", 26)):
                requests.append(
                    {
                        "appendDimension": {
                            "sheetId": tab["sheetId"],
                            "dimension": "COLUMNS",
                            "length": needed - int(grid.get("columnCount", 26)),
                        }
                    }
                )
            requests.append(
                self._header_request(tab["sheetId"], start, [c.header for c in missing])
            )
            self._batch(spreadsheet_id, requests)
            for offset, column in enumerate(missing):
                columns[column.field] = start + offset
            width = max(width, needed)

        return RegisterLayout(
            spreadsheet_id=spreadsheet_id,
            sheet_id=int(tab["sheetId"]),
            title=title,
            columns=columns,
            width=width,
            row_count=int(grid.get("rowCount", 1000)),
        )

    def _header_request(self, sheet_id: int, start: int, headers: list[str]) -> dict[str, Any]:
        return {
            "updateCells": {
                "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": start},
                "rows": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {"stringValue": header},
                                "userEnteredFormat": {
                                    "textFormat": {"bold": True},
                                    "backgroundColor": _HEADER_COLOUR,
                                },
                            }
                            for header in headers
                        ]
                    }
                ],
                "fields": "userEnteredValue,userEnteredFormat(textFormat,backgroundColor)",
            }
        }

    def _column_rules(self, sheet_id: int, index: int, column: Column) -> list[dict[str, Any]]:
        """The dropdown or checkbox under a column's header."""
        body_range = {
            "sheetId": sheet_id,
            "startRowIndex": 1,
            "startColumnIndex": index,
            "endColumnIndex": index + 1,
        }
        if column.kind == "choice":
            condition = {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": option} for option in CHOICES[column.field]],
            }
            # A warning, not a rejection: the sheet stays usable for the odd
            # case nobody foresaw.
            rule = {"condition": condition, "strict": False, "showCustomUi": True}
        elif column.kind == "bool":
            rule = {"condition": {"type": "BOOLEAN"}}
        else:
            return []
        return [{"setDataValidation": {"range": body_range, "rule": rule}}]

    def _rename_request(self, sheet_id: int, index: int, header: str) -> dict[str, Any]:
        """Only the value: a header inside a table keeps the table's own styling."""
        return {
            "updateCells": {
                "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": index},
                "rows": [{"values": [{"userEnteredValue": {"stringValue": header}}]}],
                "fields": "userEnteredValue",
            }
        }

    def _add_dropdown(self, spreadsheet_id: str, sheet_id: int, index: int, column: Column) -> None:
        """Best effort: a missing dropdown must never stop the sheet being read.

        Plain cells take a validation rule; a column inside a table refuses one
        ("typed columns") and has to become a dropdown-typed table column instead.
        """
        try:
            self._batch(spreadsheet_id, self._column_rules(sheet_id, index, column))
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            request = self._table_dropdown_request(spreadsheet_id, sheet_id, index, column)
            if request is None:
                raise RuntimeError("the column is in no table")
            self._batch(spreadsheet_id, [request])
        except Exception:  # noqa: BLE001
            logger.warning("Could not add the %s dropdown to the sheet", column.header, exc_info=True)

    def _table_dropdown_request(
        self, spreadsheet_id: str, sheet_id: int, index: int, column: Column
    ) -> dict[str, Any] | None:
        metadata = (
            self._spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId),tables)")
            .execute()
        )
        for sheet in metadata.get("sheets", []):
            if int(sheet.get("properties", {}).get("sheetId", -1)) != sheet_id:
                continue
            for table in sheet.get("tables", []):
                span = table.get("range", {})
                start = int(span.get("startColumnIndex", 0))
                if not start <= index < int(span.get("endColumnIndex", 0)):
                    continue
                offset = index - start
                # ``fields: columnProperties`` replaces the whole list, so every
                # other column is sent back exactly as it was.
                properties = [
                    p for p in table.get("columnProperties", [])
                    if int(p.get("columnIndex", 0)) != offset
                ]
                properties.append(
                    {
                        "columnIndex": offset,
                        "columnName": column.header,
                        "columnType": "DROPDOWN",
                        "dataValidationRule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": o} for o in CHOICES[column.field]
                                ],
                            }
                        },
                    }
                )
                properties.sort(key=lambda p: int(p.get("columnIndex", 0)))
                return {
                    "updateTable": {
                        "table": {"tableId": table["tableId"], "columnProperties": properties},
                        "fields": "columnProperties",
                    }
                }
        return None

    def _hide_request(self, sheet_id: int, index: int) -> dict[str, Any]:
        return {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": index,
                    "endIndex": index + 1,
                },
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        }

    def _create_register(self, spreadsheet_id: str, title: str) -> RegisterLayout:
        """A new tab with headers, column formats and dropdowns already in place."""
        width = len(REGISTER_COLUMNS)
        reply = (
            self._spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": title,
                                    "index": 0,
                                    "gridProperties": {
                                        "rowCount": 1000,
                                        "columnCount": width,
                                        "frozenRowCount": 1,
                                    },
                                }
                            }
                        }
                    ]
                },
            )
            .execute()
        )
        sheet_id = int(reply["replies"][0]["addSheet"]["properties"]["sheetId"])
        requests: list[dict[str, Any]] = [
            self._header_request(sheet_id, 0, [c.header for c in REGISTER_COLUMNS])
        ]
        for index, column in enumerate(REGISTER_COLUMNS):
            body_range = {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "startColumnIndex": index,
                "endColumnIndex": index + 1,
            }
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": index,
                            "endIndex": index + 1,
                        },
                        "properties": {"pixelSize": column.width},
                        "fields": "pixelSize",
                    }
                }
            )
            fmt = value_to_cell(column.kind, None).get("userEnteredFormat")
            if column.kind in {"text", "choice"}:
                fmt = {"numberFormat": {"type": "TEXT"}}
            elif column.kind == "amount":
                fmt = {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00 €"}}
            if fmt:
                requests.append(
                    {
                        "repeatCell": {
                            "range": body_range,
                            "cell": {"userEnteredFormat": fmt},
                            "fields": "userEnteredFormat.numberFormat",
                        }
                    }
                )
            requests.extend(self._column_rules(sheet_id, index, column))
            if column.hidden:
                requests.append(self._hide_request(sheet_id, index))
        self._batch(spreadsheet_id, requests)
        return RegisterLayout(
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
            title=title,
            columns={column.field: index for index, column in enumerate(REGISTER_COLUMNS)},
            width=width,
            row_count=1000,
        )

    # ── Register rows ────────────────────────────────────────────────────────

    def _read_grid(self, spreadsheet_id: str, title: str, width: int) -> list[list[Any]]:
        response = (
            self._values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"{quote_title(title)}!A1:{column_letter(width)}",
                # FORMULA keeps the `=IMAGE(...)` in "Fitxer"; SERIAL_NUMBER
                # makes dates locale-proof.
                valueRenderOption="FORMULA",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
        return response.get("values", [])

    @serialized
    def read_tabs(self, spreadsheet_id: str, pattern: str) -> dict[str, list[list[Any]]]:
        """Every tab whose title matches ``pattern``, as raw values, in one read.

        Unformatted, with dates as serials: "-6,00 €" arrives as ``-6.0`` and a
        date as a number, whatever the spreadsheet's locale.
        """
        titles = [
            t["title"] for t in self._tabs(spreadsheet_id) if re.fullmatch(pattern, t.get("title", ""))
        ]
        if not titles:
            return {}
        response = (
            self._values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=[f"{quote_title(title)}!A1:Z" for title in titles],
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
        ranges = response.get("valueRanges", [])
        return {title: (ranges[i].get("values", []) if i < len(ranges) else []) for i, title in enumerate(titles)}

    # ── Statements mirror ────────────────────────────────────────────────────

    @serialized
    def read_mirror(self, workspace: WorkspaceSetting, titles: list[str]) -> dict[str, list[list[Any]]]:
        """The named tabs of the register's spreadsheet, unformatted; missing ones left out."""
        spreadsheet_id = self._spreadsheet_id(workspace)
        existing = {t.get("title", "") for t in self._tabs(spreadsheet_id)}
        wanted = [title for title in titles if title in existing]
        if not wanted:
            return {}
        response = (
            self._values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=[f"{quote_title(title)}!A1:Z" for title in wanted],
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
        ranges = response.get("valueRanges", [])
        return {title: (ranges[i].get("values", []) if i < len(ranges) else []) for i, title in enumerate(wanted)}

    @serialized
    def write_mirror(self, workspace: WorkspaceSetting, tabs: list[MirrorTabData]) -> None:
        """Rewrite each tab whole: header, every line, and the colour of each row.

        One batch for all of them. A tab is created the first time, with its
        widths and a warning on the bank's columns; after that its widths and
        anything a person formatted outside the written range are left alone.
        The grid is resized to the lines, so a line that went away goes too.
        """
        if not tabs:
            return
        spreadsheet_id = self._spreadsheet_id(workspace)
        existing = {t.get("title", ""): t for t in self._tabs(spreadsheet_id)}
        requests: list[dict[str, Any]] = []

        missing = [tab for tab in tabs if tab.title not in existing]
        if missing:
            reply = (
                self._spreadsheets()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"requests": [{"addSheet": {"properties": {"title": tab.title}}} for tab in missing]},
                )
                .execute()
            )
            for tab, answer in zip(missing, reply.get("replies", []), strict=False):
                properties = answer["addSheet"]["properties"]
                existing[tab.title] = properties
                sheet_id = int(properties["sheetId"])
                for index, width in enumerate(tab.widths):
                    requests.append({
                        "updateDimensionProperties": {
                            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": index, "endIndex": index + 1},
                            "properties": {"pixelSize": width},
                            "fields": "pixelSize",
                        }
                    })
                if tab.protected_columns:
                    requests.append({
                        "addProtectedRange": {
                            "protectedRange": {
                                "range": {"sheetId": sheet_id, "startColumnIndex": 0, "endColumnIndex": tab.protected_columns},
                                "description": "Dades del banc: les escriu Cosecre a cada sincronització.",
                                "warningOnly": True,
                            }
                        }
                    })

        for tab in tabs:
            sheet_id = int(existing[tab.title]["sheetId"])
            width = len(tab.headers)
            requests.append({
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        # One spare row: Sheets will not freeze every row of a grid, and
                        # an empty tab would otherwise be only its header.
                        "gridProperties": {"rowCount": len(tab.rows) + 2, "columnCount": width, "frozenRowCount": 1},
                    },
                    "fields": "gridProperties(rowCount,columnCount,frozenRowCount)",
                }
            })
            header = [
                {
                    "userEnteredValue": {"stringValue": text},
                    "userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": _HEADER_COLOUR},
                }
                for text in tab.headers
            ]
            rows = [{"values": header}]
            for values, tone in zip(tab.rows, tab.tones, strict=True):
                cells = []
                for index, (kind, value) in enumerate(zip(tab.kinds, values, strict=True)):
                    cell = value_to_cell("amount" if kind == "money" else kind, value)
                    fmt = cell.setdefault("userEnteredFormat", {})
                    colour = _MIRROR_TONES.get(tone)
                    if tone == "pending" and index < tab.protected_columns:
                        colour = None  # only the cells to fill in ask for attention
                    if colour:
                        fmt["backgroundColor"] = colour
                    cells.append(cell)
                rows.append({"values": cells})
            rows.append({"values": [{} for _ in tab.headers]})  # clears the spare row
            requests.append({
                "updateCells": {
                    "rows": rows,
                    "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                    "fields": "userEnteredValue,userEnteredFormat",
                }
            })
        self._batch(spreadsheet_id, requests)

    @serialized
    def read_register(self, workspace: WorkspaceSetting) -> list[SheetRow]:
        layout = self.register_layout(workspace)
        grid = self._read_grid(layout.spreadsheet_id, layout.title, layout.width)
        rows: list[SheetRow] = []
        for row_number, cells in enumerate(grid[1:], start=2):
            values: dict[str, Any] = {}
            meaningful = False
            for field_name, index in layout.columns.items():
                raw = cells[index] if index < len(cells) else None
                column = COLUMNS_BY_FIELD[field_name]
                value = cell_to_value(column.kind, field_name, raw)
                values[field_name] = value
                # A pre-ticked checkbox column alone is not a document.
                if column.kind != "bool" and value not in ("", None):
                    meaningful = True
            if meaningful:
                rows.append(SheetRow(row_number=row_number, values=values))
        return rows

    def _row_requests(
        self, layout: RegisterLayout, row_number: int, values: dict[str, Any], *, colour: bool
    ) -> list[dict[str, Any]]:
        cells = {
            layout.columns[name]: value_to_cell(COLUMNS_BY_FIELD[name].kind, value)
            for name, value in values.items()
            if name in layout.columns
        }
        requests: list[dict[str, Any]] = []
        # One updateCells per run of adjacent register columns, so a column of
        # someone else's in between is never written.
        indexes = sorted(cells)
        run: list[int] = []
        for index in indexes + [None]:  # type: ignore[list-item]
            if index is not None and (not run or index == run[-1] + 1):
                run.append(index)
                continue
            if run:
                requests.append(
                    {
                        "updateCells": {
                            "start": {
                                "sheetId": layout.sheet_id,
                                "rowIndex": row_number - 1,
                                "columnIndex": run[0],
                            },
                            "rows": [{"values": [cells[i] for i in run]}],
                            "fields": "userEnteredValue,userEnteredFormat.numberFormat",
                        }
                    }
                )
            run = [index] if index is not None else []
        if colour:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": layout.sheet_id,
                            "startRowIndex": row_number - 1,
                            "endRowIndex": row_number,
                            "startColumnIndex": 0,
                            "endColumnIndex": layout.width,
                        },
                        "cell": {"userEnteredFormat": {"backgroundColor": row_colour(values)}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
        return requests

    @serialized
    def write_row(self, workspace: WorkspaceSetting, row_number: int, values: dict[str, Any]) -> int:
        layout = self.register_layout(workspace)
        self._ensure_rows(layout, row_number)
        self._batch(layout.spreadsheet_id, self._row_requests(layout, row_number, values, colour=True))
        return row_number

    @serialized
    def append_row(self, workspace: WorkspaceSetting, values: dict[str, Any]) -> int:
        """Write below the last row with real data.

        Not the Sheets append API: it skips over pre-ticked checkbox rows and
        lands far below the visible data.
        """
        rows = self.read_register(workspace)
        row_number = max((row.row_number for row in rows), default=1) + 1
        return self.write_row(workspace, row_number, values)

    @serialized
    def append_rows(self, workspace: WorkspaceSetting, rows: list[dict[str, Any]]) -> list[int]:
        """Many rows below the data, in one request. Used by the migration."""
        if not rows:
            return []
        layout = self.register_layout(workspace)
        first = max((row.row_number for row in self.read_register(workspace)), default=1) + 1
        numbers = list(range(first, first + len(rows)))
        self._ensure_rows(layout, numbers[-1])
        requests: list[dict[str, Any]] = []
        for row_number, values in zip(numbers, rows):
            requests.extend(self._row_requests(layout, row_number, values, colour=True))
        # Large migrations stay under the request size limit.
        for start in range(0, len(requests), 400):
            self._batch(layout.spreadsheet_id, requests[start : start + 400])
        return numbers

    @serialized
    def write_cells(self, workspace: WorkspaceSetting, updates: list[tuple[int, dict[str, Any]]]) -> None:
        """Several partial rows in one request, without touching row colours."""
        layout = self.register_layout(workspace)
        requests: list[dict[str, Any]] = []
        for row_number, values in updates:
            requests.extend(self._row_requests(layout, row_number, values, colour=False))
        self._batch(layout.spreadsheet_id, requests)

    @serialized
    def find_row(self, workspace: WorkspaceSetting, internal_doc_number: str) -> int:
        for row in self.read_register(workspace):
            if row.values.get("num_doc_intern") == internal_doc_number:
                return row.row_number
        raise SheetDocumentNotFound(internal_doc_number)

    @serialized
    def delete_row(self, workspace: WorkspaceSetting, row_number: int) -> None:
        layout = self.register_layout(workspace)
        self._batch(
            layout.spreadsheet_id,
            [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": layout.sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_number - 1,
                            "endIndex": row_number,
                        }
                    }
                }
            ],
        )

    def _ensure_rows(self, layout: RegisterLayout, row_number: int) -> None:
        if row_number <= layout.row_count:
            return
        extra = max(row_number - layout.row_count, 200)
        self._batch(
            layout.spreadsheet_id,
            [
                {
                    "appendDimension": {
                        "sheetId": layout.sheet_id,
                        "dimension": "ROWS",
                        "length": extra,
                    }
                }
            ],
        )
        layout.row_count += extra

    # ── Legacy tabs ──────────────────────────────────────────────────────────

    @serialized
    def read_legacy_tab(self, workspace: WorkspaceSetting, title: str) -> LegacyTab | None:
        """Rows of an invoice-era tab, keyed by register field. ``None`` if absent."""
        spreadsheet_id = self._spreadsheet_id(workspace)
        tab = next(
            (t for t in self._tabs(spreadsheet_id) if fold_header(t.get("title", "")) == fold_header(title)),
            None,
        )
        if tab is None:
            return None
        width = max(int(tab.get("gridProperties", {}).get("columnCount", 26)), 1)
        grid = self._read_grid(spreadsheet_id, tab["title"], width)
        if not grid:
            return LegacyTab(title=tab["title"], rows=[], reference_column=None)
        headers = {fold_header(header): index for index, header in enumerate(grid[0]) if header}
        positions = {
            name: headers[fold_header(header)]
            for name, header in LEGACY_HEADERS.items()
            if fold_header(header) in headers
        }
        rows: list[SheetRow] = []
        for row_number, cells in enumerate(grid[1:], start=2):
            raw = {name: (cells[i] if i < len(cells) else None) for name, i in positions.items()}
            if not any(
                value not in (None, "") for name, value in raw.items() if name != "validat"
            ):
                continue
            rows.append(SheetRow(row_number=row_number, values=raw))
        return LegacyTab(
            title=tab["title"], rows=rows, reference_column=positions.get("num_doc_intern")
        )

    @serialized
    def write_legacy_references(
        self, workspace: WorkspaceSetting, tab: LegacyTab, references: list[tuple[int, str]]
    ) -> None:
        if not references or tab.reference_column is None:
            return
        letter = column_letter(tab.reference_column + 1)
        self._values().batchUpdate(
            spreadsheetId=self._spreadsheet_id(workspace),
            body={
                "valueInputOption": "RAW",
                "data": [
                    {"range": f"{quote_title(tab.title)}!{letter}{row}", "values": [[reference]]}
                    for row, reference in references
                ],
            },
        ).execute()

    # ── Drive ────────────────────────────────────────────────────────────────

    @serialized
    def upload_file_to_drive(
        self, file_path: Path, filename: str, mime_type: str, folder_id: str | None = None
    ) -> tuple[str, str]:
        """Upload a file to Drive and return ``(web_view_link, file_id)``."""
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(
            str(file_path), mimetype=mime_type, resumable=True, chunksize=1024 * 1024
        )
        body: dict = {"name": filename}
        if folder_id:
            body["parents"] = [folder_id]
        try:
            uploaded = (
                self._files()
                .create(
                    body=body, media_body=media, fields="id,webViewLink", supportsAllDrives=True
                )
                .execute()
            )
        finally:
            media.stream().close()
        self._permissions().create(
            fileId=uploaded["id"],
            body={"role": "reader", "type": "anyone"},
            supportsAllDrives=True,
        ).execute()
        return uploaded["webViewLink"], uploaded["id"]

    @serialized
    def drive_name_taken(self, folder_id: str | None, name: str, *, except_id: str | None = None) -> bool:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"name = '{escaped}' and trashed = false"
        if folder_id:
            query += f" and '{folder_id}' in parents"
        found = (
            self._files()
            .list(
                q=query,
                fields="files(id)",
                pageSize=5,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
            .get("files", [])
        )
        return any(item["id"] != except_id for item in found)

    @serialized
    def update_drive_file(
        self, file_id: str, *, name: str | None = None, folder_id: str | None = None
    ) -> None:
        """Rename a file and/or move it into ``folder_id``."""
        kwargs: dict[str, Any] = {"fileId": file_id, "supportsAllDrives": True, "body": {}}
        if name:
            kwargs["body"]["name"] = name
        if folder_id:
            current = (
                self._files()
                .get(fileId=file_id, fields="parents", supportsAllDrives=True)
                .execute()
                .get("parents", [])
            )
            if folder_id not in current:
                kwargs["addParents"] = folder_id
                if current:
                    kwargs["removeParents"] = ",".join(current)
        if kwargs["body"] or "addParents" in kwargs:
            self._files().update(**kwargs).execute()

    @serialized
    def download_drive_file(self, file_id: str, destination: Path) -> str:
        """Fetch a file's bytes; returns its MIME type."""
        from googleapiclient.http import MediaIoBaseDownload

        meta = (
            self._files()
            .get(fileId=file_id, fields="mimeType", supportsAllDrives=True)
            .execute()
        )
        request = self._files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request, chunksize=4 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        destination.write_bytes(buffer.getvalue())
        return meta.get("mimeType", "application/octet-stream")

    @serialized
    def trash_drive_file(self, file_id: str, *, trashed: bool = True) -> None:
        """To the bin (or back): unlike a deletion, an undo can bring it back."""
        self._files().update(fileId=file_id, body={"trashed": trashed}, supportsAllDrives=True).execute()

    @serialized
    def delete_drive_file(self, file_id: str) -> None:
        self._files().delete(fileId=file_id, supportsAllDrives=True).execute()

    @serialized
    def list_drive_files(self, folder_id: str, prefix: str) -> list[dict[str, str]]:
        """Files in a folder whose name starts with ``prefix``, newest first."""
        escaped = prefix.replace("'", "\\'")
        return (
            self._files()
            .list(
                q=f"'{folder_id}' in parents and name contains '{escaped}' and trashed = false",
                fields="files(id,name,createdTime)",
                orderBy="createdTime desc",
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
            .get("files", [])
        )

    @serialized
    def upload_private_file(self, file_path: Path, filename: str, mime_type: str, folder_id: str) -> str:
        """Like :meth:`upload_file_to_drive`, without the public link — for backups."""
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
        try:
            uploaded = (
                self._files()
                .create(
                    body={"name": filename, "parents": [folder_id]},
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )
        finally:
            media.stream().close()
        return uploaded["id"]


# ── Comparing versions ───────────────────────────────────────────────────────

#: Fields compared between the sheet, the database and a stored version.
COMPARED_FIELDS = tuple(c.field for c in REGISTER_COLUMNS if c.field != "num_doc_intern")


def normalize_value(field_name: str, value: Any) -> Any:
    """One comparable, JSON-safe form per field, whatever side it came from."""
    kind = COLUMNS_BY_FIELD[field_name].kind
    if kind == "date":
        parsed = parse_date(value) if not isinstance(value, date) else value
        return parsed.isoformat() if parsed else ""
    if kind == "amount":
        amount = parse_amount(value)
        return None if amount is None else round(amount, 2)
    if kind == "bool":
        return parse_bool(value) if isinstance(value, str) else bool(value)
    return str(value if value is not None else "").strip()


def snapshot_values(values: dict[str, Any]) -> dict[str, Any]:
    return {name: normalize_value(name, values.get(name)) for name in COMPARED_FIELDS}


def changed_fields(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    return [name for name in COMPARED_FIELDS if left.get(name) != right.get(name)]
