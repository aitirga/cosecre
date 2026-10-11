"""Filtering the register by asking for it in plain words.

"Factures pendents de la Papereria Pérez d'aquest curs" becomes the filters the
register already has — tipus, pagament, compte, estat, a date range — plus the
words to search for and an amount range.

Two models share the work, as they do when a document is read:

* **Jev** answers the closed questions (which type, which account, which
  period…). It only ever chooses among the options it is given, with a
  calibrated probability, so it cannot invent a filter value — but it cannot
  read a supplier's name, an amount or an exact date out of the sentence either.
* **The language model** reads everything, open parts included: the words to
  search, amounts, explicit dates, and a one-line reading to show back.

Where both answer a closed question, a confident Jev decides; otherwise the
language model's answer stands. Either one alone is enough to filter.
"""

from __future__ import annotations

import calendar
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .classification import JevClient, JevError, Question
from .llm import LLMError, LLMRegistry
from .llm.base import Message, StructuredRequest

logger = logging.getLogger(__name__)

#: Jev decides a closed question on its own from here up.
JEV_DECIDES = 0.85
#: Below this, a Jev answer nobody else backs up is not applied.
JEV_ALONE = 0.6

NONE = "cap"

# ── The closed questions ─────────────────────────────────────────────────────
# Each option: Jev's key → (the register filter's value, what it means). The
# filter values are exactly what the register's own filters use, so an answer
# can be applied as if a person had picked it.


_NOT_ASKED = "La cerca no en diu res."

FIELDS: dict[str, Question] = {
    "tipus": Question(
        instructions=(
            "Demana un tipus de document concret? A secretaria, «factures» o «documents» vol "
            "dir tot el registre: només és un tipus si el distingeix explícitament dels altres."
        ),
        options={
            "factura": (
                "Factura",
                "Demana explícitament factures completes, en contrast amb tiquets o simplificades.",
            ),
            "factura_simplificada": (
                "Factura simplificada",
                "Demana tiquets de caixa o factures simplificades (súper, botiga, bar, benzinera).",
            ),
            "pressupost": ("Pressupost", "Demana pressupostos, ofertes o proformes."),
            "albara": ("Albarà", "Demana albarans o notes de lliurament."),
            "tiquet_rebut": ("Tiquet de rebut", "Demana rebuts o justificants de pagament."),
            "altres": ("Altres", "Demana documents de tipus «Altres»."),
            NONE: (
                "",
                "No en demana cap de concret: parla de factures o documents en general, o no en diu res.",
            ),
        },
    ),
    "pagament": Question(
        instructions="Vol els documents ja pagats o els que falta pagar?",
        options={
            "pagat": ("Pagat", "Demana els ja pagats."),
            "pendent": ("Pendent de pagament", "Demana els pendents, per pagar, no pagats o deutes."),
            "altres": ("Altres", "Demana pagaments parcials, bestretes o abonaments."),
            "sense": ("—", "Demana els que no tenen indicat si estan pagats."),
            NONE: ("", _NOT_ASKED),
        },
    ),
    "compte": Question(
        instructions="De quin compte bancari de l'institut vol veure els documents?",
        options={
            "general": ("General", "El compte general."),
            "material": ("Material i Sortides", "El compte de material i sortides, excursions, colònies."),
            "menjador": ("Menjador", "El compte del menjador, càtering, servei de menjador."),
            "caixeta": ("Caixeta", "La caixeta, diners en efectiu."),
            "prepagament": ("Targeta Prepagament", "La targeta de prepagament."),
            "sense": ("—", "Els que encara no tenen compte assignat."),
            NONE: ("", _NOT_ASKED),
        },
    ),
    "estat": Question(
        instructions="En quin punt de la feina de secretaria vol els documents?",
        options={
            "per_revisar": ("needs_validation", "Per revisar o validar, pendents de confirmar."),
            "validats": ("validated", "Ja validats o confirmats."),
            "errors": ("error", "Amb error, que no s'han pogut llegir."),
            "en_curs": ("active", "Que s'estan llegint ara mateix."),
            "sense_extracte": (
                "unmatched",
                "Sense moviment bancari lligat, sense justificar a l'extracte, no conciliats.",
            ),
            "fora_full": ("outside", "Que no són al full de càlcul."),
            NONE: ("", _NOT_ASKED),
        },
    ),
    "enviat": Question(
        instructions="Vol només els documents que ha enviat el professorat?",
        options={
            "professorat": ("professorat", "Sí: enviats per professors o professores."),
            NONE: ("", _NOT_ASKED),
        },
    ),
    "periode": Question(
        instructions="De quin període de temps vol els documents?",
        options={
            "aquest_mes": ("aquest_mes", "Aquest mes."),
            "mes_passat": ("mes_passat", "El mes passat."),
            "aquest_trimestre": ("aquest_trimestre", "Aquest trimestre."),
            "trimestre_passat": ("trimestre_passat", "El trimestre passat."),
            "aquest_curs": ("aquest_curs", "Aquest curs escolar (de setembre a agost)."),
            "curs_passat": ("curs_passat", "El curs escolar passat."),
            "aquest_any": ("aquest_any", "Aquest any natural."),
            "any_passat": ("any_passat", "L'any passat."),
            NONE: ("", "No diu cap període, o dona dates o mesos concrets."),
        },
    ),
}

