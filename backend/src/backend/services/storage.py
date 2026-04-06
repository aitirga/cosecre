from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from ..config import Settings

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")
    return safe_name or "invoice"


async def save_upload_file(file: UploadFile, internal_doc_number: str, settings: Settings) -> Path:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF, PNG, and JPEG invoice files are supported.",
        )

    extension = Path(file.filename or "").suffix.lower() or ALLOWED_CONTENT_TYPES[file.content_type]
    if extension == ".jpeg":
        extension = ".jpg"
    safe_name = sanitize_filename(file.filename or f"{internal_doc_number}{extension}")
    target_path = settings.upload_dir / f"{internal_doc_number}-{safe_name}"
    content = await file.read()
    target_path.write_bytes(content)
    return target_path
