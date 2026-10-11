"""Any table's search, asked for in plain words.

The register has its own reading (:mod:`.ai_filter`), tuned to its columns and
able to answer figures. Every other list — a statement's movements, the
requests — describes its own filters instead: what it lists, which closed lists
it filters by, and whether it has a date or an amount range. The same pipeline
then turns a question into those filters:

1. **Jev** first: one closed question per filter, the period when there is a
   date range, and whether anything open (a name, a number, an amount, a date)
   has to be read out of the sentence.
2. **The language model** only when Jev cannot finish alone — it is off,
   unsure, the question has something open, or digits.

Nothing here reads the hub's data: the answer is filters for the client to
apply to a list it already holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field, create_model

from .ai_filter import FIELDS as REGISTER_FIELDS
from .ai_filter import JEV_ALONE, JEV_DECIDES, NONE, AiFilter, AiFilterUnavailable, FieldReading, period_range
from .classification import JevClient, JevError, Question
from .llm import LLMError, LLMRegistry
from .llm.base import Message, StructuredRequest

logger = logging.getLogger(__name__)

PERIOD = "periode"
OPEN = "obert"
_NOT_ASKED = "La cerca no en diu res."


# ── What a table says about itself ───────────────────────────────────────────


class ChoiceOption(BaseModel):
    value: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    hint: str = Field(default="", max_length=200)


class ChoiceFilter(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,29}$")
    label: str = Field(min_length=1, max_length=60)
    options: list[ChoiceOption] = Field(min_length=1, max_length=30)


class RangeFilter(BaseModel):
    kind: Literal["date", "amount"]
    label: str = Field(min_length=1, max_length=60)
    #: The table's own filter names for each end.
    from_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,29}$")
    to_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,29}$")


class TableSpec(BaseModel):
    #: What the list holds, in a few words: "moviments d'un extracte bancari".
    subject: str = Field(min_length=3, max_length=200)
    #: What the free-text search looks through: "concepte, import, factura".
    search_hint: str = Field(default="", max_length=200)
    filters: list[ChoiceFilter] = Field(default_factory=list, max_length=8)
    ranges: list[RangeFilter] = Field(default_factory=list, max_length=2)

    def range_of(self, kind: str) -> RangeFilter | None:
        return next((r for r in self.ranges if r.kind == kind), None)


# ── Jev ──────────────────────────────────────────────────────────────────────


def _questions(spec: TableSpec) -> dict[str, Question]:
    questions: dict[str, Question] = {}
    for choice in spec.filters:
        options = {
            f"o{index}": (option.value, option.hint or f"Demana «{option.label}».")
            for index, option in enumerate(choice.options)
        }
        options[NONE] = ("", _NOT_ASKED)
        questions[choice.name] = Question(
            instructions=f"A la llista de {spec.subject}, quin valor de «{choice.label}» demana la cerca?",
            options=options,
        )
    if spec.range_of("date"):
        questions[PERIOD] = REGISTER_FIELDS["periode"]
    questions[OPEN] = Question(
        instructions=(
            "A més d'aquests filtres, la cerca demana alguna cosa concreta que s'hagi de llegir de la "
            "frase: un nom, un número, un import, una data o un mes concret, o paraules per buscar?"
        ),
        options={
            "si": ("si", "Sí: hi ha un nom, número, import, data o paraules concretes."),
            "no": ("no", "No: només els filtres de llista o un període com «aquest mes»."),
        },
    )
    return questions


def _state(spec: TableSpec, query: str, today: date) -> str:
    return (
        f"Una persona de la secretaria d'un institut cerca a la llista de {spec.subject}. "
        f"Avui és {today.isoformat()}.\nLa seva cerca: «{query}»"
    )


def _ask_jev(jev: JevClient | None, spec: TableSpec, query: str, today: date):
    if jev is None:
        return None, "off"
    try:
        return jev.decide(_state(spec, query, today), _questions(spec)), "ok"
    except JevError:
        logger.warning("Jev could not read the search", exc_info=True)
        return None, "error"


def jev_is_enough(spec: TableSpec, query: str, answers: dict | None) -> bool:
    if not answers or any(char.isdigit() for char in query):
        return False
    for name in _questions(spec):
        answer = answers.get(name)
        if answer is None or answer.confidence < JEV_DECIDES:
            return False
    return answers[OPEN].label == "no"


# ── The language model ───────────────────────────────────────────────────────


def _reading_model(spec: TableSpec) -> type[BaseModel]:
    fields: dict = {}
    for choice in spec.filters:
        values = tuple(option.value for option in choice.options) + (NONE,)
        described = "; ".join(
            f"«{o.value}» = {o.label}{f' ({o.hint})' if o.hint else ''}" for o in choice.options
        )
        fields[choice.name] = (Literal[values], Field(description=f"{choice.label}. {described}. '{NONE}' si no en diu res."))
    if spec.range_of("date"):
        periods = tuple(REGISTER_FIELDS["periode"].options)
        fields[PERIOD] = (Literal[periods], Field(description="Període relatiu, o 'cap' si dona dates concretes o cap."))
        fields["date_from"] = (str, Field(description="Data inicial explícita AAAA-MM-DD, o buit."))
        fields["date_to"] = (str, Field(description="Data final explícita AAAA-MM-DD, o buit."))
    if spec.range_of("amount"):
        fields["amount_min"] = (Optional[float], Field(description="Import mínim en euros (sense signe), o null."))
        fields["amount_max"] = (Optional[float], Field(description="Import màxim en euros (sense signe), o null."))
    fields["text"] = (
        str,
        Field(
            description=(
                "Les paraules mínimes i distintives per a la cerca de text lliure"
                + (f" (busca a: {spec.search_hint})" if spec.search_hint else "")
                + ". Buit si no n'hi ha. Mai hi posis paraules que ja són un filtre."
            )
        ),
    )
    fields["explanation"] = (str, Field(description="Una frase curta en català: què s'ha entès que es busca."))
    return create_model("TableSearchReading", **fields)


def _ask_model(registry: LLMRegistry, spec: TableSpec, query: str, today: date):
    model = _reading_model(spec)
    try:
        provider = registry.get()
        if not provider.is_configured():
            return None, "off"
        result = provider.structured(
            StructuredRequest(
                messages=[Message(role="user", content=_state(spec, query, today))],
                schema_name="table_search",
                json_schema=model.model_json_schema(),
                instructions=(
                    f"Converteixes una cerca en llenguatge natural sobre {spec.subject} en els filtres "
                    f"d'aquesta llista. Respon només amb els valors permesos; posa '{NONE}' quan la cerca "
                    "no en diu res d'un filtre. Les dates relatives van al període; les concretes, a "
                    "date_from/date_to. El curs escolar va de setembre a agost."
                ),
            )
        )
        return model.model_validate(result.data), "ok"
    except (LLMError, ValueError):
        logger.warning("The language model could not read the search", exc_info=True)
        return None, "error"


# ── Putting it together ──────────────────────────────────────────────────────


def _merge(jev_answer, model_value: str | None) -> FieldReading | None:
    if jev_answer is not None:
        if model_value is not None and jev_answer.label == model_value:
            return FieldReading(jev_answer.label, "jev+openai", jev_answer.confidence) if model_value else None
        if jev_answer.confidence >= JEV_DECIDES or (model_value is None and jev_answer.confidence >= JEV_ALONE):
            return FieldReading(jev_answer.label, "jev", jev_answer.confidence) if jev_answer.label else None
    if model_value:
        return FieldReading(model_value, "openai")
    return None


def _iso(value: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat() if value.strip() else ""
    except ValueError:
        return ""


def _amount(value: float | None) -> str:
    if value is None:
        return ""
    return f"{abs(value):.2f}".rstrip("0").rstrip(".")


def _describe(spec: TableSpec, result: AiFilter, period: str | None) -> str:
    parts = []
    for choice in spec.filters:
        value = result.filters.get(choice.name)
        if value:
            label = next((o.label for o in choice.options if o.value == value), value)
            parts.append(f"{choice.label}: {label}")
    if period and (span := REGISTER_FIELDS["periode"].options.get(period)):
        parts.append(span[1].rstrip("."))
    return (" · ".join(parts) + ".") if parts else "Tota la llista."


def read_search(spec: TableSpec, query: str, registry: LLMRegistry, jev: JevClient | None, today: date) -> AiFilter:
    """Turn ``query`` into ``spec``'s filters. Raises when no model is reachable."""
    answers, jev_status = _ask_jev(jev, spec, query, today)
    if jev_is_enough(spec, query, answers):
        reading, model_status = None, "skipped"
    else:
        reading, model_status = _ask_model(registry, spec, query, today)

    result = AiFilter(models={"jev": jev_status, "openai": model_status})
    if answers is None and reading is None:
        raise AiFilterUnavailable("Ara mateix no hi ha cap model disponible per entendre la cerca.")
    answers = answers or {}

    def model_value(name: str) -> str | None:
        if reading is None:
            return None
        value = getattr(reading, name, None)
        return "" if value == NONE else value

    for choice in spec.filters:
        merged = _merge(answers.get(choice.name), model_value(choice.name))
        if merged and any(o.value == merged.value for o in choice.options):
            result.filters[choice.name] = merged.value
            result.sources[choice.name] = merged

    period_key = None
    if dates := spec.range_of("date"):
        merged = _merge(answers.get(PERIOD), model_value(PERIOD))
        if merged and (span := period_range(merged.value, today)):
            period_key = merged.value
            result.filters[dates.from_name], result.filters[dates.to_name] = span[0].isoformat(), span[1].isoformat()
            result.sources[dates.from_name] = result.sources[dates.to_name] = merged
        if reading is not None:
            for name, value in ((dates.from_name, _iso(reading.date_from)), (dates.to_name, _iso(reading.date_to))):
                if value:
                    result.filters[name] = value
                    result.sources[name] = FieldReading(value, "openai")

    if reading is not None:
        if amounts := spec.range_of("amount"):
            for name, value in ((amounts.from_name, _amount(reading.amount_min)), (amounts.to_name, _amount(reading.amount_max))):
                if value:
                    result.filters[name] = value
                    result.sources[name] = FieldReading(value, "openai")
        result.search = reading.text.strip()
        result.explanation = reading.explanation.strip()
    else:
        result.explanation = _describe(spec, result, period_key)
    return result


__all__ = ["TableSpec", "read_search"]