CLOSED = tuple(name for name in FIELDS if name != "periode")


# ── Periods ──────────────────────────────────────────────────────────────────


def _quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def period_range(period: str, today: date) -> tuple[date, date] | None:
    """A named period as ``(from, to)``, both inclusive."""
    if period == "aquest_mes":
        return today.replace(day=1), _month_end(today)
    if period == "mes_passat":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if period == "aquest_trimestre":
        start = _quarter_start(today)
        return start, _month_end(date(start.year, start.month + 2, 1))
    if period == "trimestre_passat":
        end = _quarter_start(today) - timedelta(days=1)
        return _quarter_start(end), end
    # A school year runs September to August.
    year = today.year if today.month >= 9 else today.year - 1
    if period == "aquest_curs":
        return date(year, 9, 1), date(year + 1, 8, 31)
    if period == "curs_passat":
        return date(year - 1, 9, 1), date(year, 8, 31)
    if period == "aquest_any":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if period == "any_passat":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return None


# ── The language model's reading ─────────────────────────────────────────────


def _enum(question: Question) -> list[str]:
    return list(question.options)


class ModelReading(BaseModel):
    """What the language model is asked to return."""

    tipus: str = Field(description=f"Una de: {', '.join(_enum(FIELDS['tipus']))}")
    pagament: str = Field(description=f"Una de: {', '.join(_enum(FIELDS['pagament']))}")
    compte: str = Field(description=f"Una de: {', '.join(_enum(FIELDS['compte']))}")
    estat: str = Field(description=f"Una de: {', '.join(_enum(FIELDS['estat']))}")
    enviat: str = Field(description=f"Una de: {', '.join(_enum(FIELDS['enviat']))}")
    periode: str = Field(description=f"Una de: {', '.join(_enum(FIELDS['periode']))}")
    date_from: str = Field(description="Data inicial explícita AAAA-MM-DD, o buit.")
    date_to: str = Field(description="Data final explícita AAAA-MM-DD, o buit.")
    amount_min: float | None = Field(description="Import mínim en euros, o null.")
    amount_max: float | None = Field(description="Import màxim en euros, o null.")
    text: str = Field(
        description=(
            "Les paraules mínimes i distintives per cercar: el nom propi d'un proveïdor "
            "(«Pérez», no «la papereria Pérez»), un número de factura, un CIF, un concepte. "
            "Buit si no n'hi ha. Mai hi posis paraules que ja són un filtre."
        )
    )
    explanation: str = Field(description="Una frase curta en català: què s'ha entès que es busca.")


INSTRUCTIONS = (
    "Converteixes una cerca en llenguatge natural sobre el registre de documents comptables "
    "d'un institut en filtres. Respon només amb els valors permesos de cada camp; posa "
    f"'{NONE}' quan la cerca no en diu res. 'Factures' en general no és un tipus: només "
    "posa tipus si la persona en demana un de concret. Les dates relatives (aquest mes, "
    "el curs passat…) van a 'periode'; les dates o mesos concrets, a date_from/date_to. "
    "Els tiquets de caixa (súper, botiga, bar, benzinera) són 'factura_simplificada'; "
    "'tiquet_rebut' és només un rebut o justificant de pagament. A 'text' només hi van "
    "noms que surtin escrits al document: «súper», «botiga» o «llibreria» no són noms de "
    "proveïdor i no s'hi posen."
)


