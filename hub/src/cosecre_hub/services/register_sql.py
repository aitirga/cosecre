"""Answering a question about the register with a query the language model writes.

"Quant hem gastat en material aquest curs?" or "Quin proveïdor ens ha facturat
més?" are not filters but sums, counts and rankings. The language model writes
them as SQL, and this module runs that SQL where it can do no harm:

* never against the hub's database, but against a throwaway in-memory copy of
  the register holding only its own columns — no users, sessions, tokens or
  anything else the hub keeps;
* through SQLite's authorizer, which lets a statement read that one table and
  call a short list of plain functions, and refuses everything else (writes,
  ``ATTACH``, pragmas, other tables) before it runs;
* with a time budget and a cap on the rows it may return.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import Document, PaymentMatch

TABLE = "documents"

#: Column → (how it is filled from an entry, what it means for the model).
COLUMNS: dict[str, tuple[Any, str]] = {
    "ref": (lambda d: d.internal_doc_number, "Referència interna (DOC-…)."),
    "tipus": (lambda d: d.tipus_document, "Factura, Factura simplificada, Pressupost, Albarà, Tiquet de rebut o Altres."),
    "num_factura": (lambda d: d.num_factura, "Número de factura del proveïdor."),
    "data": (lambda d: d.data_factura, "Data de la factura, AAAA-MM-DD (text), o NULL."),
    "proveidor": (lambda d: d.proveidor, "Nom del proveïdor."),
    "cif_proveidor": (lambda d: d.cif_proveidor, "CIF del proveïdor."),
    "ciutat": (lambda d: d.ciutat, "Ciutat del proveïdor."),
    "import": (lambda d: d.import_value, "Import total en euros (REAL), o NULL."),
    "descripcio": (lambda d: d.descripcio, "Què s'ha comprat, llegit del document."),
    "descripcio_compra": (lambda d: d.descripcio_compra, "Què s'ha comprat, escrit per secretaria."),
    "compte": (lambda d: d.pressupost_afectat, "General, Material i Sortides, Menjador, Caixeta, Targeta Prepagament, o ''."),
    "pagament": (lambda d: d.pagament, "Pagat, Pendent de pagament, Altres, o ''."),
    "metode_pagament": (lambda d: d.metode_pagament, "Efectiu, Targeta de prepagament, Transferència bancària, Targeta de dèbit, Rebut domiciliat, Altres, o ''."),
    "data_pagament": (lambda d: d.data_pagament, "Data de pagament, AAAA-MM-DD (text), o NULL."),
    "subministrat": (lambda d: d.subministrat, "Subministrat, No subministrat, No aplica, o ''."),
    "responsable": (lambda d: d.responsable_nom, "Nom de la persona responsable de la compra."),
    "validat": (lambda d: int(bool(d.validat)), "1 si secretaria l'ha validat, 0 si no."),
    "estat": (lambda d: d.status, "needs_validation (per revisar), validated, error, pending/processing (s'està llegint)."),
    "origen": (lambda d: d.origen, "Foto o Original."),
}

#: Plain functions a query may call; anything else is refused.
FUNCTIONS = {
    "abs", "avg", "coalesce", "count", "date", "group_concat", "ifnull", "iif", "instr",
    "julianday", "length", "lower", "max", "min", "nullif", "printf", "replace", "round",
    "strftime", "substr", "substring", "sum", "total", "trim", "upper", "like", "glob", "format",
}

MAX_ROWS = 100
MAX_COLUMNS = 12
TIME_BUDGET_SECONDS = 1.0


class QueryRefused(ValueError):
    """The query could not be run; the message is fit to show."""


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False


def schema_text() -> str:
    """The table as the language model is told about it."""
    lines = [f"Taula `{TABLE}` (SQLite), una fila per document del registre:"]
    lines += [f"- {name}: {meaning}" for name, (_, meaning) in COLUMNS.items()]
    lines.append("- justificat: 1 si un moviment bancari confirmat el paga, 0 si no.")
    return "\n".join(lines)


def _value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _authorize(action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 == TABLE else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if (arg2 or "").lower() in FUNCTIONS else sqlite3.SQLITE_DENY
    if action == getattr(sqlite3, "SQLITE_RECURSIVE", -1):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _load(session: Session) -> sqlite3.Connection:
    justified = {
        document_id
        for (document_id,) in session.query(PaymentMatch.document_id).filter(PaymentMatch.status == "confirmed")
    }
    names = [*COLUMNS, "justificat"]
    connection = sqlite3.connect(":memory:")
    connection.execute(f"CREATE TABLE {TABLE} ({', '.join(names)})")
    connection.executemany(
        f"INSERT INTO {TABLE} VALUES ({', '.join('?' for _ in names)})",
        (
            [*(_value(fill(document)) for fill, _ in COLUMNS.values()), int(document.id in justified)]
            for document in session.query(Document).yield_per(500)
        ),
    )
    connection.commit()
    return connection


def run_query(session: Session, sql: str) -> QueryResult:
    """Run one read-only ``SELECT`` over the register. Raises :class:`QueryRefused`."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise QueryRefused("No hi ha cap consulta.")
    if ";" in statement:
        raise QueryRefused("Només s'admet una consulta.")
    if not statement.lower().startswith(("select", "with")):
        raise QueryRefused("Només s'admeten consultes de lectura.")

    connection = _load(session)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_authorize)
        deadline = time.monotonic() + TIME_BUDGET_SECONDS
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        try:
            cursor = connection.execute(statement)
            rows = cursor.fetchmany(MAX_ROWS + 1)
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            if "interrupted" in message:
                raise QueryRefused("La consulta trigava massa.") from exc
            if "not authorized" in message or "prohibited" in message:
                raise QueryRefused("La consulta fa servir alguna cosa no permesa.") from exc
            raise QueryRefused(f"La consulta no és vàlida: {message}") from exc
        columns = [description[0] for description in cursor.description or []][:MAX_COLUMNS]
        return QueryResult(
            columns=columns,
            rows=[list(row[: len(columns)]) for row in rows[:MAX_ROWS]],
            truncated=len(rows) > MAX_ROWS,
        )
    finally:
        connection.close()


__all__ = ["COLUMNS", "QueryRefused", "QueryResult", "run_query", "schema_text"]
