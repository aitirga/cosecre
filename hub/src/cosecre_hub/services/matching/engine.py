"""From one movement to a proposal: candidates, rules, then two models.

1. **Candidates.** Register entries whose amount is the movement's, or whose
   number, CIF or name the movement carries; plus sets of one supplier's
   invoices that add up to it (one transfer paying several).
2. **Rules.** When one candidate has the exact amount *and* its number or CIF,
   and nothing else comes close, no model is asked.
3. **Models.** Otherwise gpt-6-luna chooses among the top candidates (or none),
   and Jev answers the same multiple-choice question with a calibrated
   probability. They are combined the way ``classification.combine`` combines
   field answers: agreement is trusted, a disagreement is flagged.

Whatever is chosen is only *proposed*. The best other candidates are kept as
alternatives, so the review screen can offer them without asking again.
"""

from __future__ import annotations

import itertools
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...models import BankMovement, Document, PaymentMatch
from ..classification import JevClient, JevError, Question
from ..llm import LLMError, LLMRegistry, Message, StructuredRequest
from . import signals as sig
from .confidence import MEDIUM, ModelView, combined, evidence

logger = logging.getLogger(__name__)

#: How many candidates the models are shown.
MAX_OPTIONS = 8
#: How many alternatives are kept besides the proposal.
MAX_ALTERNATIVES = 3
#: A rules-only decision needs this much daylight over the runner-up.
RULES_MARGIN = 0.25
#: Invoices older than this before the payment are not considered.
LOOKBACK = timedelta(days=400)
NONE_KEY = "cap"

INSTRUCTIONS = """
Ets l'assistent de comptabilitat d'un institut públic de Catalunya. Has de justificar un
moviment bancari: trobar quina factura del registre (o quin conjunt de factures) paga.

Pistes, de més a menys fiables:
- L'import ha de coincidir al cèntim (o la suma, si és un conjunt).
- El concepte de les transferències sol dur el número de factura ("FAC:<número>"), però el
  banc talla el text a uns 17 caràcters: un número que hi comença també compta.
- Els rebuts domiciliats duen el CIF del creditor seguit de tres xifres (B64902166006).
- El nom del beneficiari pot estar escurçat o en majúscules.
- El pagament sol ser posterior a la data de la factura (dies o setmanes), rarament anterior.
- Si cap opció encaixa de debò, respon "cap". És millor "cap" que una factura dubtosa.

Respon estrictament amb l'esquema: la clau de l'opció triada, la teva confiança (0-1) i una
frase curta en català que expliqui per què. A la frase no esmentis les claus (c1, c2…): qui la
llegeix no les veu. Anomena les factures pel número o pel proveïdor.
""".strip()


class ModelChoice(BaseModel):
    choice: str = Field(description='La clau de l\'opció triada (c1, c2…) o "cap".')
    confidence: float = Field(description="Confiança entre 0 i 1.")
    reason: str = Field(description="Una frase curta en català.")


@dataclass
class Candidate:
    key: str
    documents: list[Document]
    signals: dict[str, float]
    evidence: float = 0.0

    @property
    def is_set(self) -> bool:
        return len(self.documents) > 1

    def describe(self) -> str:
        parts = []
        for d in self.documents:
            parts.append(
                f"factura {d.num_factura or '(sense número)'} de {d.proveidor or '(proveïdor desconegut)'}"
                f" (CIF {d.cif_proveidor or '—'}), data {d.data_factura or '—'}, import {d.import_value} €"
                + (f", IBAN {d.compte_corrent}" if d.compte_corrent else "")
                + (f", pagament previst: {d.metode_pagament}" if d.metode_pagament else "")
                + (f", compte: {d.pressupost_afectat}" if d.pressupost_afectat else "")
                + (f", descripció: {d.descripcio[:80]}" if d.descripcio else "")
            )
        joined = " + ".join(parts)
        if self.is_set:
            return f"Conjunt de {len(self.documents)} factures: {joined}"
        return joined[:1].upper() + joined[1:]


@dataclass
class Outcome:
    """What one movement's matching produced, for the caller to count."""

    proposed: bool
    candidates: int
    decided_by: str = ""
    confidence: int | None = None
    trace: dict[str, Any] = field(default_factory=dict)


