"""What a person decided before, for Jev to read and for its answer to be weighed by.

Jev cannot be trained on a school's own decisions, but it reads what it is
given and its probabilities can be reweighted. So a movement's precedents —
the lines other movements of the same supplier (or, with no invoice, the same
concept) were confirmed to — do two things:

- they go into Jev's state, compact: one entry per line with how often, how
  recently and an example, and the times a person changed what Jev proposed,
  which is what teaches most;
- they bend Jev's ranking towards what was chosen before, more the more
  history there is, so a supplier seen once barely moves it and one charged
  to the same line ten times all but decides it.

Old decisions fade (half a weight per school year), only confirmed ones count,
and what goes into the state has a hard size limit: Jev's budget is better
spent on the invoice than on a long list of examples.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from ...models import BankMovement, Document, PaymentMatch
from ...services.people import fold
from ...services.text_format import compact_code
from .models import MovementPartida, Partida, PartidaDecision

#: A decision a year older than the movement counts half.
HALF_LIFE_DAYS = 365
MAX_LINES = 6
MAX_CORRECTIONS = 3
#: What the precedents may take of Jev's state, as JSON.
MAX_CHARS = 1500
EXAMPLE_CHARS = 90
#: How far the history bends Jev's ranking: β = BETA_MAX · W / (W + BETA_HALF),
#: W being the decayed number of precedents. Three recent ones give half of it.
BETA_MAX = 1.0
BETA_HALF = 3.0
#: What a line nobody chose before keeps, so the history never zeroes Jev out.
#: The usual line gains at most (1 + FLOOR) / FLOOR = 11× on the others: about
#: 1.8× after one precedent, 6× after ten.
FLOOR = 0.1


def _decay(when: date | None, then: date | None) -> float:
    if when is None or then is None:
        return 0.5
    return 0.5 ** (abs((when - then).days) / HALF_LIFE_DAYS)


def _month(when: date | None) -> str:
    return when.strftime("%Y-%m") if when else ""


def _example(invoices: list[Document], concept: str) -> str:
    for document in invoices:
        text = (document.descripcio_compra or document.descripcio or "").strip()
        if text:
            return text[:EXAMPLE_CHARS]
    return (concept or "").strip()[:EXAMPLE_CHARS]


@dataclass(slots=True)
class Precedent:
    codi: str
    nom: str
    weight: float = 0.0
    count: int = 0
    last: date | None = None
    example: str = ""


@dataclass(slots=True)
class Correction:
    #: What Jev proposed, by code (to name it as this year does) and by the name it had.
    codi: str
    nom: str
    chosen: str
    count: int = 0
    last: date | None = None


@dataclass(slots=True)
class History:
    #: ``proveidor`` or ``concepte``: what the precedents share with the movement.
    by: str = ""
    lines: list[Precedent] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(p.weight for p in self.lines)

    @property
    def strength(self) -> float:
        """β: 0 without history, towards ``BETA_MAX`` with plenty."""
        return BETA_MAX * self.total / (self.total + BETA_HALF) if self.total else 0.0

    def for_state(self, names: dict[str, str]) -> dict[str, Any] | None:
        """The block Jev reads, within ``MAX_CHARS``. ``names``: codi → this year's name."""
        if not self.lines and not self.corrections:
            return None
        block: dict[str, Any] = {"mateix": self.by}
        block["partides"] = [
            {
                k: v
                for k, v in {
                    "partida": names.get(p.codi, p.nom),
                    "vegades": p.count,
                    "ultima": _month(p.last),
                    "exemple": p.example,
                }.items()
                if v not in ("", None)
            }
            for p in self.lines[:MAX_LINES]
        ]
        if self.corrections:
            block["correccions"] = [
                {
                    "jev_va_proposar": names.get(c.codi, c.nom),
                    "la_persona_va_triar": c.chosen,
                    "vegades": c.count,
                }
                for c in self.corrections[:MAX_CORRECTIONS]
            ]
        # Over budget: drop the least telling first — the oldest lines' examples,
        # then the rarest lines, then the oldest corrections.
        while len(json.dumps(block, ensure_ascii=False)) > MAX_CHARS:
            with_example = [e for e in block["partides"] if "exemple" in e]
            if with_example:
                del with_example[-1]["exemple"]
            elif len(block["partides"]) > 1:
                block["partides"].pop()
            elif block.get("correccions"):
                block["correccions"].pop()
            else:
                break
        return block

    def weigh(self, probabilities: dict[int, float], codis: dict[int, str]) -> dict[int, float]:
        """Jev's line probabilities bent by the history; same total, so "none fits" keeps its own.

        ``p'(c) ∝ p(c) · (share(c) + FLOOR)^β``, where ``share`` is the line's
        part of the decayed precedents.
        """
        beta = self.strength
        if not beta or not probabilities:
            return dict(probabilities)
        shares = {p.codi: p.weight / self.total for p in self.lines}
        bent = {
            pid: p * (shares.get(codis.get(pid, ""), 0.0) + FLOOR) ** beta
            for pid, p in probabilities.items()
        }
        mass, total = sum(probabilities.values()), sum(bent.values())
        if total <= 0:
            return dict(probabilities)
        return {pid: round(p * mass / total, 4) for pid, p in bent.items()}


