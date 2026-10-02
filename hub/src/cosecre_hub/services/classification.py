"""Closed-list decisions, made by two models that check each other.

The vision model reads the document and proposes a category as part of its
extraction. Jev (TypeSafe's decision model) then answers the same question from
the transcription, with a calibrated probability. Agreement is trusted; a
disagreement or a lone, unsure answer is still filled in but flagged for a
person, which is what the validation step is for anyway.

Jev is optional. Without a key — or when it is down — the vision model's answer
stands on its own, exactly as before this module existed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..schemas.documents import AiHint

logger = logging.getLogger(__name__)

JEV_URL = "https://api.typesafe.ai/v1/systemone"

#: Above this, Jev overrides a vision answer it disagrees with.
JEV_OVERRIDE_CONFIDENCE = 0.85
#: Below this, a Jev answer nobody else backs up is not used at all.
JEV_MINIMUM_CONFIDENCE = 0.5
#: The transcription and the questions share Jev's ~32k-token budget.
MAX_STATE_CHARS = 60_000

_UNKNOWN = "desconegut"


@dataclass(frozen=True, slots=True)
class Question:
    instructions: str
    #: Jev answers with one of these keys; each maps to a stored label ("" = unknown).
    options: dict[str, tuple[str, str]]

    def payload(self) -> dict[str, Any]:
        return {
            "type": "choice",
            "instructions": self.instructions,
            "criteria": {key: description for key, (_, description) in self.options.items()},
        }

    def label(self, key: str) -> str | None:
        option = self.options.get(key)
        return option[0] if option else None


QUESTIONS: dict[str, Question] = {
    "tipus_document": Question(
        instructions="Quin tipus de document comptable és?",
        options={
            "factura": (
                "Factura",
                "Factura completa: es titula 'factura', té número de factura, dades fiscals "
                "del proveïdor i del client destinatari i l'IVA desglossat.",
            ),
            "factura_simplificada": (
                "Factura simplificada",
                "Factura simplificada o tiquet de caixa: posa 'factura simplificada', "
                "'fac. simp.', 'F. simplificada', o és el tiquet d'una botiga, bar, "
                "supermercat, farmàcia, taxi o benzinera.",
            ),
            "pressupost": (
                "Pressupost",
                "Pressupost, oferta o factura proforma: preu proposat abans de comprar o "
                "contractar ('pressupost', 'presupuesto', 'oferta', 'proforma').",
            ),
            "albara": (
                "Albarà",
                "Albarà o nota de lliurament: acredita l'entrega de material ('albarà', "
                "'albarán', 'nota de entrega') i no és la factura.",
            ),
            "tiquet_rebut": (
                "Tiquet de rebut",
                "Rebut o justificant de pagament: comprovant d'un cobrament o d'un pagament "
                "('rebut', 'recibo', 'justificante', comprovant de targeta o de transferència) "
                "que no és una factura.",
            ),
            "altres": ("Altres", "Cap dels tipus anteriors."),
        },
    ),
    "pagament": Question(
        instructions="El document ja està pagat o encara s'ha de pagar?",
        options={
            "pagat": (
                "Pagat",
                "Ja està pagat: tiquet pagat al moment, segell 'PAGAT' o 'PAGADO', canvi "
                "retornat, cobrament amb targeta o en efectiu registrat, rebut de cobrament.",
            ),
            "pendent": (
                "Pendent de pagament",
                "S'ha de pagar: factura amb data de venciment, instruccions o compte per "
                "pagar, 'a pagar', i cap indicació que ja s'hagi pagat.",
            ),
            "altres": (
                "Altres",
                "Situació especial: pagament parcial, bestreta, abonament o devolució.",
            ),
            _UNKNOWN: ("", "El document no permet saber si està pagat."),
        },
    ),
    "metode_pagament": Question(
        instructions="Amb quin mètode s'ha pagat o s'ha de pagar?",
        options={
            "efectiu": (
                "Efectiu",
                "En efectiu: 'efectivo', 'efectiu', 'contado', 'cash', import entregat i canvi.",
            ),
            "prepagament": ("Targeta de prepagament", "Targeta de prepagament o moneder."),
            "transferencia": (
                "Transferència bancària",
                "Per transferència: demana transferir o indica un IBAN on ingressar l'import.",
            ),
            "debit": (
                "Targeta de dèbit",
                "Amb targeta bancària: 'tarjeta', 'targeta', VISA, Mastercard, datàfon, "
                "número de targeta emmascarat.",
            ),
            "domiciliat": (
                "Rebut domiciliat",
                "Domiciliació: es carrega directament al compte del client ('domiciliación', "
                "'adeudo', 'SEPA', 'cargo en cuenta').",
            ),
            "altres": ("Altres", "Un altre mètode: Bizum, PayPal, xec…"),
            _UNKNOWN: ("", "El document no diu com es paga."),
        },
    ),
    "pressupost_afectat": Question(
        instructions="De quin compte de l'institut surt aquest pagament?",
        options={
            "general": (
                "General",
                "Compte general: la majoria de despeses pagades amb targeta de dèbit, rebut "
                "domiciliat o transferència bancària, de qualsevol tipus.",
            ),
            "menjador": (
                "Menjador",
                "Factures del menjador escolar, normalment de l'empresa Ares Menjares o "
                "similar (càtering, servei de menjador).",
            ),
            "caixeta": (
                "Caixeta",
                "Tiquets o factures simplificades pagats en efectiu ('efectivo', canvi "
                "retornat).",
            ),
            "prepagament": (
                "Targeta Prepagament",
                "Tiquets o factures simplificades pagats amb targeta, no en efectiu.",
            ),
            "material_sortides": (
                "Material i Sortides",
                "Compte on les famílies ingressen diners; gairebé mai hi ha despeses, ni "
                "tan sols de material.",
            ),
            _UNKNOWN: ("", "No es pot saber de quin compte surt."),
        },
    ),
}


@dataclass(frozen=True, slots=True)
class JevAnswer:
    label: str
    confidence: float
    #: Stored label → probability, for every option Jev scored.
    probabilities: dict[str, float] = field(default_factory=dict)


class JevError(RuntimeError):
    pass


class JevClient:
    """Thin client for ``POST /v1/systemone``.

    Deliberately not an :class:`LLMProvider`: that contract is about producing
    text, and Jev never does.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "jev-latest",
        *,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=timeout)

    def decide(self, state: str, questions: dict[str, Question]) -> dict[str, JevAnswer]:
        try:
            response = self._client.post(
                JEV_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "state": state[:MAX_STATE_CHARS],
                    "questions": {name: q.payload() for name, q in questions.items()},
                },
            )
            response.raise_for_status()
            answers = response.json()["answers"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise JevError(str(exc)) from exc

        decided: dict[str, JevAnswer] = {}
        for name, question in questions.items():
            answer = answers.get(name) or {}
            label = question.label(str(answer.get("choice", "")))
            if label is None:
                continue  # an answer outside the criteria is no answer
            confidence = answer.get("confidence")
            if confidence is None:
                confidence = max((answer.get("probabilities") or {0: 0.0}).values())
            probabilities = {
                question.label(key): round(float(p), 4)
                for key, p in (answer.get("probabilities") or {}).items()
                if question.label(key) is not None
            }
            decided[name] = JevAnswer(
                label=label, confidence=float(confidence), probabilities=probabilities
            )
        return decided

    def close(self) -> None:
        self._client.close()


def combine(vision: str, jev: JevAnswer | None) -> tuple[str, AiHint | None]:
    """One field's final value from the two opinions, and why."""
    if jev is None:
        return vision, (AiHint(source="openai") if vision else None)

    if jev.label == vision:
        if not vision:
            return "", None
        return vision, AiHint(source="jev+openai", confidence=jev.confidence)

    if not vision:
        # Only Jev has an opinion. Use it if it is reasonably sure, but say so.
        if jev.confidence < JEV_MINIMUM_CONFIDENCE:
            return "", None
        return jev.label, AiHint(source="jev", confidence=jev.confidence, review=True)

    if not jev.label:
        # Jev thinks the document does not say; the vision model read something.
        return vision, AiHint(source="openai", confidence=jev.confidence, review=True)

    if jev.confidence >= JEV_OVERRIDE_CONFIDENCE:
        return jev.label, AiHint(
            source="jev", confidence=jev.confidence, alternative=vision, review=True
        )
    return vision, AiHint(
        source="openai", confidence=jev.confidence, alternative=jev.label, review=True
    )


def build_state(transcription: str, fields: dict[str, Any]) -> str:
    """What Jev reads: the extracted header fields, then the full text."""
    header = "\n".join(
        f"{name}: {value}"
        for name, value in fields.items()
        if value not in (None, "") and name != "transcripcio"
    )
    return (
        "Document comptable rebut per un institut, que és el client.\n"
        f"Camps llegits:\n{header}\n\nText complet del document:\n{transcription}"
    )


class DocumentClassifier:
    """Runs Jev over an extraction and merges its answers in."""

    def __init__(self, jev: JevClient | None):
        self.jev = jev

    @property
    def configured(self) -> bool:
        return self.jev is not None

    def classify(
        self, transcription: str, vision_values: dict[str, str], context: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, AiHint], dict[str, Any]]:
        """Final values, their hints, and a trace of how each was reached."""
        answers: dict[str, JevAnswer] = {}
        trace: dict[str, Any] = {
            "model": getattr(self.jev, "model", None),
            "status": "off" if self.jev is None else "ok",
            "answers": {},
        }
        if self.jev is not None and transcription.strip():
            try:
                answers = self.jev.decide(build_state(transcription, context), QUESTIONS)
            except JevError as exc:
                logger.warning("Jev classification failed; using the vision model alone", exc_info=True)
                trace["status"] = "error"
                trace["error"] = str(exc)[:300]
        elif self.jev is not None:
            trace["status"] = "skipped"  # nothing transcribed to read

        values: dict[str, str] = {}
        hints: dict[str, AiHint] = {}
        for name in QUESTIONS:
            answer = answers.get(name)
            value, hint = combine(vision_values.get(name, ""), answer)
            values[name] = value
            if hint is not None:
                hints[name] = hint
            if answer is not None:
                trace["answers"][name] = {
                    "label": answer.label,
                    "confidence": round(answer.confidence, 4),
                    "probabilities": answer.probabilities,
                }
        return values, hints, trace

    def close(self) -> None:
        if self.jev is not None:
            self.jev.close()
