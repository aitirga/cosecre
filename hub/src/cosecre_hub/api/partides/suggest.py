"""Jev's preliminary budget line for an invoice.

One Choice over every expense line of the year (168 for a typical school, well
under Jev's 255 options), plus a "none fits" way out, and a yes/no on whether
the purchase spans more than one budget concept — asked together, so the
second costs no latency. Code keeps what is known for certain: the invoice's
school year, what this supplier was charged to before, and what the
secretari/a wrote about the lines and in general.

Nothing here is final. What Jev proposes is stored unconfirmed and shown in
violet until a person accepts or changes it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from ...models import Document
from ...services.classification import JevClient
from .esfera import fund_family
from .models import Partida

#: Jev's own limit is 255 options per Choice; one is the way out.
MAX_OPTIONS = 254
#: Below this a proposal is shown as an alternative but not pre-assigned.
PREASSIGN_MINIMUM = 0.2
#: A second line is pre-assigned too when Jev thinks the purchase is split and
#: the runner-up is at least this likely.
SECOND_LINE_MINIMUM = 0.15
SPLIT_MINIMUM = 0.6
TRANSCRIPTION_CHARS = 2500

NONE_KEY = "cap"


def school_year(when: date | None) -> str:
    """``25-26`` for anything from September 2025 to August 2026."""
    if when is None:
        return ""
    start = when.year if when.month >= 9 else when.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def invoice_date(document: Document) -> date | None:
    return document.data_factura or (document.created_at.date() if document.created_at else None)


@dataclass(frozen=True, slots=True)
class Ranked:
    partida_id: int
    probability: float


@dataclass(frozen=True, slots=True)
class Suggestion:
    ranking: list[Ranked]
    confidence: float
    cap: float
    multiple: float | None
    model: str

    def preassign(self) -> list[Ranked]:
        """What goes in as the preliminary assignment: one line, two, or none."""
        if not self.ranking or self.ranking[0].probability < PREASSIGN_MINIMUM:
            return []
        if self.cap > self.ranking[0].probability:
            return []
        chosen = [self.ranking[0]]
        if (
            len(self.ranking) > 1
            and (self.multiple or 0) >= SPLIT_MINIMUM
            and self.ranking[1].probability >= SECOND_LINE_MINIMUM
        ):
            chosen.append(self.ranking[1])
        return chosen


def _tagged_year(name: str) -> str:
    head = name.strip()[:5]
    return head if len(head) == 5 and head[2] == "-" and head.replace("-", "").isdigit() else ""


def candidates(partides: list[Partida], invoice_year: str) -> list[Partida]:
    """Expense lines an invoice can be charged to: the leaves of the tree."""
    expenses = [p for p in partides if p.tipus == "despesa" and not p.retirada]
    has_children = {p.codi_pare for p in expenses if p.codi_pare}
    leaves = [p for p in expenses if p.codi not in has_children]
    excess = len(leaves) - MAX_OPTIONS
    if excess > 0 and invoice_year:
        # Lines tagged with another school year are the least likely; drop them first.
        other_year = [p.id for p in leaves if _tagged_year(p.nom) not in ("", invoice_year)]
        dropped = set(other_year[:excess])
        leaves = [p for p in leaves if p.id not in dropped]
    return leaves[:MAX_OPTIONS]


def _described(partida: Partida, parents: dict[str, Partida]) -> dict[str, Any]:
    described: dict[str, Any] = {"partida": partida.nom}
    parent = parents.get(partida.codi_pare or "")
    if parent is not None:
        described["concepte"] = parent.nom
    _, fund = fund_family(partida.codi_finalista)
    described["fons"] = fund if partida.codi_finalista else "Pressupost ordinari del centre"
    if partida.context.strip():
        described["quan_s_usa"] = partida.context.strip()
    return described


def build_state(
    document: Document, general_context: str, history: list[tuple[str, int]]
) -> dict[str, Any]:
    when = invoice_date(document)
    invoice = {
        "proveidor": document.proveidor,
        "cif_proveidor": document.cif_proveidor,
        "data": when.isoformat() if when else "",
        "import_euros": document.import_value,
        "tipus_document": document.tipus_document,
        "que_es_compra_segons_la_ia": document.descripcio,
        "que_es_compra_segons_el_professor": document.descripcio_compra,
        "metode_pagament": document.metode_pagament,
        "compte_bancari": document.pressupost_afectat,
        "responsable": document.responsable_nom,
    }
    state: dict[str, Any] = {
        "factura": {k: v for k, v in invoice.items() if v not in (None, "")},
        "curs_escolar_de_la_factura": school_year(when),
    }
    if history:
        state["partides_anteriors_del_mateix_proveidor"] = [
            {"partida": name, "vegades": count} for name, count in history
        ]
    if general_context.strip():
        state["criteris_del_centre"] = general_context.strip()
    transcription = (document.transcripcio or "").strip()
    if transcription:
        state["text_de_la_factura"] = transcription[:TRANSCRIPTION_CHARS]
    return state


def build_questions(options: list[Partida], all_partides: list[Partida]) -> dict[str, Any]:
    parents = {p.codi: p for p in all_partides}
    criteria: dict[str, Any] = {f"p{p.id}": _described(p, parents) for p in options}
    criteria[NONE_KEY] = (
        "Cap partida de despesa encaixa: no és una compra del centre, és un ingrés o un "
        "document que no s'imputa al pressupost."
    )
    return {
        "partida": {
            "type": "choice",
            "instructions": {
                "pregunta": (
                    "A quina partida del pressupost de despeses del centre educatiu s'ha "
                    "d'imputar aquesta factura?"
                ),
                "com_decidir": [
                    "Mira què s'ha comprat (les descripcions i el text de la factura) i a quin "
                    "concepte de despesa correspon.",
                    "Les partides que comencen per un curs (24-25, 25-26, 26-27) són d'aquell "
                    "curs escolar: tria la del `curs_escolar_de_la_factura`, tret que la "
                    "compra sigui clarament per al curs següent.",
                    "Si la partida diu un nivell, tria el que digui la factura o el professor; "
                    "si no ho diu, la més general. Nivells: INF o INFANTIL = P3, P4 i P5; "
                    "CI = cicle inicial, 1r i 2n de primària; CM = cicle mitjà, 3r i 4t de "
                    "primària; CS = cicle superior, 5è i 6è de primària; ESO = secundària.",
                    "El transport (autocars) va a les partides de Transports; les entrades, "
                    "les activitats, els monitors i les estades, a les de sortides o colònies.",
                    "Les partides d'un fons finalista (Motxilles, Pla de Xoc, PMOE…) només "
                    "quan la compra és d'aquell programa; si no, el pressupost ordinari.",
                    "Segueix `criteris_del_centre` i el camp `quan_s_usa` de cada partida.",
                    "Si el mateix proveïdor ja s'ha imputat a una partida, és una bona pista.",
                ],
            },
            "criteria": criteria,
        },
        "diverses": {
            "type": "noul",
            "instructions": (
                "La factura inclou compres de conceptes de despesa clarament diferents que "
                "s'haurien de repartir entre més d'una partida del pressupost (per exemple, "
                "material escolar i una sortida)?"
            ),
        },
    }


def read_answers(answers: dict[str, Any], model: str) -> Suggestion:
    choice = answers.get("partida") or {}
    ranking: list[Ranked] = []
    cap = 0.0
    for key, probability in (choice.get("probabilities") or {}).items():
        if key == NONE_KEY:
            cap = float(probability)
        elif key.startswith("p") and key[1:].isdigit():
            ranking.append(Ranked(int(key[1:]), round(float(probability), 4)))
    ranking.sort(key=lambda r: r.probability, reverse=True)
    picked = str(choice.get("choice", ""))
    if not ranking and picked.startswith("p") and picked[1:].isdigit():
        ranking = [Ranked(int(picked[1:]), float(choice.get("confidence") or 0))]
    split = (answers.get("diverses") or {}).get("noul")
    return Suggestion(
        ranking=ranking[:5],
        confidence=float(choice.get("confidence") or 0.0),
        cap=round(cap, 4),
        multiple=float(split) if isinstance(split, (int, float)) else None,
        model=model,
    )


def ask(
    jev: JevClient,
    document: Document,
    partides: list[Partida],
    general_context: str,
    history: list[tuple[str, int]],
) -> Suggestion:
    """Raises :class:`~cosecre_hub.services.classification.JevError` when Jev is down."""
    options = candidates(partides, school_year(invoice_date(document)))
    state = json.dumps(build_state(document, general_context, history), ensure_ascii=False)
    answers = jev.ask(state, build_questions(options, partides))
    return read_answers(answers, jev.model)