def _paid(session: Session, movement_ids: list[int]) -> dict[int, list[Document]]:
    rows = (
        session.query(PaymentMatch.movement_id, Document)
        .join(Document, Document.id == PaymentMatch.document_id)
        .filter(PaymentMatch.status == "confirmed", PaymentMatch.movement_id.in_(movement_ids or [-1]))
        .order_by(PaymentMatch.id)
    )
    paid: dict[int, list[Document]] = defaultdict(list)
    for movement_id, document in rows:
        paid[movement_id].append(document)
    return paid


def gather(session: Session, movement: BankMovement, invoices: list[Document]) -> History:
    """Confirmed lines of the movements that share this one's supplier (or concept)."""
    cifs = {compact_code(d.cif_proveidor) for d in invoices} - {""}
    names = {fold(d.proveidor or "") for d in invoices} - {""}
    concept = fold(movement.concepte or "")
    if not cifs and not names and not concept:
        return History()
    rows = (
        session.query(MovementPartida.movement_id, BankMovement, Partida.codi, Partida.nom)
        .join(BankMovement, BankMovement.id == MovementPartida.movement_id)
        .join(Partida, Partida.id == MovementPartida.partida_id)
        .filter(MovementPartida.confirmada.is_(True), MovementPartida.movement_id != movement.id)
        .all()
    )
    if not rows:
        return History()
    paid = _paid(session, list({row[0] for row in rows}))

    charged: dict[int, list[tuple[str, str]]] = defaultdict(list)
    others: dict[int, BankMovement] = {}
    for other_id, other, codi, nom in rows:
        charged[other_id].append((codi, nom))
        others[other_id] = other

    def shares_key(other: BankMovement) -> bool:
        theirs = paid.get(other.id, [])
        if invoices:
            return any(
                (cifs and compact_code(d.cif_proveidor) in cifs) or (names and fold(d.proveidor or "") in names)
                for d in theirs
            )
        return not theirs and bool(concept) and fold(other.concepte or "") == concept

    when = movement.data or movement.data_valor
    lines: dict[str, Precedent] = {}
    matched: list[int] = []
    for other_id, other in others.items():
        if not shares_key(other):
            continue
        matched.append(other_id)
        then = other.data or other.data_valor
        weight = _decay(when, then)
        example = _example(paid.get(other_id, []), other.concepte or "")
        on = charged[other_id]
        for codi, nom in on:
            line = lines.setdefault(codi, Precedent(codi=codi, nom=nom))
            # A split counts once per line, its weight shared out.
            line.weight += weight / len(on)
            line.count += 1
            if line.last is None or (then and then >= line.last):
                line.last, line.nom = then, nom
                line.example = example or line.example

    corrections: dict[tuple[str, str], Correction] = {}
    if matched:
        for decision in session.query(PartidaDecision).filter(
            PartidaDecision.movement_id.in_(matched), PartidaDecision.corregida.is_(True)
        ):
            chosen = " + ".join(c.get("nom", "") for c in decision.triades or [])
            correction = corrections.setdefault(
                (decision.proposada_codi, chosen),
                Correction(codi=decision.proposada_codi, nom=decision.proposada_nom, chosen=chosen),
            )
            correction.count += 1
            then = others[decision.movement_id].data
            if correction.last is None or (then and then > correction.last):
                correction.last = then

    return History(
        by="proveidor" if invoices else "concepte",
        lines=sorted(lines.values(), key=lambda p: (p.weight, p.count), reverse=True),
        corrections=sorted(
            corrections.values(), key=lambda c: (c.count, c.last or date.min), reverse=True
        ),
    )