# ── Result ───────────────────────────────────────────────────────────────────

Source = Literal["jev", "openai", "jev+openai"]


@dataclass
class FieldReading:
    value: str
    source: Source
    confidence: float | None = None


@dataclass
class AiFilter:
    #: Register filter name → value, only for what the question asked for.
    filters: dict[str, str] = field(default_factory=dict)
    search: str = ""
    explanation: str = ""
    sources: dict[str, FieldReading] = field(default_factory=dict)
    #: ``ok``, ``off`` or ``error``, per model.
    models: dict[str, str] = field(default_factory=dict)


class AiFilterUnavailable(RuntimeError):
    pass


def _state(query: str, today: date) -> str:
    return (
        "Una persona de la secretaria d'un institut cerca al registre de documents comptables "
        f"(factures, tiquets, pressupostos…). Avui és {today.isoformat()}.\n"
        f"La seva cerca: «{query}»"
    )


def _ask_jev(jev: JevClient | None, query: str, today: date):
    if jev is None:
        return None, "off"
    try:
        return jev.decide(_state(query, today), FIELDS), "ok"
    except JevError:
        logger.warning("Jev could not read the filter question", exc_info=True)
        return None, "error"


def _ask_model(registry: LLMRegistry, query: str, today: date):
    try:
        provider = registry.get()
        if not provider.is_configured():
            return None, "off"
        result = provider.structured(
            StructuredRequest(
                messages=[Message(role="user", content=_state(query, today))],
                schema_name="register_filter",
                json_schema=ModelReading.model_json_schema(),
                instructions=INSTRUCTIONS,
            )
        )
        return ModelReading.model_validate(result.data), "ok"
    except (LLMError, ValueError):
        logger.warning("The language model could not read the filter question", exc_info=True)
        return None, "error"


def _merge(name: str, jev_answer, model_key: str | None) -> FieldReading | None:
    """One closed field from the two opinions; ``None`` when it is not asked for."""
    question = FIELDS[name]
    model_value = question.label(model_key) if model_key else None
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
    if value is None or value < 0:
        return ""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def read_filter(query: str, registry: LLMRegistry, jev: JevClient | None, today: date) -> AiFilter:
    """Turn ``query`` into register filters. Raises when no model is reachable."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        jev_job = pool.submit(_ask_jev, jev, query, today)
        model_job = pool.submit(_ask_model, registry, query, today)
        jev_answers, jev_status = jev_job.result()
        reading, model_status = model_job.result()

    result = AiFilter(models={"jev": jev_status, "openai": model_status})
    if jev_answers is None and reading is None:
        raise AiFilterUnavailable("Ara mateix no hi ha cap model disponible per entendre la cerca.")

    jev_answers = jev_answers or {}
    for name in (*CLOSED, "periode"):
        merged = _merge(name, jev_answers.get(name), getattr(reading, name, None) if reading else None)
        if merged is None:
            continue
        if name == "periode":
            span = period_range(merged.value, today)
            if span:
                result.filters["des"], result.filters["fins"] = span[0].isoformat(), span[1].isoformat()
                result.sources["des"] = result.sources["fins"] = merged
            continue
        result.filters[name] = merged.value
        result.sources[name] = merged

    if reading is not None:
        # An explicit date beats a named period: "des del 3 de març" is precise.
        for key, value in (("des", _iso(reading.date_from)), ("fins", _iso(reading.date_to))):
            if value:
                result.filters[key] = value
                result.sources[key] = FieldReading(value, "openai")
        for key, value in (("min", _amount(reading.amount_min)), ("max", _amount(reading.amount_max))):
            if value:
                result.filters[key] = value
                result.sources[key] = FieldReading(value, "openai")
        result.search = reading.text.strip()
        result.explanation = reading.explanation.strip()
    return result

__all__ = ["AiFilter", "AiFilterUnavailable", "FIELDS", "period_range", "read_filter"]
