"""esfer@'s "Dades del pressupost" export, read without a model.

Where to find it: *Informes i extraccions → Consulta les dades del pressupost →
Exporta XLS*. The sheet has a header block (centre, NIF, code, year), then one
table:

    Tipus | Codi partida | Codi finalista | Nom partida | Import Pressupost

``Ingressos`` and ``Despeses`` open their sections in the first column. A
sub-line is indented with spaces in every cell and its code extends its
parent's (``D/220000100/4210`` → ``D/220000100/4210.24``).

Run it on a file to see what it reads::

    uv run python -m cosecre_hub.api.partides.esfera "Dades del pressupost.xls"
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...services.statements import StatementError
from ...services.statements.caixa_xls import read_rows
from ...services.text_format import parse_amount


class BudgetFileError(ValueError):
    pass


@dataclass
class ParsedPartida:
    tipus: str
    codi: str
    codi_pare: str | None
    codi_finalista: str
    nom: str
    import_pressupost: float
    ordre: int


@dataclass
class ParsedBudget:
    exercici: int
    centre: str = ""
    nif: str = ""
    codi_centre: str = ""
    data_informe: str = ""
    total_ingressos: float | None = None
    total_despeses: float | None = None
    partides: list[ParsedPartida] = field(default_factory=list)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text).strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _amount(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    parsed = parse_amount(_text(value))
    return float(parsed) if parsed is not None else 0.0


_LABELLED = re.compile(r"^\s*(Nom|Nif|Codi|Exercici|Data|Tipus)\s*:\s*(.*?)\s*$", re.IGNORECASE)
_TOTAL = re.compile(r"Total\s+(Ingressos|Despeses)\s+([\d.,]+)", re.IGNORECASE)


def parse(content: bytes, file_name: str = "") -> ParsedBudget:
    try:
        rows = read_rows(content, file_name)
    except StatementError as exc:
        raise BudgetFileError(
            "No s'ha pogut llegir el fitxer. Ha de ser l'Excel de «Dades del pressupost» d'esfer@."
        ) from exc

    labels: dict[str, str] = {}
    header_index = None
    totals: dict[str, float] = {}
    for index, row in enumerate(rows):
        cells = [_text(c) for c in row]
        folded = [_fold(c) for c in cells]
        if "codi partida" in folded and "nom partida" in folded:
            header_index = index
            columns = {name: folded.index(name) for name in folded if name}
            break
        for cell in cells:
            match = _LABELLED.match(cell)
            if match and match.group(2):
                labels.setdefault(match.group(1).lower(), match.group(2))
            total = _TOTAL.search(cell)
            if total:
                totals[total.group(1).lower()] = _amount(total.group(2))

    if header_index is None:
        raise BudgetFileError(
            "Aquest Excel no té la taula de partides (falten les columnes «Codi partida» i "
            "«Nom partida»). Exporta'l des d'esfer@: Informes i extraccions → Consulta les "
            "dades del pressupost → Exporta XLS."
        )
    try:
        exercici = int(re.sub(r"\D", "", labels.get("exercici", "")) or 0)
    except ValueError:
        exercici = 0
    if not 2000 <= exercici <= 2100:
        raise BudgetFileError("No s'ha trobat l'exercici del pressupost a la capçalera de l'Excel.")

    budget = ParsedBudget(
        exercici=exercici,
        centre=labels.get("nom", ""),
        nif=labels.get("nif", "").replace(" ", "").upper(),
        codi_centre=labels.get("codi", ""),
        data_informe=labels.get("data", ""),
    )

    col_type = columns.get("tipus", 0)
    col_code = columns["codi partida"]
    col_fund = columns.get("codi finalista")
    col_name = columns["nom partida"]
    col_amount = columns.get("import pressupost")

    def cell(row: list[Any], col: int | None) -> Any:
        return row[col] if col is not None and col < len(row) else None

    section = ""
    parent: str | None = None
    seen: set[str] = set()
    for row in rows[header_index + 1 :]:
        section_cell = _fold(_text(cell(row, col_type)))
        if section_cell.startswith("ingress"):
            section, parent = "ingres", None
            continue
        if section_cell.startswith("despes"):
            section, parent = "despesa", None
            continue

        raw_code = _text(cell(row, col_code))
        name = _text(cell(row, col_name)).strip()
        if not raw_code.strip():
            total = _fold(name)
            if total.startswith("total ingressos"):
                budget.total_ingressos = _amount(cell(row, col_amount))
            elif total.startswith("total despeses"):
                budget.total_despeses = _amount(cell(row, col_amount))
            continue
        if not section:
            continue

        code = raw_code.strip()
        indented = raw_code[:1].isspace() or (parent is not None and code.startswith(parent + "."))
        if code in seen:
            continue
        seen.add(code)
        budget.partides.append(
            ParsedPartida(
                tipus=section,
                codi=code,
                codi_pare=parent if indented else None,
                codi_finalista=_text(cell(row, col_fund)).strip(),
                nom=re.sub(r"\s+", " ", name),
                import_pressupost=_amount(cell(row, col_amount)),
                ordre=len(budget.partides),
            )
        )
        if not indented:
            parent = code

    if budget.total_ingressos is None:
        budget.total_ingressos = totals.get("ingressos")
    if budget.total_despeses is None:
        budget.total_despeses = totals.get("despeses")
    if not budget.partides:
        raise BudgetFileError("L'Excel no té cap partida.")
    return budget


# ── Funds ───────────────────────────────────────────────────────────────────
# A codi finalista names a fund *and* a year (MOTXILLES2526, PlaDeXoc25_26). The
# family without the year is what people think in, and what the picker colours.

_FAMILY_LABELS = {
    "MOTXILLES": "Motxilles escolars",
    "PLADEXOC": "Pla de Xoc",
    "FAMILIESMATERIAL": "Famílies · material",
    "FAMMAT": "Famílies · material",
    "FAMILIESSORTIDES": "Famílies · sortides",
    "FAMLLIBRES": "Famílies · llibres",
    "FAMSOCI": "Famílies · socialització",
    "PMOEPROA": "PMOE / PROA+",
    "ASSIGLLIBRESTEXT": "Dotació llibres i llicències",
    "ROBOTICA": "Robòtica",
}


def fund_family(codi_finalista: str) -> tuple[str, str]:
    """``(key, label)`` of a codi finalista's fund; ``("", …)`` for the ordinary budget."""
    code = codi_finalista.strip().upper()
    if not code:
        return "", "Pressupost ordinari"
    key = re.sub(r"_?FSE$", "", code)
    key = re.sub(r"[\d_]+$", "", key).replace("_", "")
    key = key or code
    if key == "FAMMAT":
        key = "FAMILIESMATERIAL"
    return key, _FAMILY_LABELS.get(key, key.capitalize())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    budget = parse(path.read_bytes(), path.name)
    print(json.dumps(asdict(budget), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