def describe_movement(movement: BankMovement) -> str:
    sign = "Pagament" if movement.import_value < 0 else "Ingrés"
    return (
        f"{sign} de {abs(movement.import_value):.2f} € el {movement.data} des del compte {movement.compte}"
        f" ({movement.tipus or 'mètode desconegut'}). Concepte: «{movement.concepte}»."
        + (f" Més dades: «{movement.mes_dades}»." if movement.mes_dades else "")
    )


def open_documents(session: Session) -> list[Document]:
    """Register entries that could still be what a payment paid."""
    taken = {
        row[0]
        for row in session.query(PaymentMatch.document_id).filter(PaymentMatch.status == "confirmed")
    }
    return [
        d
        for d in session.query(Document).filter(Document.import_value.isnot(None)).all()
        if d.id not in taken and d.status not in {"pending", "processing", "error"}
    ]


def candidates_for(movement: BankMovement, documents: list[Document]) -> list[Candidate]:
    amount = abs(movement.import_value)
    text = sig.payee_text(movement)
    when = movement.data
    pool = [
        d
        for d in documents
        if not (when and d.data_factura and (d.data_factura < when - LOOKBACK or d.data_factura > when + timedelta(days=10)))
    ]

    singles: list[Candidate] = []
    related: list[Document] = []
    for document in pool:
        exact = sig.amount_signal(amount, document.import_value) >= 1.0
        number = sig.number_signal(movement.num_factura_hint, movement.concepte, document.num_factura)
        cif = sig.cif_signal(movement, document.cif_proveidor)
        name = sig.name_signal(text, document.proveidor)
        if exact or number or cif:
            singles.append(Candidate("", [document], sig.score(movement, [document])))
        if cif or name >= 0.6:
            related.append(document)

    # One payment, several invoices of the same supplier adding up to it.
    sets: list[Candidate] = []
    related = [d for d in related if 0 < (d.import_value or 0) < amount + 0.01]
    related.sort(key=lambda d: d.data_factura or datetime.min.date(), reverse=True)
    related = related[:14]
    for size in (2, 3, 4):
        for combo in itertools.combinations(related, size):
            if abs(sum(d.import_value or 0 for d in combo) - amount) <= 0.011:
                sets.append(Candidate("", list(combo), sig.score(movement, list(combo))))
            if len(sets) >= 6:
                break

    everything = singles + sets
    for candidate in everything:
        candidate.evidence = evidence(candidate.signals)
    everything.sort(key=lambda c: c.evidence, reverse=True)
    for index, candidate in enumerate(everything, start=1):
        candidate.key = f"c{index}"
    return everything


