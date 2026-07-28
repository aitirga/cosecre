from __future__ import annotations

import base64
from pathlib import Path

from openai import OpenAI

from ..config import Settings
from ..schemas import DocumentType, InvoiceExtraction

DEFAULT_PROMPT = """
Extract accounting document data from the provided document.
Rules:
- Return the response strictly in the provided schema.
- Keep text exactly as seen when possible.
- Use empty strings when a field is not present.
- Preserve decimal separators in the amount.
""".strip()


class OpenAIExtractionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract_document(
        self,
        file_path: Path,
        mime_type: str,
        internal_doc_number: str,
        model: str,
        prompt_override: str = "",
        document_type: DocumentType = "invoice",
    ) -> InvoiceExtraction:
        if not self.settings.openai_api_key:
            raise RuntimeError("OpenAI API key is not configured.")

        client = OpenAI(api_key=self.settings.openai_api_key)
        content: list[dict[str, str]] = [
            {
                "type": "input_text",
                "text": f"Extract the {document_type} fields from this document.",
            }
        ]

        if mime_type == "application/pdf":
            with file_path.open("rb") as file_stream:
                uploaded = client.files.create(file=file_stream, purpose="user_data")
            content.append({"type": "input_file", "file_id": uploaded.id})
        else:
            encoded = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{encoded}",
                    "detail": "high",
                }
            )

        response = client.responses.parse(
            model=model,
            instructions="\n\n".join(part for part in [DEFAULT_PROMPT, prompt_override] if part),
            input=[{"role": "user", "content": content}],
            text_format=InvoiceExtraction,
            reasoning={"effort": "medium"},
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI did not return a structured document payload.")

        return response.output_parsed

    def extract_invoice(
        self,
        file_path: Path,
        mime_type: str,
        internal_doc_number: str,
        model: str,
        prompt_override: str = "",
    ) -> InvoiceExtraction:
        return self.extract_document(
            file_path,
            mime_type,
            internal_doc_number,
            model,
            prompt_override,
            document_type="invoice",
        )
