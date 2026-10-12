"""Public portal configuration only: never accept credentials in the shared bag."""
from urllib.parse import parse_qs, urlsplit
import re

from fastapi import HTTPException
from pydantic import AnyHttpUrl, TypeAdapter

SLUG = "cosecre-sfera"
KEYS = frozenset({"access_url", "centre"})


def validate_settings(payload: dict) -> dict[str, str]:
    if set(payload) - KEYS:
        raise HTTPException(422, "Esfer@ només admet access_url i centre; no hi desis credencials.")
    result = {}
    for key, value in payload.items():
        limit = 2048 if key == "access_url" else 200
        if not isinstance(value, str) or len(value) > limit:
            raise HTTPException(422, f"El camp {key} no és vàlid.")
        result[key] = value.strip()
    value = result.get("access_url", "")
    if value:
        try:
            TypeAdapter(AnyHttpUrl).validate_python(value)
            url = urlsplit(value)
            _ = url.port  # Reject malformed ports too.
            local = url.hostname in {"localhost", "127.0.0.1", "::1"}
            secure = url.scheme == "https" or (url.scheme == "http" and local)
            sensitive = any(re.search(r"password|token|secret|authorization|^code$", key, re.I) for key in parse_qs(url.query, keep_blank_values=True))
            if not secure or not url.hostname or url.username or url.password or sensitive:
                raise ValueError
        except ValueError:
            raise HTTPException(422, "Cal una URL HTTPS sense credencials; HTTP només per a proves locals.") from None
    return result
