"""Where uploaded documents land on disk.

Files are streamed rather than read whole: the hub runs on modest hardware and a
handful of concurrent multi-megabyte uploads is enough to matter.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException, UploadFile, status

from ..config import Settings

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}

#: What a file's extension says it is, whatever its case: ``FACTURA.PDF`` and
#: ``scan.JPEG`` arrive from scanners and phones as often as ``.pdf`` does.
EXTENSION_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

#: Spellings of an allowed type that clients send in place of the canonical one.
_CONTENT_TYPE_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "application/x-pdf": "application/pdf"}

#: Generous for a phone photo of an invoice, small enough that a runaway client
#: cannot fill the disk in one request.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


def sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")
    return safe_name or "document"


class StoredUpload(NamedTuple):
    path: Path
    #: The type the file was recognised as, one of ``ALLOWED_CONTENT_TYPES``.
    content_type: str


def _sniff_content_type(head: bytes) -> str | None:
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def resolve_content_type(filename: str | None, declared: str | None, head: bytes = b"") -> str | None:
    """What an upload is, or ``None`` when it is not a PDF or an image we take.

    The type the client declared wins when it is one we accept. Clients that do
    not know the type (``application/octet-stream``, nothing at all, a Windows
    registry without ``.PDF``) fall back to the extension, compared without
    regard to case, and finally to the file's own first bytes.
    """
    declared_type = (declared or "").split(";")[0].strip().lower()
    declared_type = _CONTENT_TYPE_ALIASES.get(declared_type, declared_type)
    if declared_type in ALLOWED_CONTENT_TYPES:
        return declared_type
    by_name = EXTENSION_CONTENT_TYPES.get(Path(filename or "").suffix.lower())
    return by_name or _sniff_content_type(head)


async def save_upload_file(file: UploadFile, internal_doc_number: str, settings: Settings) -> StoredUpload:
    first = await file.read(_CHUNK_BYTES)
    content_type = resolve_content_type(file.filename, file.content_type, first)
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Només s'accepten fitxers PDF, PNG i JPEG.",
        )

    # The extension is stored lower-case and canonical, so nothing downstream
    # has to remember to fold case (``.PDF``) or spelling (``.jpeg``).
    original = sanitize_filename(file.filename) if file.filename else internal_doc_number
    stem = original[: -len(Path(original).suffix)] if Path(original).suffix.lower() in EXTENSION_CONTENT_TYPES else original
    extension = ALLOWED_CONTENT_TYPES[content_type]
    target_path = settings.upload_dir / f"{internal_doc_number}-{stem}{extension}"

    written = 0
    try:
        with target_path.open("wb") as sink:
            chunk = first
            while chunk:
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "No s'accepten fitxers de més de "
                            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                        ),
                    )
                sink.write(chunk)
                chunk = await file.read(_CHUNK_BYTES)
    except Exception:
        # A partial file would otherwise sit there looking like a real upload and
        # fail extraction later with a confusing error.
        target_path.unlink(missing_ok=True)
        raise

    if written == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="El fitxer és buit."
        )

    return StoredUpload(target_path, content_type)
