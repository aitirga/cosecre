"""The Assistent's read-only SQL, over a copy of the data rather than the data.

The model writes SQL to answer questions — sums, rankings, months compared —
and this module runs it where it can do no harm:

* never against the hub's database, but against an in-memory SQLite copy of a
  short list of tables and columns: no password hashes, tokens, invitations,
  sessions, file paths or anything else the hub keeps for itself;
* through SQLite's authorizer, which lets a statement read those tables and
  call a list of plain functions, and refuses everything else — writes,
  ``ATTACH``, pragmas — before it runs;
* with ``query_only`` on, a time budget and a cap on the rows it returns.

The copy is built once per question, on the first query, and thrown away with
it. Writing is not this module's business at all: see :mod:`.proposals`.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Float, Integer, select
from sqlalchemy.orm import Session

from ...db import Base

#: Table → (what it is, {column: what it means}). Only these columns exist in
#: the copy; names are the database's own, so what a query finds can be sent
#: straight back to the API.
TABLES: dict[str, tuple[str, dict[str, str]]] = {
    "documents": (
        "El registre comptable: una fila per factura, tiquet o altre document.",
        {
            "id": "Clau interna.",
            "internal_doc_number": "Referència (DOC-…). És la que fa servir l'API: /documents/records/{internal_doc_number}.",
            "tipus_document": "Factura, Factura simplificada, Pressupost, Albarà, Tiquet de rebut o Altres.",
            "origen": "Foto o Original.",
            "num_factura": "Número de factura del proveïdor.",
            "data_factura": "Data de la factura, 'AAAA-MM-DD', o NULL.",
            "proveidor": "Nom del proveïdor.",
            "cif_proveidor": "CIF del proveïdor.",
            "carrer": "Adreça del proveïdor.",
            "codi_postal": "Codi postal del proveïdor.",
            "ciutat": "Ciutat del proveïdor.",
            "compte_corrent": "IBAN del proveïdor, si el document en porta.",
            "cif_proveit": "CIF del centre que surt al document.",
            "import_value": "Import total en euros (REAL), o NULL. A l'API el camp es diu `import`.",
            "descripcio": "Què s'ha comprat, llegit del document.",
            "descripcio_compra": "Què s'ha comprat, escrit per secretaria.",
            "pagament": "Pagat, Pendent de pagament, Altres, o ''.",
            "pagament_observacions": "Notes sobre el pagament.",
            "metode_pagament": "Efectiu, Targeta de prepagament, Transferència bancària, Targeta de dèbit, Rebut domiciliat, Altres, o ''.",
            "data_pagament": "Data de pagament, 'AAAA-MM-DD', o NULL.",
            "subministrat": "Subministrat, No subministrat, No aplica, o ''.",
            "pressupost_afectat": "Compte: General, Material i Sortides, Menjador, Caixeta, Targeta Prepagament, o ''.",
            "responsable_nom": "Persona responsable de la compra.",
            "responsable_email": "Correu de la persona responsable.",
            "validat": "1 si secretaria l'ha validat, 0 si no.",
            "status": "needs_validation (per revisar), validated, error, pending/processing (s'està llegint).",
            "request_id": "La sol·licitud (requests.id) a què respon, o NULL.",
            "created_by_id": "Qui l'ha entrat (users.id).",
            "created_at": "Quan es va entrar, 'AAAA-MM-DDTHH:MM:SS' (UTC).",
            "updated_at": "Darrer canvi, 'AAAA-MM-DDTHH:MM:SS' (UTC).",
        },
    ),
    "bank_movements": (
        "Moviments bancaris dels extractes importats (i de la caixeta).",
        {
            "id": "Clau; l'API la fa servir com a {movement_id}.",
            "import_id": "L'extracte (statement_imports.id).",
            "compte": "General, Material i Sortides, Menjador, Caixeta o Targeta Prepagament.",
            "source": "caixa_xls, prepaid_pdf o caixeta_sheet.",
            "tipus": "Com s'ha mogut els diners (mètode de pagament).",
            "categoria": "pagament (hauria de tenir factura), comissio, traspas_intern, ingres, devolucio, saldo_inicial.",
            "data": "Data del moviment, 'AAAA-MM-DD'.",
            "data_valor": "Data valor, 'AAAA-MM-DD'.",
            "concepte": "Concepte del banc.",
            "mes_dades": "Més dades del banc.",
            "import_value": "Import en euros; negatiu és una sortida de diners.",
            "saldo": "Saldo després del moviment.",
            "codi": "Codi intern de la línia (TP_007, MEN_112, Cix_012…).",
            "num_factura_hint": "Número de factura que esmenta el banc, si n'hi ha.",
            "cif_hint": "CIF que esmenta el banc, si n'hi ha.",
            "match_status": "unmatched, proposed, confirmed (justificat), rejected o not_applicable.",
            "linked_movement_id": "L'altra meitat d'un traspàs intern.",
        },
    ),
    "statement_imports": (
        "Extractes bancaris importats.",
        {
            "id": "Clau; l'API la fa servir com a {statement_id}.",
            "source": "caixa_xls, prepaid_pdf o caixeta_sheet.",
            "compte": "El compte de l'extracte.",
            "file_name": "Nom del fitxer.",
            "status": "Estat de la importació.",
            "period_from": "Primer dia que cobreix.",
            "period_to": "Darrer dia que cobreix.",
            "rows_total": "Línies llegides.",
            "rows_new": "Línies noves.",
            "rows_duplicate": "Línies que ja hi eren.",
            "created_at": "Quan es va importar.",
        },
    ),
    "payment_matches": (
        "Justificacions: quin document paga quin moviment.",
        {
            "id": "Clau; l'API la fa servir com a {match_id}.",
            "movement_id": "bank_movements.id.",
            "document_id": "documents.id.",
            "confidence": "Confiança 0–100.",
            "rank": "0 és la proposta principal.",
            "decided_by": "rules, openai, jev, jev+openai o person.",
            "reason": "Per què.",
            "status": "proposed, alternative, confirmed o rejected.",
            "confirmed_by_id": "Qui la va confirmar (users.id).",
            "confirmed_at": "Quan.",
        },
    ),
    "requests": (
        "Sol·licituds del professorat: compres, pressupostos, consultes, reemborsaments.",
        {
            "id": "Clau; l'API la fa servir com a {request_id}.",
            "kind": "compra, pressupost, consulta o reemborsament.",
            "title": "Títol.",
            "description": "Descripció.",
            "amount": "Import estimat o pagat.",
            "proveidor": "Proveïdor.",
            "compte": "Compte d'on sortiria.",
            "needed_by": "Per a quan.",
            "status": "oberta, en_revisio, aprovada, rebutjada, resolta o cancellada.",
            "requester_id": "Qui la demana (users.id).",
            "assignee_id": "Qui la porta (users.id).",
            "created_at": "Quan es va crear.",
            "last_activity_at": "Darrera activitat.",
        },
    ),
    "request_messages": (
        "Missatges i canvis d'estat de cada sol·licitud.",
        {
            "id": "Clau.",
            "request_id": "requests.id.",
            "author_id": "users.id.",
            "kind": "message o status.",
            "body": "Text.",
            "status": "Per a un canvi d'estat, l'estat nou.",
            "created_at": "Quan.",
        },
    ),
    "users": (
        "Comptes del hub (sense cap dada d'accés).",
        {
            "id": "Clau.",
            "email": "Correu.",
            "display_name": "Nom.",
            "role": "admin, secretaria o professor.",
            "is_active": "1 si el compte és actiu.",
            "last_login_at": "Darrer inici de sessió.",
        },
    ),
    "responsables": (
        "Persones responsables de compres que el registre ha vist.",
        {"id": "Clau.", "nom": "Nom.", "email": "Correu.", "uses": "Quants documents."},
    ),
    "history_actions": (
        "El que s'ha fet al hub i es pot desfer, una fila per acció.",
        {
            "id": "Clau.",
            "label": "Què es va fer.",
            "kind": "person o auto.",
            "user_id": "Qui (users.id).",
            "state": "done, undone o dropped.",
            "created_at": "Quan.",
        },
    ),
}

#: Plain functions a query may call; anything else is refused.
FUNCTIONS = {
    # aggregates and windows
    "avg", "count", "group_concat", "string_agg", "max", "min", "sum", "total",
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile",
    "lag", "lead", "first_value", "last_value", "nth_value",
    # scalars
    "abs", "coalesce", "ifnull", "iif", "nullif", "instr", "length", "lower", "upper",
    "ltrim", "rtrim", "trim", "replace", "substr", "substring", "printf", "format",
    "round", "sign", "like", "glob", "char", "unicode", "typeof", "hex", "quote",
    # dates
    "date", "time", "datetime", "julianday", "strftime", "unixepoch", "timediff",
    # math, where SQLite was built with it
    "ceil", "ceiling", "floor", "trunc", "sqrt", "pow", "power", "exp", "ln", "log",
    "log2", "log10", "mod", "pi",
}

MAX_ROWS = 500
TIME_BUDGET_SECONDS = 3.0


class QueryRefused(ValueError):
    """The query could not be run; the message is fit to show the model."""


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False


def schema_text() -> str:
    """The copy as the model is told about it."""
    lines = ["Base de dades SQLite (només lectura). Taules i columnes:"]
    for table, (about, columns) in TABLES.items():
        lines.append(f"\n## {table} — {about}")
        lines += [f"- {name}: {meaning}" for name, meaning in columns.items()]
    return "\n".join(lines)


def _sql_type(column) -> str:
    kind = column.type
    if isinstance(kind, (Integer, Boolean)):
        return "INTEGER"
    if isinstance(kind, Float):
        return "REAL"
    return "TEXT"


def _value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None, microsecond=0).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _authorize(action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 in TABLES else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if (arg2 or "").lower() in FUNCTIONS else sqlite3.SQLITE_DENY
    if action == getattr(sqlite3, "SQLITE_RECURSIVE", -1):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class Sandbox:
    """A throwaway, read-only copy of :data:`TABLES`, built on first use."""

    def __init__(self, session: Session):
        self._session = session
        self._connection: sqlite3.Connection | None = None

    def _load(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        for name, (_, wanted) in TABLES.items():
            table = Base.metadata.tables[name]
            columns = [table.c[column] for column in wanted if column in table.c]
            names = [column.name for column in columns]
            definition = ", ".join(f"{column.name} {_sql_type(column)}" for column in columns)
            connection.execute(f"CREATE TABLE {name} ({definition})")
            rows = self._session.execute(select(*columns)).yield_per(1000)
            connection.executemany(
                f"INSERT INTO {name} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                ([_value(value) for value in row] for row in rows),
            )
        connection.commit()
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_authorize)
        return connection

    def query(self, sql: str, max_rows: int = MAX_ROWS) -> QueryResult:
        """Run one read-only ``SELECT``. Raises :class:`QueryRefused`."""
        statement = (sql or "").strip().rstrip(";").strip()
        if not statement:
            raise QueryRefused("No hi ha cap consulta.")
        if ";" in statement:
            raise QueryRefused("Només s'admet una consulta alhora.")
        if not statement.lower().startswith(("select", "with")):
            raise QueryRefused("Només s'admeten consultes de lectura (SELECT o WITH).")
        if self._connection is None:
            self._connection = self._load()
        connection = self._connection
        deadline = time.monotonic() + TIME_BUDGET_SECONDS
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        try:
            cursor = connection.execute(statement)
            rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.Warning as exc:
            raise QueryRefused("Només s'admet una consulta alhora.") from exc
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            if "interrupted" in message:
                raise QueryRefused("La consulta trigava massa; simplifica-la.") from exc
            if "not authorized" in message or "prohibited" in message:
                raise QueryRefused(
                    "La consulta fa servir alguna cosa no permesa (només es pot llegir les taules descrites)."
                ) from exc
            raise QueryRefused(f"La consulta no és vàlida: {message}") from exc
        finally:
            connection.set_progress_handler(None, 0)
        columns = [description[0] for description in cursor.description or []]
        return QueryResult(
            columns=columns,
            rows=[list(row) for row in rows[:max_rows]],
            truncated=len(rows) > max_rows,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
