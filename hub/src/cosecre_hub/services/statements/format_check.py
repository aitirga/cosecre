"""A second pair of eyes on a dropped Excel, before anything is parsed.

The parser is strict about *structure* (it needs the header row), but a file
can have that structure and still be the wrong thing: another bank's export, a
hand-made summary, a statement with its columns shifted. gpt-6-luna reads the
first rows as text and says whether this is a CaixaBank "Moviments del compte"
export, and what is off if not.

It is advisory when it cannot answer — no key, the API down — so a model outage
never blocks bringing a statement in; the parser's own checks still apply.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from ..llm import LLMError, LLMRegistry, Message, StructuredRequest

logger = logging.getLogger(__name__)

#: Enough to see the title, the header and a handful of movements.
PREVIEW_ROWS = 14

INSTRUCTIONS = """
Ets l'assistent de comptabilitat d'un institut. Et passo les primeres files d'un Excel que algú
ha deixat a l'apartat d'extractes bancaris. Comprova si és l'exportació "Moviments del compte"
de CaixaBank, que té aquest format exacte:

- Una fila de títol: "Moviments del compte <IBAN ES..> (CCC: ...)".
- Una fila "Imports expressats en euros".
- Una capçalera amb les columnes Data | Data valor | Moviment | Més dades | Import | Saldo.
- Una fila per moviment: dates (poden sortir com a números de sèrie d'Excel, p. ex. 46296),
  un concepte, dades addicionals, un import amb signe (negatiu = pagament) i el saldo.

Respon estrictament amb l'esquema. valid = true només si és aquest format. Si no ho és, o hi
veus alguna cosa estranya (columnes desplaçades, imports sense signe, un altre banc, un resum
fet a mà), explica-ho a issues en frases curtes en català.
""".strip()


class FormatVerdict(BaseModel):
    valid: bool = Field(description="És l'exportació de moviments de CaixaBank?")
    bank: str = Field(description="Banc que sembla haver generat el fitxer, o buit.")
    account_iban: str = Field(description="L'IBAN del títol, si hi és.")
    header_row: int = Field(description="Índex (0 = primera fila) de la capçalera, o -1.")
    confidence: float = Field(description="Confiança entre 0 i 1.")
    issues: list[str] = Field(description="Problemes trobats, en català. Buit si tot és correcte.")


@dataclass
class FormatCheck:
    #: ``ok``, ``rejected`` or ``unavailable`` (the model could not answer).
    status: str
    verdict: FormatVerdict | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def rejected(self) -> bool:
        return self.status == "rejected"

    def message(self) -> str:
        issues = "; ".join(self.verdict.issues) if self.verdict and self.verdict.issues else ""
        base = "Aquest Excel no sembla l'extracte de moviments de La Caixa."
        return f"{base} {issues}".strip()


def preview(rows: list[list[Any]], limit: int = PREVIEW_ROWS) -> str:
    """The first rows as numbered, tab-separated text."""
    lines = []
    for index, row in enumerate(rows[:limit]):
        cells = ["" if c is None else str(c).strip() for c in row]
        while cells and not cells[-1]:
            cells.pop()
        lines.append(f"{index}\t" + "\t".join(cells))
    return "\n".join(lines)


def check(registry: LLMRegistry, rows: list[list[Any]], *, model: str | None = None) -> FormatCheck:
    try:
        provider = registry.get()
        if not provider.is_configured():
            return FormatCheck(status="unavailable", warnings=["No s'ha pogut fer la comprovació amb IA (sense clau)."])
        result = provider.structured(
            StructuredRequest(
                messages=[Message(role="user", content=f"Primeres files de l'Excel:\n\n{preview(rows)}")],
                schema_name="statement_format_check",
                json_schema=FormatVerdict.model_json_schema(),
                instructions=INSTRUCTIONS,
                model=model,
            )
        )
        verdict = FormatVerdict.model_validate(result.data)
    except (LLMError, ValueError) as exc:
        logger.warning("Format check unavailable; relying on the parser", exc_info=True)
        return FormatCheck(
            status="unavailable",
            error=str(exc)[:300],
            warnings=["No s'ha pogut fer la comprovació amb IA; s'ha validat només l'estructura."],
        )
    if not verdict.valid:
        return FormatCheck(status="rejected", verdict=verdict)
    return FormatCheck(status="ok", verdict=verdict, warnings=list(verdict.issues))
