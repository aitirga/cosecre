"""Turning a scanned document into structured fields.

This is a thin domain wrapper over the LLM gateway: it owns the prompt and the
schema, and knows nothing about which provider ends up answering.
"""

from __future__ import annotations

from pathlib import Path

from ..schemas import DocumentType, InvoiceExtraction
from .llm import FileExtractionRequest, LLMError, LLMRegistry

DEFAULT_PROMPT = """
Extract accounting document data from the provided document.
Rules:
- Return the response strictly in the provided schema.
- Keep text exactly as seen when possible.
- Use empty strings when a field is not present.
- Preserve decimal separators in the amount.
""".strip()


class DocumentExtractionService:
    def __init__(self, registry: LLMRegistry):
        self._registry = registry

    def extract(
        self,
        file_path: Path,
        mime_type: str,
        *,
        model: str | None = None,
        prompt_override: str = "",
        document_type: DocumentType = "invoice",
        provider: str | None = None,
    ) -> InvoiceExtraction:
        instructions = "\n\n".join(part for part in [DEFAULT_PROMPT, prompt_override] if part)
        result = self._registry.get(provider).extract_file(
            FileExtractionRequest(
                file_path=file_path,
                mime_type=mime_type,
                # by_alias keeps the sheet's own field name (`import`) as the key
                # the model is asked to produce, so nothing has to be remapped.
                json_schema=InvoiceExtraction.model_json_schema(by_alias=True),
                schema_name=f"{document_type}_extraction",
                prompt=f"Extract the {document_type} fields from this document.",
                instructions=instructions,
                model=model,
            )
        )

        try:
            return InvoiceExtraction.model_validate(result.data)
        except Exception as exc:  # noqa: BLE001 — a schema mismatch is an LLM failure
            raise LLMError(
                "The model returned a payload that does not match the document schema."
            ) from exc
