"""What the Assistent can do, as the model sees it, and what each does here.

Every tool either reads (the SQL sandbox, the API's ``GET`` routes), shows
(tables, charts, figures — *blocks* stored with the answer), or proposes. None
of them writes: see :mod:`.proposals`.

Tables and charts take a query rather than numbers typed by the model when
they can, so what is drawn is what the database says, not what the model
remembers it saying.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..llm import ToolSpec
from . import proposals
from .bridge import MAX_READ_CHARS, Bridge, BridgeRefused
from .sandbox import QueryRefused, Sandbox

#: Rows of a query result handed back to the model; the rest is summarised.
MODEL_ROWS = 150
MODEL_CHARS = 20_000
TABLE_ROWS = 500
CHART_POINTS = 240
CHART_SERIES = 8
CHART_KINDS = ("bar", "line", "area", "pie", "scatter")

_DATA_SCHEMA = {
    "type": "object",
    "description": "Dades escrites a mà, només si no surten d'una consulta.",
    "properties": {
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array", "items": {}}},
    },
}

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="run_sql",
        description=(
            "Executa una consulta SQLite de només lectura (SELECT/WITH) sobre una còpia de les dades i "
            "en retorna les files. Fes-la servir per comptar, sumar, agrupar, comparar o trobar les "
            "referències dels registres que s'han de canviar. Les dates són text 'AAAA-MM-DD'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Una sola consulta SELECT o WITH."},
                "purpose": {"type": "string", "description": "Què busques, en poques paraules (es mostra a l'usuari)."},
            },
            "required": ["sql"],
        },
    ),
    ToolSpec(
        name="show_table",
        description=(
            "Mostra una taula a l'usuari dins la resposta. Passa-hi `sql` perquè les dades surtin de la "
            "base de dades; fes servir àlies llegibles per a les columnes (AS \"Proveïdor\")."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "sql": {"type": "string", "description": "Consulta que dona la taula."},
                "data": _DATA_SCHEMA,
                "note": {"type": "string", "description": "Una línia sota la taula, opcional."},
            },
            "required": ["title"],
        },
    ),
    ToolSpec(
        name="show_chart",
        description=(
            "Dibuixa un gràfic dins la resposta. Amb `sql`: la primera columna són les etiquetes (eix X o "
            "porcions) i cada columna numèrica següent és una sèrie, amb el nom de la columna. "
            "Tipus: bar, line, area, pie, scatter. Fes servir line/area per a evolucions en el temps, "
            "bar per comparar categories, pie només amb poques parts d'un total."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "kind": {"type": "string", "enum": list(CHART_KINDS)},
                "sql": {"type": "string"},
                "data": _DATA_SCHEMA,
                "unit": {"type": "string", "description": "Unitat dels valors, p. ex. '€'."},
                "stacked": {"type": "boolean", "description": "Barres o àrees apilades."},
                "horizontal": {"type": "boolean", "description": "Barres horitzontals (etiquetes llargues)."},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["title", "kind"],
        },
    ),
    ToolSpec(
        name="show_metrics",
        description=(
            "Mostra unes quantes xifres clau en targetes (total gastat, documents pendents…). "
            "Els valors han de venir d'una consulta que ja hagis fet."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "value": {"type": "string", "description": "Ja formatat: '1.234,56 €'."},
                            "hint": {"type": "string"},
                        },
                        "required": ["label", "value"],
                    },
                },
            },
            "required": ["items"],
        },
    ),
    ToolSpec(
        name="list_api",
        description=(
            "Llista les rutes de l'API del hub (mètode, camí, paràmetres i cos). Filtra amb paraules: "
            "'documents', 'movements', 'requests'… Consulta-ho abans de proposar canvis."
        ),
        parameters={
            "type": "object",
            "properties": {"search": {"type": "string"}},
        },
    ),
    ToolSpec(
        name="call_api",
        description=(
            "Fa un GET a l'API del hub, amb els permisos de l'usuari, i en retorna el JSON. "
            "Per a dades que la base de dades no té en columnes (estat dels fulls, detall d'un moviment…)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Camí, p. ex. /documents/records/DOC-0042."},
                "params": {"type": "object", "description": "Paràmetres de consulta."},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        name="propose_changes",
        description=(
            "L'ÚNICA manera de canviar dades. Prepara una llista de crides a l'API (POST/PUT/PATCH/DELETE) "
            "que l'usuari veurà amb el valor d'abans i el de després, i que només s'aplicaran si les "
            "confirma. Una proposta per petició; fins a 200 accions. Els canvis aplicats es poden desfer."
        ),
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Què fa la proposta, en una frase."},
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": ["POST", "PUT", "PATCH", "DELETE"]},
                            "path": {"type": "string"},
                            "body": {"type": "object"},
                            "label": {"type": "string", "description": "Què fa aquesta acció, per a l'usuari."},
                        },
                        "required": ["method", "path"],
                    },
                },
            },
            "required": ["summary", "actions"],
        },
    ),
]

STATUS_TEXT = {
    "run_sql": "Consultant les dades…",
    "show_table": "Preparant la taula…",
    "show_chart": "Dibuixant el gràfic…",
    "show_metrics": "Resumint les xifres…",
    "list_api": "Mirant què permet l'API…",
    "call_api": "Llegint del hub…",
    "propose_changes": "Preparant la proposta de canvis…",
}


@dataclass
class ToolOutcome:
    #: What the model reads back.
    output: str
    #: Blocks to add to the answer, in order.
    blocks: list[dict[str, Any]] = field(default_factory=list)


class ToolError(ValueError):
    pass


class Toolbox:
    def __init__(self, session: Session, bridge: Bridge, conversation_id: int):
        self.session = session
        self.bridge = bridge
        self.conversation_id = conversation_id
        self.sandbox = Sandbox(session)

    def close(self) -> None:
        self.sandbox.close()

    def run(self, name: str, raw_arguments: str) -> ToolOutcome:
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return self._failed(name, {}, "Els arguments no són JSON vàlid.")
        if not isinstance(arguments, dict):
            return self._failed(name, {}, "Els arguments han de ser un objecte.")
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return self._failed(name, arguments, f"No existeix l'eina {name}.")
        # SQLite without WAL: an open read would keep every other request from
        # committing, so none is held across a tool — and none is left after.
        self.session.commit()
        try:
            return handler(arguments)
        except (ToolError, QueryRefused, BridgeRefused, proposals.ProposalInvalid) as exc:
            self.session.rollback()
            return self._failed(name, arguments, str(exc))
        finally:
            self.session.commit()

    def _failed(self, name: str, arguments: dict[str, Any], message: str) -> ToolOutcome:
        step = _step(name, arguments, ok=False, detail=message)
        return ToolOutcome(output=f"Error: {message}", blocks=[step])

    # ── Reading ─────────────────────────────────────────────────────────────

    def _tool_run_sql(self, arguments: dict[str, Any]) -> ToolOutcome:
        sql = str(arguments.get("sql", ""))
        result = self.sandbox.query(sql)
        rows = result.rows[:MODEL_ROWS]
        payload = {
            "columns": result.columns,
            "rows": rows,
            "row_count": len(result.rows),
            "more_rows": result.truncated or len(result.rows) > MODEL_ROWS,
        }
        text = _fit(payload)
        detail = f"{len(result.rows)}{'+' if result.truncated else ''} files"
        return ToolOutcome(output=text, blocks=[_step("run_sql", arguments, ok=True, detail=detail)])

    def _tool_list_api(self, arguments: dict[str, Any]) -> ToolOutcome:
        search = str(arguments.get("search", ""))
        text = self.bridge.catalog(search)
        return ToolOutcome(
            output=text[:MAX_READ_CHARS],
            blocks=[_step("list_api", arguments, ok=True, detail=search or "tot")],
        )

    def _tool_call_api(self, arguments: dict[str, Any]) -> ToolOutcome:
        resolved = self.bridge.resolve("GET", str(arguments.get("path", "")))
        self.bridge.check_read(resolved)
        params = {**resolved.params, **{k: str(v) for k, v in (arguments.get("params") or {}).items()}}
        response = self.bridge.call("GET", resolved.path, params=params)
        if not response.ok:
            raise ToolError(f"{response.status_code}: {response.detail()}")
        text = json.dumps(response.data, ensure_ascii=False, default=str)
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + " …[retallat: demana menys dades o fes servir run_sql]"
        step = _step("call_api", {"path": resolved.path, **({"params": params} if params else {})}, ok=True,
                     detail=f"{response.status_code}")
        return ToolOutcome(output=text, blocks=[step])

    # ── Showing ─────────────────────────────────────────────────────────────

    def _data(self, arguments: dict[str, Any], limit: int) -> tuple[list[str], list[list[Any]], bool, str]:
        sql = str(arguments.get("sql") or "").strip()
        if sql:
            result = self.sandbox.query(sql, max_rows=limit)
            return result.columns, result.rows, result.truncated, sql
        data = arguments.get("data") or {}
        columns = [str(c) for c in data.get("columns") or []]
        rows = [list(r) if isinstance(r, list) else [r] for r in data.get("rows") or []]
        if not columns or not rows:
            raise ToolError("Cal `sql` o bé `data` amb columnes i files.")
        return columns, rows[:limit], len(rows) > limit, ""

    def _tool_show_table(self, arguments: dict[str, Any]) -> ToolOutcome:
        columns, rows, truncated, sql = self._data(arguments, TABLE_ROWS)
        block = {
            "type": "table",
            "title": str(arguments.get("title") or ""),
            "columns": columns,
            "rows": [[_cell(v) for v in row] for row in rows],
            "truncated": truncated,
            "note": str(arguments.get("note") or ""),
            "sql": sql,
        }
        output = f"Taula mostrada a l'usuari: {len(rows)} files, columnes {columns}."
        if not rows:
            output += " (Està buida: digues-ho a l'usuari.)"
        return ToolOutcome(output=output, blocks=[block])

    def _tool_show_chart(self, arguments: dict[str, Any]) -> ToolOutcome:
        kind = str(arguments.get("kind") or "bar")
        if kind not in CHART_KINDS:
            raise ToolError(f"Tipus de gràfic desconegut: {kind}.")
        columns, rows, truncated, sql = self._data(arguments, CHART_POINTS)
        if len(columns) < 2:
            raise ToolError("Un gràfic necessita una columna d'etiquetes i almenys una de valors.")
        labels = [_label(row[0]) for row in rows]
        series = []
        for position, name in enumerate(columns[1:], start=1):
            values = [_number(row[position]) if position < len(row) else None for row in rows]
            if any(value is not None for value in values):
                series.append({"name": name, "values": values})
        if not series:
            raise ToolError("Cap columna després de la primera té valors numèrics.")
        series = series[: 1 if kind == "pie" else CHART_SERIES]
        block = {
            "type": "chart",
            "kind": kind,
            "title": str(arguments.get("title") or ""),
            "labels": labels,
            "series": series,
            "unit": str(arguments.get("unit") or ""),
            "stacked": bool(arguments.get("stacked")),
            "horizontal": bool(arguments.get("horizontal")),
            "x_label": str(arguments.get("x_label") or columns[0]),
            "y_label": str(arguments.get("y_label") or ""),
            "note": str(arguments.get("note") or ""),
            "truncated": truncated,
            "sql": sql,
        }
        output = f"Gràfic mostrat: {len(labels)} punts, sèries {[s['name'] for s in series]}."
        if not labels:
            output += " (No hi ha dades: digues-ho a l'usuari.)"
        return ToolOutcome(output=output, blocks=[block])

    def _tool_show_metrics(self, arguments: dict[str, Any]) -> ToolOutcome:
        items = [
            {
                "label": str(item.get("label", ""))[:80],
                "value": str(item.get("value", ""))[:40],
                "hint": str(item.get("hint", ""))[:120],
            }
            for item in (arguments.get("items") or [])[:8]
            if isinstance(item, dict)
        ]
        if not items:
            raise ToolError("Cal almenys una xifra.")
        block = {"type": "metrics", "title": str(arguments.get("title") or ""), "items": items}
        return ToolOutcome(output=f"{len(items)} xifres mostrades.", blocks=[block])

    # ── Proposing ───────────────────────────────────────────────────────────

    def _tool_propose_changes(self, arguments: dict[str, Any]) -> ToolOutcome:
        proposal = proposals.create(
            self.session,
            self.bridge,
            self.conversation_id,
            str(arguments.get("summary") or ""),
            arguments.get("actions") or [],
        )
        changed = sum(len(action["changes"]) for action in proposal.actions)
        output = (
            f"Proposta #{proposal.id} creada amb {len(proposal.actions)} accions ({changed} camps). "
            "L'usuari la veu amb els valors d'abans i de després i ha de prémer «Aplica». "
            "Encara NO s'ha canviat res: no diguis que està fet; explica què farà i què cal revisar."
        )
        return ToolOutcome(output=output, blocks=[{"type": "proposal", "proposal_id": proposal.id}])


def _step(tool: str, arguments: dict[str, Any], *, ok: bool, detail: str) -> dict[str, Any]:
    step: dict[str, Any] = {"type": "step", "tool": tool, "ok": ok, "detail": detail[:500]}
    if arguments.get("purpose"):
        step["purpose"] = str(arguments["purpose"])[:200]
    if arguments.get("sql"):
        step["sql"] = str(arguments["sql"])[:4000]
    if tool == "call_api" and arguments.get("path"):
        step["path"] = str(arguments["path"])
    if tool == "list_api" and arguments.get("search"):
        step["search"] = str(arguments["search"])
    return step


def _fit(payload: dict[str, Any]) -> str:
    """JSON for the model, cut down by rows rather than mid-value when too long."""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    rows = payload["rows"]
    while len(text) > MODEL_CHARS and len(rows) > 5:
        rows = rows[: len(rows) // 2]
        text = json.dumps({**payload, "rows": rows, "more_rows": True}, ensure_ascii=False, default=str)
    return text[:MODEL_CHARS]


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)


def _label(value: Any) -> str:
    return "" if value is None else str(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    return None