def _rules_decide(candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    top = candidates[0]
    strong = top.signals["amount"] >= 1.0 and max(top.signals["number"], top.signals["cif"]) >= 1.0
    runner_up = candidates[1].evidence if len(candidates) > 1 else 0.0
    if strong and not top.is_set and top.evidence - runner_up >= RULES_MARGIN:
        return top
    return None


def _ask_openai(
    registry: LLMRegistry, movement: BankMovement, options: list[Candidate], model: str | None
) -> tuple[ModelChoice | None, dict[str, Any]]:
    prompt = (
        f"Moviment:\n{describe_movement(movement)}\n\nOpcions del registre:\n"
        + "\n".join(f"- {c.key}: {c.describe()}" for c in options)
        + f'\n- {NONE_KEY}: Cap d\'aquestes factures correspon a aquest moviment.'
    )
    try:
        result = registry.get().structured(
            StructuredRequest(
                messages=[Message(role="user", content=prompt)],
                schema_name="payment_match",
                json_schema=ModelChoice.model_json_schema(),
                instructions=INSTRUCTIONS,
                model=model,
            )
        )
        choice = ModelChoice.model_validate(result.data)
    except (LLMError, ValueError) as exc:
        logger.warning("The vision model could not choose a match", exc_info=True)
        return None, {"status": "error", "error": str(exc)[:300]}
    keys = {c.key for c in options} | {NONE_KEY}
    if choice.choice not in keys:
        return None, {"status": "invalid", "answer": choice.model_dump()}
    choice.confidence = max(0.0, min(1.0, choice.confidence))
    return choice, {"status": "ok", "model": result.model, "answer": choice.model_dump()}


def _ask_jev(
    jev: JevClient | None, movement: BankMovement, options: list[Candidate]
) -> tuple[Any, dict[str, Any]]:
    if jev is None:
        return None, {"status": "off"}
    question = Question(
        instructions=(
            "Quina d'aquestes factures del registre paga el moviment bancari? L'import ha de "
            "coincidir; el número de factura, el CIF o el nom del proveïdor ho confirmen."
        ),
        options={
            **{c.key: (c.key, c.describe()) for c in options},
            NONE_KEY: (NONE_KEY, "Cap d'aquestes factures correspon al moviment."),
        },
    )
    state = "Moviment bancari d'un institut que cal justificar amb una factura.\n" + describe_movement(movement)
    try:
        answer = jev.decide(state, {"match": question}).get("match")
    except JevError as exc:
        logger.warning("Jev could not choose a match", exc_info=True)
        return None, {"status": "error", "error": str(exc)[:300]}
    if answer is None:
        return None, {"status": "invalid"}
    return answer, {
        "status": "ok",
        "model": jev.model,
        "answer": {
            "choice": answer.label,
            "confidence": round(answer.confidence, 4),
            "probabilities": answer.probabilities,
        },
    }


def decide(
    movement: BankMovement,
    candidates: list[Candidate],
    *,
    registry: LLMRegistry,
    jev: JevClient | None,
    model: str | None = None,
) -> tuple[Candidate | None, ModelView, str, str, dict[str, Any]]:
    """The chosen candidate (or ``None``), how sure the models were, who decided, why."""
    trace: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "candidates": [
            {"key": c.key, "documents": [d.internal_doc_number for d in c.documents], "evidence": round(c.evidence, 3)}
            for c in candidates[:MAX_OPTIONS]
        ],
    }
    ruled = _rules_decide(candidates)
    if ruled is not None:
        trace["rules"] = {"chosen": ruled.key}
        reason = "L'import coincideix i el concepte porta el número de factura o el CIF del proveïdor."
        return ruled, ModelView(rules_only=True), "rules", reason, trace
    if not candidates:
        trace["rules"] = {"chosen": None}
        return None, ModelView(), "rules", "Cap factura del registre té aquest import, número, CIF o proveïdor.", trace

    options = candidates[:MAX_OPTIONS]
    by_key = {c.key: c for c in options}
    vision, trace["openai"] = _ask_openai(registry, movement, options, model)
    jev_answer, trace["jev"] = _ask_jev(jev, movement, options)

    v_key = vision.choice if vision else None
    j_key = jev_answer.label if jev_answer else None
    v_conf = vision.confidence if vision else None
    j_conf = jev_answer.confidence if jev_answer else None
    reason = vision.reason if vision else ""

    if v_key is None and j_key is None:
        trace["final"] = {"chosen": None}
        return None, ModelView(), "", "Els models no han pogut respondre.", trace
    if v_key is not None and j_key is not None and v_key != j_key:
        # They disagree: Jev wins only when it is very sure, like for the register's fields.
        jev_wins = (j_conf or 0) >= 0.85
        chosen_key = j_key if jev_wins else v_key
        decided_by = "jev" if jev_wins else "openai"
        view = ModelView(
            openai=v_conf if chosen_key == v_key else None,
            jev=j_conf if chosen_key == j_key else None,
            disagree=True,
        )
        if jev_wins:
            reason = f"Jev tria una altra opció amb {round((j_conf or 0) * 100)} % de confiança. {reason}".strip()
    elif v_key is not None and j_key is not None:
        chosen_key, decided_by, view = v_key, "jev+openai", ModelView(openai=v_conf, jev=j_conf)
    elif v_key is not None:
        chosen_key, decided_by, view = v_key, "openai", ModelView(openai=v_conf)
    else:
        if (j_conf or 0) < 0.5:
            trace["final"] = {"chosen": None}
            return None, ModelView(), "jev", "Jev no n'està prou segur.", trace
        chosen_key, decided_by, view = j_key, "jev", ModelView(jev=j_conf)
        reason = reason or "Triat per Jev."

    trace["final"] = {"chosen": chosen_key, "decided_by": decided_by}
    if chosen_key == NONE_KEY:
        return None, view, decided_by, reason or "Cap factura correspon a aquest moviment.", trace
    return by_key.get(chosen_key), view, decided_by, reason, trace


