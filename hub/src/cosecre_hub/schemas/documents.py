"""The accounting-document register: what is extracted, stored and edited.

Category values are stored as the Catalan labels people read in the sheet, so a
value in the database, in the API and in a spreadsheet cell is the same string.
An empty string always means "not known yet".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..services.text_format import parse_amount, parse_date

TIPUS_DOCUMENT = (
    "Factura",
    "Factura simplificada",
    "Pressupost",
    "Albarà",
    "Tiquet de rebut",
    "Altres",
)
ESTATS_PAGAMENT = ("Pagat", "Pendent de pagament", "Altres")
METODES_PAGAMENT = (
    "Efectiu",
    "Targeta de prepagament",
    "Transferència bancària",
    "Targeta de dèbit",
    "Rebut domiciliat",
    "Altres",
)
ESTATS_SUBMINISTRAMENT = ("Subministrat", "No subministrat", "No aplica")
ORIGENS = ("Foto", "Original")
#: The bank account a payment comes out of. Stored under the old
#: ``pressupost_afectat`` key, so existing records and backups keep working.
COMPTES = (
    "General",
    "Material i Sortides",
    "Menjador",
    "Caixeta",
    "Targeta Prepagament",
)

#: Field → allowed values, for every field that is a closed list.
CHOICES: dict[str, tuple[str, ...]] = {
    "tipus_document": TIPUS_DOCUMENT,
    "pagament": ESTATS_PAGAMENT,
    "metode_pagament": METODES_PAGAMENT,
    "subministrat": ESTATS_SUBMINISTRAMENT,
    "origen": ORIGENS,
    "pressupost_afectat": COMPTES,
}


def canonical_choice(field: str, value: object) -> str:
    """Match a value to its list case- and accent-insensitively.

    Returns the canonical label, ``""`` for blank, or the trimmed input when it
    is not on the list — a person typing in the sheet is not rejected, only the
    API is strict.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    folded = _fold(text)
    for option in CHOICES[field]:
        if _fold(option) == folded:
            return option
    return text


def _fold(text: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).strip()


ExtractionStatus = Literal[
    "pending",
    "processing",
    "written_to_sheet",
    "needs_validation",
    "validated",
    "error",
]

#: ``synced``: the sheet row matches the database. ``pending``: a change has not
#: reached the sheet yet (it is retried on the next sync). ``removed``: someone
#: deleted the row in the sheet; the record is kept here and comes back only if
#: it is saved again.
SheetState = Literal["synced", "pending", "removed"]

CaptureSource = Literal["camera", "file"]


# ── What the model is asked for ──────────────────────────────────────────────


