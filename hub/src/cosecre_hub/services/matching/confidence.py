"""One number per proposal, and the colour it is shown in.

People see a single confidence, not a dashboard of scores. It blends what the
rules can check (``E``, from :mod:`.signals`) with what the models said
(``M``), and then caps it where a rule says "don't be sure":

* the amount is not exact (a rounded card charge), or several invoices add up
  to it (applied by the engine) → ≤ 60;
* the two models disagree → ≤ 50;
* nothing gets above 95 unless the amount, the invoice number or CIF, and both
  models all agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Band = Literal["high", "medium", "low", "none"]

HIGH = 85
MEDIUM = 60

#: Signal → weight in the evidence score. They add to more than 1 on purpose:
#: two strong signals are enough to be sure, and the sum is capped.
WEIGHTS = {
    "amount": 0.35,
    "number": 0.30,
    "cif": 0.20,
    "iban": 0.20,
    "name": 0.15,
    "date": 0.10,
    "consistency": 0.05,
}


def evidence(signals: dict[str, float]) -> float:
    """``E``: the rules' view, 0–1."""
    total = sum(WEIGHTS[name] * max(0.0, min(1.0, float(signals.get(name, 0.0)))) for name in WEIGHTS)
    return min(1.0, total)


@dataclass(frozen=True, slots=True)
class ModelView:
    """What the models said about the chosen candidate.

    ``openai`` / ``jev`` are each model's confidence *in this candidate*, or
    ``None`` when that model did not answer (or was not asked).
    """

    openai: float | None = None
    jev: float | None = None
    #: The models picked different candidates.
    disagree: bool = False
    #: The rules decided alone; no model was asked.
    rules_only: bool = False


def model_score(view: ModelView, e: float) -> float:
    """``M``: the models' view, 0–1."""
    if view.rules_only:
        return e
    answers = [c for c in (view.openai, view.jev) if c is not None]
    if not answers:
        return 0.0
    if view.disagree:
        return max(answers) * 0.5
    if len(answers) == 2:
        return max(answers)
    return answers[0] * 0.8


def combined(signals: dict[str, float], view: ModelView) -> int:
    e = evidence(signals)
    m = model_score(view, e)
    score = round(100 * (0.6 * e + 0.4 * m))
    if signals.get("amount", 0.0) < 1.0:
        score = min(score, MEDIUM)
    if view.disagree:
        score = min(score, 50)
    strong = (
        signals.get("amount", 0.0) >= 1.0
        and max(signals.get("number", 0.0), signals.get("cif", 0.0)) >= 1.0
        and view.openai is not None
        and view.jev is not None
        and not view.disagree
    )
    if not strong:
        score = min(score, 95)
    return max(0, min(100, score))


def band(confidence: int | None) -> Band:
    if confidence is None:
        return "none"
    if confidence >= HIGH:
        return "high"
    if confidence >= MEDIUM:
        return "medium"
    return "low"
