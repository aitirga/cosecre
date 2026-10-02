"""Turning a scanned document into a register entry.

Three steps, each owned by something that is good at it: the vision model reads
the document, :mod:`.classification` settles the closed lists with a second
opinion, and :mod:`.text_format` enforces formatting nobody should have to
trust a model with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ..schemas import AiHint, DocumentExtraction
from ..schemas.documents import canonical_choice
from .classification import QUESTIONS, DocumentClassifier
from .llm import FileExtractionRequest, LLMError, LLMRegistry
from .text_format import (
    compact_code,
    iban_is_valid,
    name_case,
    normalize_iban,
    parse_date,
    sentence_case,
)

DEFAULT_PROMPT = """
Ets l'assistent de comptabilitat d'un institut públic de Catalunya. Extreu les dades del
document comptable adjunt (factura, tiquet, pressupost, albarà o rebut).
Regles:
- Respon estrictament amb l'esquema proporcionat.
- Transcriu el document sencer al camp transcripcio, sense resumir-lo.
- Copia números, codis i NIF exactament com apareixen.
- Les dates, en format dd/mm/aaaa.
- Els textos que redactis tu (descripcio) han d'estar en català, en minúscules amb majúscula
  inicial, encara que el document sigui en una altra llengua.
- Deixa buit qualsevol camp que el document no mostri; no l'endevinis.
- Excepció: pressupost_afectat (el compte) no surt mai al document. Dedueix-lo del tipus de
  document, del proveïdor i de com s'ha pagat, seguint la descripció del camp.
""".strip()


@dataclass
class ExtractedDocument:
    """A normalised extraction, ready to become (or enrich) a register entry."""

    fields: dict[str, object]
    transcription: str
    hints: dict[str, AiHint] = field(default_factory=dict)
    #: How the result was reached: the vision model's raw proposal, Jev's
    #: scored answers, and what was kept. Shown in the app for the curious.
    trace: dict[str, Any] = field(default_factory=dict)


class DocumentExtractionService:
    def __init__(self, registry: LLMRegistry, classifier: DocumentClassifier | None = None):
        self._registry = registry
        self._classifier = classifier or DocumentClassifier(None)

    def read(
        self,
        file_path: Path,
        mime_type: str,
        *,
        model: str | None = None,
        prompt_override: str = "",
        provider: str | None = None,
    ) -> DocumentExtraction:
        """The vision model's raw reading, before anything is decided."""
        instructions = "\n\n".join(part for part in [DEFAULT_PROMPT, prompt_override] if part)
        result = self._registry.get(provider).extract_file(
            FileExtractionRequest(
                file_path=file_path,
                mime_type=mime_type,
                # by_alias keeps the sheet's own field name (`import`) as the key
                # the model is asked to produce, so nothing has to be remapped.
                json_schema=DocumentExtraction.model_json_schema(by_alias=True),
                schema_name="document_extraction",
                prompt="Extreu les dades d'aquest document comptable.",
                instructions=instructions,
                model=model,
            )
        )
        try:
            return DocumentExtraction.model_validate(result.data)
        except Exception as exc:  # noqa: BLE001 — a schema mismatch is an LLM failure
            raise LLMError(
                "The model returned a payload that does not match the document schema."
            ) from exc

    def extract(self, file_path: Path, mime_type: str, **kwargs) -> ExtractedDocument:
        return self.finish(self.read(file_path, mime_type, **kwargs), model=kwargs.get("model"))

    def finish(self, raw: DocumentExtraction, *, model: str | None = None) -> ExtractedDocument:
        fields, hints = normalise(raw)
        vision = {name: str(fields.get(name, "")) for name in QUESTIONS}
        decided, decided_hints, jev_trace = self._classifier.classify(
            raw.transcripcio,
            vision,
            context={
                "proveidor": fields.get("proveidor"),
                "num_factura": fields.get("num_factura"),
                "import": fields.get("import_value"),
                # The account follows from these; Jev reads the vision model's take.
                "tipus_document": fields.get("tipus_document"),
                "metode_pagament": fields.get("metode_pagament"),
            },
        )
        fields.update(decided)
        hints.update(decided_hints)
        proposal = raw.model_dump(by_alias=True, exclude={"transcripcio"})
        trace = {
            "at": datetime.now(UTC).isoformat(),
            "vision": {"model": model, "proposal": proposal},
            "jev": jev_trace,
            "final": {
                name: {
                    "value": fields.get(name, ""),
                    "hint": hints[name].model_dump(exclude_none=True) if name in hints else None,
                }
                for name in QUESTIONS
            },
        }
        return ExtractedDocument(
            fields=fields, transcription=raw.transcripcio, hints=hints, trace=trace
        )


def normalise(raw: DocumentExtraction) -> tuple[dict[str, object], dict[str, AiHint]]:
    """Apply the house formatting rules to a raw extraction."""
    hints: dict[str, AiHint] = {}

    def as_date(name: str, text: str) -> date | None:
        parsed = parse_date(text)
        if text.strip() and parsed is None:
            hints[name] = AiHint(source="openai", alternative=text.strip(), review=True)
        return parsed

    iban = normalize_iban(raw.compte_corrent)
    if iban and not iban_is_valid(iban):
        hints["compte_corrent"] = AiHint(source="openai", review=True)
    postcode = re.sub(r"\s", "", raw.codi_postal)
    if postcode and not re.fullmatch(r"\d{5}", postcode):
        hints["codi_postal"] = AiHint(source="openai", review=True)

    fields: dict[str, object] = {
        "tipus_document": canonical_choice("tipus_document", raw.tipus_document),
        "num_factura": raw.num_factura.strip(),
        "data_factura": as_date("data_factura", raw.data_factura),
        "proveidor": name_case(raw.proveidor),
        "cif_proveidor": compact_code(raw.cif_proveidor),
        "carrer": name_case(raw.carrer),
        "codi_postal": postcode,
        "ciutat": name_case(raw.ciutat),
        "compte_corrent": iban,
        "cif_proveit": compact_code(raw.cif_proveit),
        "import_value": raw.import_value,
        "descripcio": sentence_case(raw.descripcio),
        "pressupost_afectat": canonical_choice("pressupost_afectat", raw.pressupost_afectat),
        "pagament": canonical_choice("pagament", raw.pagament),
        "metode_pagament": canonical_choice("metode_pagament", raw.metode_pagament),
        "data_pagament": as_date("data_pagament", raw.data_pagament),
    }
    return fields, hints
