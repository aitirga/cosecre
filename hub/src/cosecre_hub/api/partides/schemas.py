from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class PartidaRead(BaseModel):
    id: int
    exercici: int
    tipus: Literal["despesa", "ingres"]
    codi: str
    codi_pare: str | None
    codi_finalista: str
    #: The fund without its year (``MOTXILLES``), ``""`` for the ordinary budget.
    fons: str
    fons_label: str
    nom: str
    import_pressupost: float
    ordre: int
    #: A heading with sub-lines: movements go to its sub-lines, not to it.
    te_fills: bool
    retirada: bool
    context: str
    #: Confirmed movements charged to it, and their total.
    moviments: int = 0
    imputat: float = 0.0


class PressupostRead(BaseModel):
    exercici: int | None
    exercicis: list[int]
    centre: str = ""
    nif: str = ""
    codi_centre: str = ""
    data_informe: str = ""
    total_ingressos: float | None = None
    total_despeses: float | None = None
    file_name: str = ""
    imported_at: datetime | None = None
    context_general: str = ""
    #: The secretari/a's order of the lines inside each concept, by code. Keyed
    #: by the concept's code (or ``chapter-N``), so it holds from year to year.
    ordre_usuari: dict[str, list[str]] = {}
    jev: bool = False
    partides: list[PartidaRead] = []


class ImportSummary(BaseModel):
    dry_run: bool
    exercici: int
    centre: str
    nif: str
    codi_centre: str
    #: ``None`` when the hub has no CIF set to compare against.
    nif_matches: bool | None
    replaces: bool
    created: int
    updated: int
    unchanged: int
    #: Gone from the new file but kept because movements are charged to them.
    retired: int
    removed: int
    despeses: int
    ingressos: int
    total_despeses: float | None
    #: Context copied over from the same line of an earlier year.
    context_inherited: int = 0


class OrderUpdate(BaseModel):
    block: str = Field(min_length=1, max_length=64)
    codis: list[str] = Field(default_factory=list, max_length=400)


class ContextUpdate(BaseModel):
    context: str = Field(default="", max_length=4000)


class AssignmentRead(BaseModel):
    partida_id: int
    import_assignat: float | None
    origen: Literal["persona", "jev"]
    confianca: float | None
    confirmada: bool


class RankedRead(BaseModel):
    partida_id: int
    probability: float


class SuggestionRead(BaseModel):
    ranking: list[RankedRead]
    confidence: float
    cap: float
    multiple: float | None
    model: str
    created_at: datetime


class InvoiceBrief(BaseModel):
    """An invoice the movement paid, as a person confirmed in Justificar extractes."""

    reference: str
    tipus_document: str
    num_factura: str
    proveidor: str
    cif_proveidor: str
    data_factura: date | None
    import_value: float | None
    descripcio: str
    descripcio_compra: str
    responsable_nom: str
    file_url: str | None
    file_name: str | None


class QueueItem(BaseModel):
    """One statement movement that is charged to the budget."""

    id: int
    import_id: int
    codi: str
    #: Which account the money moved in, and how (``METODES_PAGAMENT``).
    compte: str
    tipus: str
    categoria: str
    data: date | None
    concepte: str
    mes_dades: str
    #: Signed, as the statement has it: negative is money out.
    import_value: float
    #: ``despesa`` for money out, ``ingres`` for money in: the lines that apply.
    sentit: Literal["despesa", "ingres"]
    #: Its reconciliation with the register (``confirmed``, ``proposed``…).
    match_status: str
    factures: list[InvoiceBrief]
    #: The budget year whose lines apply: the movement's own, or the latest imported.
    exercici: int | None
    curs: str
    #: ``pendent`` (nothing), ``proposta`` (only Jev's) or ``assignada``.
    estat: Literal["pendent", "proposta", "assignada"]
    assignments: list[AssignmentRead]
    suggestion: SuggestionRead | None


class AssignmentWrite(BaseModel):
    partida_id: int
    import_assignat: float | None = None


class AssignmentsUpdate(BaseModel):
    partides: list[AssignmentWrite] = Field(default_factory=list, max_length=20)
