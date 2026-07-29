"""Where uploaded documents land on disk.

Files are streamed rather than read whole: the hub runs on modest hardware and a
handful of concurrent multi-megabyte uploads is enough to matter.
"""

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

#: Images only. AIM's chat takes photos of a student's working; a PDF
#: mid-conversation is not useful, and it would need the upload-then-reference
#: path rather than an inline part.
IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}

#: Generous for a phone photo of an invoice, small enough that a runaway client
#: cannot fill the disk in one request.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


def sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")
    return safe_name or "document"


async def save_upload_file(
    file: UploadFile,
    internal_doc_number: str,
    settings: Settings,
    *,
    allowed: dict[str, str] | None = None,
    subdirectory: str | None = None,
) -> Path:
    """Stream an upload to disk.

    Both keyword arguments default to the documents module's original
    behaviour. AIM passes an image-only allow-list and its own subdirectory, so
    a student's photo never lands beside an invoice.
    """
    accepted = allowed or ALLOWED_CONTENT_TYPES
    if file.content_type not in accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {', '.join(sorted(accepted))} files are supported.",
        )

    extension = Path(file.filename or "").suffix.lower() or accepted[file.content_type]
    if extension == ".jpeg":
        extension = ".jpg"
    safe_name = sanitize_filename(file.filename or f"{internal_doc_number}{extension}")

    directory = settings.upload_dir / subdirectory if subdirectory else settings.upload_dir
    directory.mkdir(parents=True, exist_ok=True)
    target_path = directory / f"{internal_doc_number}-{safe_name}"

    written = 0
    try:
        with target_path.open("wb") as sink:
            while chunk := await file.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"Files larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB "
                            "are not accepted."
                        ),
                    )
                sink.write(chunk)
    except Exception:
        # A partial file would otherwise sit there looking like a real upload and
        # fail extraction later with a confusing error.
        target_path.unlink(missing_ok=True)
        raise

    if written == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file was empty."
        )

    return target_path