def match_movement(
    session: Session,
    movement: BankMovement,
    *,
    registry: LLMRegistry,
    jev: JevClient | None,
    model: str | None = None,
    documents: list[Document] | None = None,
) -> Outcome:
    """Replace a movement's open proposals with fresh ones. Commits."""
    for stale in session.query(PaymentMatch).filter(
        PaymentMatch.movement_id == movement.id, PaymentMatch.status.in_(["proposed", "alternative"])
    ).all():
        session.delete(stale)
    session.flush()
    rejected = {
        m.document_id
        for m in session.query(PaymentMatch).filter(
            PaymentMatch.movement_id == movement.id, PaymentMatch.status == "rejected"
        )
    }
    pool = [d for d in (documents if documents is not None else open_documents(session)) if d.id not in rejected]
    candidates = candidates_for(movement, pool)
    chosen, view, decided_by, reason, trace = decide(
        movement, candidates, registry=registry, jev=jev, model=model
    )

    jev_probabilities = ((trace.get("jev") or {}).get("answer") or {}).get("probabilities") or {}
    group = 0
    confidence = None
    if chosen is not None:
        confidence = combined(chosen.signals, view)
        if chosen.is_set:
            # Adding up is easy to do by accident; a person should look at a set.
            confidence = min(confidence, MEDIUM)
        for document in chosen.documents:
            session.add(
                PaymentMatch(
                    movement_id=movement.id,
                    document_id=document.id,
                    confidence=confidence,
                    rank=0,
                    signals={**chosen.signals, "group": group, "set_size": len(chosen.documents)},
                    decided_by=decided_by,
                    reason=reason,
                    ai_trace=trace,
                    status="proposed",
                )
            )
    seen = {d.id for d in chosen.documents} if chosen else set()
    rank = 1
    for candidate in candidates:
        if rank > MAX_ALTERNATIVES:
            break
        if candidate is chosen or any(d.id in seen for d in candidate.documents):
            continue
        group += 1
        alt_view = ModelView(jev=jev_probabilities.get(candidate.key))
        alt_confidence = min(combined(candidate.signals, alt_view), (confidence or 100) - 1)
        for document in candidate.documents:
            seen.add(document.id)
            session.add(
                PaymentMatch(
                    movement_id=movement.id,
                    document_id=document.id,
                    confidence=max(0, alt_confidence),
                    rank=rank,
                    signals={**candidate.signals, "group": group, "set_size": len(candidate.documents)},
                    decided_by="rules",
                    reason="",
                    status="alternative",
                )
            )
        rank += 1
    movement.match_status = "proposed" if chosen is not None else "no_match"
    session.commit()
    return Outcome(
        proposed=chosen is not None,
        candidates=len(candidates),
        decided_by=decided_by,
        confidence=confidence,
        trace=trace,
    )


def resolve_conflicts(session: Session, movement_ids: list[int]) -> int:
    """One invoice, one payment: keep each proposal only where it fits best.

    A monthly subscription has the same amount every month, so one invoice can
    come out as the proposal for four charges. It stays on the movement it fits
    best — highest confidence, then nearest date — and becomes an alternative
    for the others. Returns how many proposals were withdrawn.
    """
    proposals = (
        session.query(PaymentMatch)
        .join(BankMovement, PaymentMatch.movement_id == BankMovement.id)
        .filter(PaymentMatch.status == "proposed", BankMovement.match_status == "proposed")
        .all()
    )
    relevant = set(movement_ids)
    by_document: dict[int, list[PaymentMatch]] = {}
    for match in proposals:
        by_document.setdefault(match.document_id, []).append(match)

    def fit(match: PaymentMatch):
        paid, invoiced = match.movement.data, match.document.data_factura
        distance = abs((paid - invoiced).days) if paid and invoiced else 10_000
        return (match.confidence, -distance)

    withdrawn = 0
    for matches in by_document.values():
        if len(matches) < 2 or not any(m.movement_id in relevant for m in matches):
            continue
        winner = max(matches, key=fit)
        for loser in matches:
            if loser is winner or loser.movement_id not in relevant:
                continue
            movement = loser.movement
            when = winner.movement.data.strftime("%d/%m/%Y") if winner.movement.data else "un altre dia"
            for sibling in movement.matches:
                if sibling.status == "proposed":
                    sibling.status = "alternative"
                    sibling.rank = max(sibling.rank, 1)
                    sibling.confidence = min(sibling.confidence, MEDIUM - 1)
                    sibling.reason = f"Aquesta factura encaixa millor amb el moviment del {when}."
            movement.match_status = "no_match"
            withdrawn += 1
    session.commit()
    return withdrawn


def dumps(outcome: Outcome) -> str:
    return json.dumps(outcome.trace, ensure_ascii=False, default=str)
