"""The prepaid card's statement: a CaixaBank printout saved as an image-only PDF.

There is no text layer to parse, so the vision model reads it, with the same
strict-schema call the register's extraction uses. It is also asked what the
document *is*, so a PDF dropped here by mistake is refused instead of turned
into nonsense movements.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from ..llm import FileExtractionRequest, LLMError, LLMRegistry
from ..text_format import parse_amount, parse_date
from . import INTERNAL, PAYMENT, SOURCE_PREPAID, ParsedMovement, ParsedStatement, StatementError

PREPAID = "Targeta de prepagament"

PROMPT = """
Ets l'assistent de comptabilitat d'un institut. El PDF adjunt hauria de ser un extracte de la
targeta de prepagament de CaixaBank ("Targeta TARJETA PREPAGO EMPRESA"), imprès des de la web
del banc: una capçalera amb el número de targeta, el contracte i els totals, i una taula
"Establiment | Data operació | Import".

Regles:
- Respon estrictament amb l'esquema.
- Si el document no és un extracte d'una targeta de prepagament, kind = "other" i deixa la resta buit.
- Copia cada fila de la taula, en l'ordre en què surt, sense ometre'n cap.
- Les dates en format dd/mm/aaaa. Els imports amb el signe que porten (les recàrregues són positives).
""".strip()


class PrepaidRow(BaseModel):
    establiment: str = Field(default="", description="Nom de l'establiment, tal com surt.")
    data: str = Field(default="", description="Data de l'operació, dd/mm/aaaa.")
    import_: str = Field(default="", alias="import", description="Import amb signe, p. ex. -11,75.")


class PrepaidExtraction(BaseModel):
    kind: str = Field(
        default="other", description='"prepaid_statement" si és un extracte de targeta de prepagament; si no, "other".'
    )
    card_number: str = Field(default="", description="Número de la targeta, p. ex. 4000 0000 0000 0000.")
    contract: str = Field(default="", description="Número de contracte.")
    print_date: str = Field(default="", description="Data d'impressió, dd/mm/aaaa.")
    month_operations: str = Field(
        default="", description="L'import d'\"Operacions <mes>\" de la capçalera, si hi és."
    )
    balance: str = Field(default="", description="El saldo de la capçalera, si hi és.")
    rows: list[PrepaidRow] = Field(default_factory=list)


def _card(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    return " ".join(digits[i : i + 4] for i in range(0, len(digits), 4))


def read(registry: LLMRegistry, file_path: Path, *, model: str | None = None) -> ParsedStatement:
    try:
        result = registry.get().extract_file(
            FileExtractionRequest(
                file_path=file_path,
                mime_type="application/pdf",
                json_schema=PrepaidExtraction.model_json_schema(by_alias=True),
                schema_name="prepaid_statement",
                prompt="Llegeix aquest extracte de la targeta de prepagament.",
                instructions=PROMPT,
                model=model,
            )
        )
        raw = PrepaidExtraction.model_validate(result.data)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 — a schema mismatch is a model failure
        raise LLMError("The model returned a payload that does not match the prepaid schema.") from exc
    return to_statement(raw)


def to_statement(raw: PrepaidExtraction) -> ParsedStatement:
    if raw.kind != "prepaid_statement":
        raise StatementError(
            "Aquest PDF no sembla un extracte de la targeta de prepagament. "
            "Els PDF que es deixen aquí han de ser l'extracte imprès de CaixaBank."
        )
    card = _card(raw.card_number)
    seen: Counter[tuple] = Counter()
    movements: list[ParsedMovement] = []
    for row in raw.rows:
        when = parse_date(row.data)
        amount = parse_amount(row.import_)
        name = " ".join(row.establiment.split())
        if when is None or amount is None or not name:
            continue
        key = (when, name.upper(), round(amount, 2))
        seen[key] += 1
        top_up = amount > 0 or name.upper().startswith(("RECARGA", "CARREGA"))
        movements.append(
            ParsedMovement(
                data=when,
                concepte=name,
                import_value=round(amount, 2),
                tipus=PREPAID,
                categoria=INTERNAL if top_up else PAYMENT,
                # The same shop, day and amount twice is two coffees, not a duplicate.
                identity=(SOURCE_PREPAID, card, *key, seen[key]),
                raw=row.model_dump(by_alias=True),
            )
        )
    if not movements:
        raise StatementError("No s'ha trobat cap moviment a l'extracte de la targeta.")

    warnings: list[str] = []
    month_total = parse_amount(raw.month_operations)
    printed = parse_date(raw.print_date)
    if month_total is not None and printed is not None:
        spent = sum(
            -m.import_value
            for m in movements
            if m.import_value < 0 and m.data and (m.data.year, m.data.month) == (printed.year, printed.month)
        )
        if abs(spent - abs(month_total)) > 0.01:
            warnings.append(
                f"Les operacions del mes sumen {spent:.2f} € però la capçalera diu {abs(month_total):.2f} €."
            )
    return ParsedStatement(
        source=SOURCE_PREPAID,
        movements=movements,
        account_iban=card,
        compte="Targeta Prepagament",
        meta={
            "card_number": card,
            "contract": raw.contract,
            "print_date": printed.isoformat() if printed else None,
            "balance": parse_amount(raw.balance),
            "warnings": warnings,
        },
    )
