from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _parse_import_value(v: object) -> float | None:
    """Convert a currency string or number to a plain float.

    Handles European (1.234,56) and US (1,234.56) formats, and strips
    common currency symbols.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[€$£¥\s]", "", str(v)).strip()
    if not s:
        return None
    if "," in s and "." in s:
        # Whichever comes last is the decimal separator
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # Treat comma as decimal separator only when ≤2 digits follow it
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


ExtractionStatus = Literal[
    "pending",
    "processing",
    "written_to_sheet",
    "needs_validation",
    "validated",
    "error",
]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserRead(BaseModel):
    id: int
    email: EmailStr
    is_admin: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserRead


class InvoiceExtraction(BaseModel):
    num_factura: str = ""
    data_factura: str = ""
    proveidor: str = ""
    cif_proveidor: str = ""
    adreca_proveidor: str = ""
    import_value: float | None = Field(default=None, alias="import")
    cif_proveit: str = ""
    descripcio: str = ""
    pressupost_afectat: str = ""
    num_doc_intern: str = ""

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("import_value", mode="before")
    @classmethod
    def parse_import(cls, v: object) -> float | None:
        return _parse_import_value(v)


class InvoiceUpdate(BaseModel):
    num_factura: str | None = None
    data_factura: str | None = None
    proveidor: str | None = None
    cif_proveidor: str | None = None
    adreca_proveidor: str | None = None
    import_value: float | None = Field(default=None, alias="import")
    cif_proveit: str | None = None
    descripcio: str | None = None
    pressupost_afectat: str | None = None
    validat: bool | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("import_value", mode="before")
    @classmethod
    def parse_import(cls, v: object) -> float | None:
        return _parse_import_value(v)


class InvoiceRecord(InvoiceExtraction):
    validat: bool = False
    file_link: str = ""
    file_url: str | None = None
    source_file_name: str | None = None
    source_file_type: str | None = None
    extraction_status: ExtractionStatus = "pending"
    sheet_row_ref: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_message: str | None = None


class JobRead(BaseModel):
    id: str
    internal_doc_number: str
    status: ExtractionStatus
    error_message: str | None = None
    extracted_payload: InvoiceExtraction | None = None
    sheet_row_ref: int | None = None
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    job_id: str
    internal_doc_number: str
    status: ExtractionStatus


class WorkspaceSettingsRead(BaseModel):
    spreadsheet_url: str | None = None
    sheet_name: str = "Factures"
    openai_model: str = "gpt-5.4"
    extraction_prompt: str = ""
    polling_interval_seconds: int = 30


class WorkspaceSettingsUpdate(BaseModel):
    spreadsheet_url: str | None = None
    sheet_name: str = Field(min_length=1, max_length=255)
    openai_model: str = Field(min_length=1, max_length=120)
    extraction_prompt: str = ""
    polling_interval_seconds: int = Field(default=30, ge=10, le=300)


class RefreshResult(BaseModel):
    refreshed: int


class MessageResponse(BaseModel):
    message: str
