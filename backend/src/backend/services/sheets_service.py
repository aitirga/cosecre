from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..config import Settings
from ..models import WorkspaceSetting
from ..schemas import InvoiceExtraction, InvoiceRecord

FIELD_TO_HEADER = {
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
}
VALIDAT_HEADER = "Validat"
REQUIRED_HEADERS = [*FIELD_TO_HEADER.values(), VALIDAT_HEADER]
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


@dataclass
class SheetWriteResult:
    row_number: int


def parse_spreadsheet_id(spreadsheet_url: str) -> str:
    if "/spreadsheets/d/" in spreadsheet_url:
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", spreadsheet_url)
        if match:
            return match.group(1)
    parsed = urlparse(spreadsheet_url)
    if parsed.scheme or parsed.netloc:
        raise ValueError("Could not parse spreadsheet id from the provided URL.")
    return spreadsheet_url


def column_letter(column_number: int) -> str:
    result = []
    current = column_number
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "si", "sí", "x"}


def synthetic_internal_doc_number(row_number: int) -> str:
    return f"sheet-row-{row_number}"


class GoogleSheetsService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def is_ready(self, workspace: WorkspaceSetting) -> bool:
        return bool(
            workspace.spreadsheet_url
            and workspace.sheet_name
            and self.settings.google_service_account_file
        )

    def _credentials(self):
        if self.settings.google_service_account_file is None:
            raise RuntimeError("Google service account file is not configured.")
        return service_account.Credentials.from_service_account_file(
            self.settings.google_service_account_file,
            scopes=SCOPES,
        )

    def _service(self):
        return build("sheets", "v4", credentials=self._credentials(), cache_discovery=False)

    def _drive_service(self):
        return build("drive", "v3", credentials=self._credentials(), cache_discovery=False)

    def upload_file_to_drive(self, file_path: Path, filename: str, mime_type: str) -> tuple[str, str]:
        """Upload a file to Drive and return (web_view_link, file_id)."""
        drive = self._drive_service()
        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=False)
        uploaded = (
            drive.files()
            .create(body={"name": filename}, media_body=media, fields="id,webViewLink")
            .execute()
        )
        drive.permissions().create(
            fileId=uploaded["id"],
            body={"role": "reader", "type": "anyone"},
        ).execute()
        return uploaded["webViewLink"], uploaded["id"]

    def _spreadsheet_id(self, workspace: WorkspaceSetting) -> str:
        if workspace.spreadsheet_id:
            return workspace.spreadsheet_id
        if not workspace.spreadsheet_url:
            raise RuntimeError("Spreadsheet URL is not configured.")
        return parse_spreadsheet_id(workspace.spreadsheet_url)

    def _sheet_properties(self, workspace: WorkspaceSetting) -> tuple[str, int]:
        service = self._service()
        spreadsheet_id = self._spreadsheet_id(workspace)
        metadata = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
            .execute()
        )
        target = workspace.sheet_name.strip().lower()
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title", "").strip().lower() == target:
                return spreadsheet_id, int(properties["sheetId"])
        raise RuntimeError(f"Sheet tab '{workspace.sheet_name}' was not found in the spreadsheet.")

    def ensure_headers(self, workspace: WorkspaceSetting) -> list[str]:
        service = self._service()
        spreadsheet_id = self._spreadsheet_id(workspace)
        response = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{workspace.sheet_name}!A1:ZZ1")
            .execute()
        )
        values = response.get("values", [])
        if not values:
            (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{workspace.sheet_name}!A1:{column_letter(len(REQUIRED_HEADERS))}1",
                    valueInputOption="RAW",
                    body={"values": [REQUIRED_HEADERS]},
                )
                .execute()
            )
            return REQUIRED_HEADERS

        headers = values[0]
        missing = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing:
            next_col = column_letter(len(headers) + 1)
            end_col = column_letter(len(headers) + len(missing))
            (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{workspace.sheet_name}!{next_col}1:{end_col}1",
                    valueInputOption="RAW",
                    body={"values": [missing]},
                )
                .execute()
            )
            headers = headers + missing
        return headers

    def _invoice_value_map(self, invoice: InvoiceExtraction | InvoiceRecord) -> dict:
        payload = invoice.model_dump(by_alias=False)
        import_raw = payload["import_value"]
        # Write as a numeric value so Sheets treats it as a number, not text
        import_cell: float | str = import_raw if import_raw is not None else ""
        return {
            FIELD_TO_HEADER["num_factura"]: payload["num_factura"],
            FIELD_TO_HEADER["data_factura"]: payload["data_factura"],
            FIELD_TO_HEADER["proveidor"]: payload["proveidor"],
            FIELD_TO_HEADER["cif_proveidor"]: payload["cif_proveidor"],
            FIELD_TO_HEADER["adreca_proveidor"]: payload["adreca_proveidor"],
            FIELD_TO_HEADER["import_value"]: import_cell,
            FIELD_TO_HEADER["cif_proveit"]: payload["cif_proveit"],
            FIELD_TO_HEADER["descripcio"]: payload["descripcio"],
            FIELD_TO_HEADER["pressupost_afectat"]: payload["pressupost_afectat"],
            FIELD_TO_HEADER["num_doc_intern"]: payload["num_doc_intern"],
            FIELD_TO_HEADER["file_link"]: getattr(invoice, "file_link", ""),
            VALIDAT_HEADER: "TRUE" if getattr(invoice, "validat", False) else "FALSE",
        }

    def _row_from_invoice(self, invoice: InvoiceExtraction | InvoiceRecord, headers: Iterable[str]) -> list:
        value_map = self._invoice_value_map(invoice)
        return [value_map.get(header, "") for header in headers]

    def _apply_row_color(self, spreadsheet_id: str, sheet_id: int, row_number: int, color: dict[str, float]):
        service = self._service()
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row_number - 1,
                                "endRowIndex": row_number,
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": color}},
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                ]
            },
        ).execute()

    def _find_row(self, workspace: WorkspaceSetting, internal_doc_number: str) -> tuple[int, list[str], list[str]]:
        headers = self.ensure_headers(workspace)
        invoices = self.list_invoices(workspace)
        for invoice in invoices:
            if invoice.num_doc_intern == internal_doc_number and invoice.sheet_row_ref is not None:
                return invoice.sheet_row_ref, headers, self._row_from_invoice(invoice, headers)
        raise RuntimeError(f"Invoice '{internal_doc_number}' was not found in Google Sheets.")

    def _row_has_meaningful_data(self, row_map: dict[str, str]) -> bool:
        for header in FIELD_TO_HEADER.values():
            if row_map.get(header, "").strip():
                return True
        return False

    def list_invoices(self, workspace: WorkspaceSetting) -> list[InvoiceRecord]:
        headers = self.ensure_headers(workspace)
        service = self._service()
        spreadsheet_id = self._spreadsheet_id(workspace)
        response = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{workspace.sheet_name}!A:Z")
            .execute()
        )
        values = response.get("values", [])
        if len(values) <= 1:
            return []

        records: list[InvoiceRecord] = []
        for row_number, row in enumerate(values[1:], start=2):
            row_map = {
                header: row[index] if index < len(row) else ""
                for index, header in enumerate(headers)
            }
            if not self._row_has_meaningful_data(row_map):
                continue
            internal_doc_number = row_map.get(FIELD_TO_HEADER["num_doc_intern"], "").strip()
            if not internal_doc_number:
                internal_doc_number = synthetic_internal_doc_number(row_number)
            validat = parse_bool(row_map.get(VALIDAT_HEADER, ""))
            records.append(
                InvoiceRecord(
                    num_factura=row_map.get(FIELD_TO_HEADER["num_factura"], ""),
                    data_factura=row_map.get(FIELD_TO_HEADER["data_factura"], ""),
                    proveidor=row_map.get(FIELD_TO_HEADER["proveidor"], ""),
                    cif_proveidor=row_map.get(FIELD_TO_HEADER["cif_proveidor"], ""),
                    adreca_proveidor=row_map.get(FIELD_TO_HEADER["adreca_proveidor"], ""),
                    import_value=row_map.get(FIELD_TO_HEADER["import_value"], ""),
                    cif_proveit=row_map.get(FIELD_TO_HEADER["cif_proveit"], ""),
                    descripcio=row_map.get(FIELD_TO_HEADER["descripcio"], ""),
                    pressupost_afectat=row_map.get(FIELD_TO_HEADER["pressupost_afectat"], ""),
                    num_doc_intern=internal_doc_number,
                    file_link=row_map.get(FIELD_TO_HEADER["file_link"], ""),
                    validat=validat,
                    extraction_status="validated" if validat else "needs_validation",
                    sheet_row_ref=row_number,
                )
            )
        return records

    def append_invoice(self, workspace: WorkspaceSetting, invoice: InvoiceExtraction) -> SheetWriteResult:
        headers = self.ensure_headers(workspace)
        spreadsheet_id = self._spreadsheet_id(workspace)
        service = self._service()
        # Place the new row immediately after the last row that has real invoice
        # data, instead of using the Sheets append API which may skip over
        # pre-populated checkbox-only rows and land far below the visible data.
        existing = self.list_invoices(workspace)
        row_refs = [inv.sheet_row_ref for inv in existing if inv.sheet_row_ref is not None]
        row_number = (max(row_refs) + 1) if row_refs else 2
        end_column = column_letter(len(headers))
        (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=f"{workspace.sheet_name}!A{row_number}:{end_column}{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": [self._row_from_invoice(invoice, headers)]},
            )
            .execute()
        )
        try:
            _, sheet_id = self._sheet_properties(workspace)
            self._apply_row_color(
                spreadsheet_id,
                sheet_id,
                row_number,
                {"red": 1.0, "green": 0.95, "blue": 0.8},
            )
        except Exception:  # noqa: BLE001
            pass  # row colour is cosmetic — don't fail the write if it can't be applied
        return SheetWriteResult(row_number=row_number)

    def delete_invoice(self, workspace: WorkspaceSetting, internal_doc_number: str) -> None:
        try:
            row_number, _, _ = self._find_row(workspace, internal_doc_number)
        except RuntimeError:
            return  # not in sheet, nothing to do
        spreadsheet_id, sheet_id = self._sheet_properties(workspace)
        service = self._service()
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": row_number - 1,
                                "endIndex": row_number,
                            }
                        }
                    }
                ]
            },
        ).execute()

    def update_invoice(self, workspace: WorkspaceSetting, invoice: InvoiceRecord) -> SheetWriteResult:
        row_number, headers, _ = self._find_row(workspace, invoice.num_doc_intern)
        spreadsheet_id = self._spreadsheet_id(workspace)
        service = self._service()
        end_column = column_letter(len(headers))
        (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=f"{workspace.sheet_name}!A{row_number}:{end_column}{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": [self._row_from_invoice(invoice, headers)]},
            )
            .execute()
        )
        try:
            _, sheet_id = self._sheet_properties(workspace)
            self._apply_row_color(
                spreadsheet_id,
                sheet_id,
                row_number,
                {"red": 1.0, "green": 1.0, "blue": 1.0}
                if invoice.validat
                else {"red": 1.0, "green": 0.95, "blue": 0.8},
            )
        except Exception:  # noqa: BLE001
            pass  # row colour is cosmetic — don't fail the update if it can't be applied
        return SheetWriteResult(row_number=row_number)