class DocumentExtraction(BaseModel):
    """The structured-output schema handed to the vision model.

    Every field has a default: a missing value must come back empty rather than
    fail the whole extraction. Descriptions are part of the schema the model
    sees, so they double as per-field instructions.
    """

    transcripcio: str = Field(
        default="",
        description=(
            "Transcripció literal i completa del document, línia a línia, en l'idioma original. "
            "Inclou segells (p. ex. PAGAT), notes manuscrites i peu de pàgina."
        ),
    )
    tipus_document: Literal[TIPUS_DOCUMENT + ("",)] = Field(  # type: ignore[valid-type]
        default="",
        description=(
            "Factura: factura completa amb dades del client. Factura simplificada: tiquet que "
            "posa 'factura simplificada' o 'fac. simp.'. Pressupost: oferta prèvia. Albarà: nota "
            "de lliurament. Tiquet de rebut: rebut o justificant de pagament que no és factura."
        ),
    )
    num_factura: str = Field(default="", description="Número del document tal com està imprès.")
    data_factura: str = Field(default="", description="Data d'emissió en format dd/mm/aaaa.")
    proveidor: str = Field(default="", description="Nom o raó social de qui emet el document.")
    cif_proveidor: str = Field(default="", description="NIF o CIF de qui emet el document.")
    carrer: str = Field(default="", description="Carrer i número del proveïdor.")
    codi_postal: str = Field(default="", description="Codi postal del proveïdor.")
    ciutat: str = Field(
        default="", description="Població del proveïdor, sense la província ni el país."
    )
    compte_corrent: str = Field(
        default="",
        description=(
            "Un sol IBAN: el del proveïdor on s'ha de pagar (el primer, si n'hi ha diversos). "
            "Buit si només hi ha el compte del client (p. ex. en un rebut domiciliat)."
        ),
    )
    cif_proveit: str = Field(default="", description="NIF o CIF del client (a qui es factura).")
    import_value: float | None = Field(
        default=None,
        alias="import",
        description="Import total a pagar, IVA inclòs, com a número.",
    )
    descripcio: str = Field(
        default="",
        description=(
            "Resum breu en català del que s'ha comprat o del servei, en minúscules amb "
            "majúscula inicial. Tradueix-lo si el document és en una altra llengua."
        ),
    )
    pressupost_afectat: Literal[COMPTES + ("",)] = Field(  # type: ignore[valid-type]
        default="",
        description=(
            "Compte de l'institut d'on surt el pagament. Menjador: factures del menjador "
            "escolar (p. ex. Ares Menjares). Caixeta: tiquets i factures simplificades pagats "
            "en efectiu. Targeta Prepagament: tiquets i factures simplificades no pagats en "
            "efectiu. General: la resta, sobretot targeta de dèbit, rebut domiciliat o "
            "transferència. Material i Sortides: no l'usis mai. Buit si no es pot saber."
        ),
    )
    pagament: Literal[ESTATS_PAGAMENT + ("",)] = Field(  # type: ignore[valid-type]
        default="",
        description=(
            "Pagat si el document indica que ja s'ha cobrat (tiquet pagat, segell PAGAT, canvi "
            "retornat). Pendent de pagament si hi ha venciment o instruccions per pagar. "
            "Buit si no es pot saber."
        ),
    )
    metode_pagament: Literal[METODES_PAGAMENT + ("",)] = Field(  # type: ignore[valid-type]
        default="",
        description="Com s'ha pagat o s'ha de pagar, només si el document ho diu. Buit si no.",
    )
    data_pagament: str = Field(
        default="",
        description="Data en què es va pagar, en format dd/mm/aaaa, si el document la mostra.",
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("import_value", mode="before")
    @classmethod
    def parse_import(cls, v: object) -> float | None:
        return parse_amount(v)


# ── What is stored and edited ────────────────────────────────────────────────


class DocumentFields(BaseModel):
    """Every column of the register that a person can change."""

    tipus_document: str = ""
    origen: str = ""
    num_factura: str = ""
    data_factura: date | None = None
    proveidor: str = ""
    cif_proveidor: str = ""
    carrer: str = ""
    codi_postal: str = ""
    ciutat: str = ""
    compte_corrent: str = ""
    cif_proveit: str = ""
    import_value: float | None = Field(default=None, alias="import")
    descripcio: str = ""
    descripcio_compra: str = ""
    pagament: str = ""
    pagament_observacions: str = ""
    metode_pagament: str = ""
    data_pagament: date | None = None
    subministrat: str = ""
    pressupost_afectat: str = ""
    validat: bool = False

    model_config = ConfigDict(populate_by_name=True)


EDITABLE_FIELDS = tuple(DocumentFields.model_fields)


class AiHint(BaseModel):
    """Why a field holds the value it does, when a model chose it."""

    #: ``migracio``: inferred from which of the two old tabs a row came from.
    source: Literal["jev", "openai", "jev+openai", "migracio"]
    confidence: float | None = None
    #: The other model's answer, when the two disagreed.
    alternative: str | None = None
    review: bool = False


class DocumentRecord(DocumentFields):
    num_doc_intern: str
    file_link: str = ""
    file_url: str | None = None
    #: What the original is called when downloaded — the same as on Drive.
    file_name: str | None = None
    file_size: int | None = None
    drive_url: str | None = None
    source_file_name: str | None = None
    source_file_type: str | None = None
    transcripcio: str = ""
    extraction_status: ExtractionStatus = "pending"
    sheet_state: SheetState = "pending"
    sheet_row_ref: int | None = None
    legacy_type: str | None = None
    ai_hints: dict[str, AiHint] = Field(default_factory=dict)
    ai_trace: dict[str, Any] | None = None
    iban_valid: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_message: str | None = None


class DocumentUpdate(BaseModel):
    """A partial edit. Only the fields sent are touched; ``null`` clears a date
    or the amount."""

    tipus_document: str | None = None
    num_factura: str | None = None
    data_factura: date | None = None
    proveidor: str | None = None
    cif_proveidor: str | None = None
    carrer: str | None = None
    codi_postal: str | None = None
    ciutat: str | None = None
    compte_corrent: str | None = None
    cif_proveit: str | None = None
    import_value: float | None = Field(default=None, alias="import")
    descripcio: str | None = None
    descripcio_compra: str | None = None
    pagament: str | None = None
    pagament_observacions: str | None = None
    metode_pagament: str | None = None
    data_pagament: date | None = None
    subministrat: str | None = None
    pressupost_afectat: str | None = None
    validat: bool | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("import_value", mode="before")
    @classmethod
    def parse_import(cls, v: object) -> float | None:
        return parse_amount(v)

    @field_validator("data_factura", "data_pagament", mode="before")
    @classmethod
    def parse_dates(cls, v: object) -> date | None:
        if v is None or v == "":
            return None
        parsed = parse_date(v)
        if parsed is None:
            raise ValueError("La data ha de tenir el format dd/mm/aaaa.")
        return parsed

    @field_validator(
        "tipus_document", "pagament", "metode_pagament", "subministrat", "pressupost_afectat"
    )
    @classmethod
    def check_choice(cls, v: str | None, info) -> str | None:
        if v is None:
            return None
        value = canonical_choice(info.field_name, v)
        if value and value not in CHOICES[info.field_name]:
            raise ValueError(f"Valor no permès: {v}")
        return value


class JobRead(BaseModel):
    id: str
    internal_doc_number: str
    status: ExtractionStatus
    error_message: str | None = None
    sheet_row_ref: int | None = None
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    job_id: str
    internal_doc_number: str
    status: ExtractionStatus


class SyncResult(BaseModel):
    #: False when no spreadsheet is configured: the register lives only here.
    sheet_configured: bool = True
    refreshed: int
    imported: int = 0
    updated: int = 0
    pushed: int = 0
    removed: int = 0
    #: Sheet-side changes (and conflicts among them) waiting for a person.
    waiting: int = 0
    conflicts: int = 0
    error: str | None = None


class FieldChangeRead(BaseModel):
    field: str
    label: str
    db: Any = None
    sheet: Any = None


class DiffEntryRead(BaseModel):
    reference: str
    status: Literal["db_changed", "not_in_sheet", "sheet_changed", "new_in_sheet", "missing", "conflict"]
    row: int | None = None
    num_factura: str = ""
    proveidor: str = ""
    changes: list[FieldChangeRead] = Field(default_factory=list)


class SyncDiff(BaseModel):
    sheet_configured: bool = True
    entries: list[DiffEntryRead] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class SyncApply(BaseModel):
    """Which entries to apply: references, or ``row:<n>`` for typed rows. All when omitted."""

    references: list[str] | None = None


class SyncApplied(BaseModel):
    applied: int
    backup: str | None = None


# ── Settings ─────────────────────────────────────────────────────────────────


class WorkspaceSettingsRead(BaseModel):
    spreadsheet_url: str | None = None
    registry_sheet_name: str = "Registre documents comptables"
    #: The two tabs the register replaced. Read only by the migration.
    sheet_name: str = "Factures"
    ticket_sheet_name: str = "Tiquets"
    openai_model: str = "gpt-6-luna"
    extraction_prompt: str = ""
    polling_interval_seconds: int = 30
    classifier_configured: bool = False
    drive_folder_configured: bool = False


class WorkspaceSettingsUpdate(BaseModel):
    spreadsheet_url: str | None = None
    registry_sheet_name: str = Field(
        default="Registre documents comptables", min_length=1, max_length=255
    )
    sheet_name: str = Field(default="Factures", min_length=1, max_length=255)
    ticket_sheet_name: str = Field(default="Tiquets", min_length=1, max_length=255)
    openai_model: str = Field(min_length=1, max_length=120)
    extraction_prompt: str = ""
    polling_interval_seconds: int = Field(default=30, ge=10, le=300)


# ── Migration ────────────────────────────────────────────────────────────────


class MigrationIssue(BaseModel):
    tab: str
    row: int | None = None
    reference: str | None = None
    message: str


class MigrationReport(BaseModel):
    dry_run: bool
    tabs: dict[str, int] = Field(default_factory=dict)
    already_migrated: int = 0
    to_create: int = 0
    created: int = 0
    references_generated: int = 0
    #: Uploads found only in the database, never written to either old tab.
    from_database: int = 0
    with_file: int = 0
    issues: list[MigrationIssue] = Field(default_factory=list)
    enrichment_pending: int = 0
    enrichment_done: int = 0
    enrichment_running: bool = False
    #: Originals kept only on this server, not yet in the Drive folder.
    drive_missing: int = 0
    drive_running: bool = False
    drive_configured: bool = False
    completed_at: datetime | None = None
