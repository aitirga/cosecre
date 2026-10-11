"""The Assistent talking to the hub's own API, as the person it is talking to.

Requests go through the whole app in-process (``httpx.ASGITransport``): the
same routes, validation, permission checks, sheet mirroring and history the
web app gets. Nothing here can do what the person could not do by hand,
because it is the person's own token that signs every call.

Which routes it may touch is decided here, by the route a path resolves to:

* reads (``GET``) of anything but sign-in, downloads and the chat itself;
* writes only as a proposal a person confirms, and never to accounts, sign-in,
  backups, the history, the model gateway, migrations or file uploads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import anyio.from_thread
import httpx

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

#: Route prefixes (after the API prefix) no proposal may write to.
WRITE_DENIED = (
    "/auth",
    "/users",
    "/backups",
    "/history",
    "/llm",
    "/assistant",
    "/meta",
    "/documents/migration",
)
#: Routes no read may touch: credentials, the chat, and files rather than data.
READ_DENIED = ("/auth", "/assistant", "/backups/{name}")
READ_DENIED_SUFFIXES = ("/file", "/files.zip")

#: What a read hands back to the model at most, in characters.
MAX_READ_CHARS = 24_000


class BridgeRefused(ValueError):
    """The call is not one the Assistent may make; the message says why."""


@dataclass
class Resolved:
    method: str
    #: The path as called, without the API prefix — ``/documents/records/DOC-1``.
    path: str
    #: The route's template, without the prefix — ``/documents/records/{reference}``.
    template: str
    params: dict[str, str]


@dataclass
class BridgeResponse:
    status_code: int
    data: Any
    ok: bool

    def detail(self) -> str:
        if isinstance(self.data, dict) and isinstance(self.data.get("detail"), str):
            return self.data["detail"]
        if isinstance(self.data, dict) and isinstance(self.data.get("detail"), list):
            return "; ".join(str(item.get("msg", item)) for item in self.data["detail"])
        return "" if self.ok else f"Error {self.status_code}"


class Bridge:
    def __init__(self, app, token: str):
        self.app = app
        self._token = token
        self._prefix = app.state.settings.api_prefix

    # ── Resolving ───────────────────────────────────────────────────────────

    def resolve(self, method: str, path: str) -> Resolved:
        method = (method or "GET").upper()
        parts = urlsplit((path or "").strip())
        if parts.scheme or parts.netloc:
            raise BridgeRefused("Només es poden cridar rutes del hub (un camí com /documents/records).")
        bare = parts.path
        if bare.startswith(self._prefix):
            bare = bare[len(self._prefix):]
        if not bare.startswith("/") or ".." in bare:
            raise BridgeRefused("La ruta ha de començar per / (per exemple /documents/records).")
        bare = bare.rstrip("/") or "/"
        wrong_method = False
        for pattern, template, methods in self._routes():
            if pattern.fullmatch(bare):
                if method in methods:
                    return Resolved(method, bare, template, dict(parse_qsl(parts.query)))
                wrong_method = True
        if wrong_method:
            raise BridgeRefused(f"La ruta {bare} no admet {method}.")
        raise BridgeRefused(f"No hi ha cap ruta {method} {bare}. Consulta el catàleg (list_api).")

    def _routes(self) -> list[tuple[re.Pattern[str], str, set[str]]]:
        """``(pattern, template, methods)`` per path, in the app's own order.

        Read off the OpenAPI document rather than the router: it is the API's
        public shape, stable across FastAPI's internals, and in declaration
        order — so ``/records/files.zip`` is still tried before ``/records/{reference}``.
        """
        cached = getattr(self.app.state, "assistant_routes", None)
        if cached is not None:
            return cached
        routes = []
        for full_path, operations in self.app.openapi().get("paths", {}).items():
            if not full_path.startswith(self._prefix):
                continue
            template = full_path[len(self._prefix):]
            pattern = re.compile(
                "".join(
                    "[^/]+" if part.startswith("{") else re.escape(part)
                    for part in re.split(r"(\{[^}]+\})", template)
                    if part
                )
            )
            routes.append((pattern, template, {method.upper() for method in operations}))
        self.app.state.assistant_routes = routes
        return routes

    def check_read(self, resolved: Resolved) -> None:
        if resolved.method != "GET":
            raise BridgeRefused("Per llegir només es pot fer servir GET; per canviar res, proposa-ho.")
        if resolved.template.startswith(READ_DENIED) or resolved.template.endswith(READ_DENIED_SUFFIXES):
            raise BridgeRefused(f"{resolved.template} no és una ruta que l'assistent pugui llegir.")

    def check_write(self, resolved: Resolved) -> None:
        if resolved.method not in WRITE_METHODS:
            raise BridgeRefused("Una proposta només conté POST, PUT, PATCH o DELETE.")
        if resolved.template.startswith(WRITE_DENIED) or resolved.template.endswith("/upload"):
            raise BridgeRefused(
                f"{resolved.method} {resolved.template} queda fora de l'abast de l'assistent "
                "(comptes, accés, còpies, historial, migracions i pujades de fitxers)."
            )

    def writable(self, method: str, template: str) -> bool:
        return method in WRITE_METHODS and not (
            template.startswith(WRITE_DENIED) or template.endswith("/upload")
        )

    def readable(self, method: str, template: str) -> bool:
        return method == "GET" and not (
            template.startswith(READ_DENIED) or template.endswith(READ_DENIED_SUFFIXES)
        )

    def has_route(self, method: str, path: str) -> bool:
        try:
            self.resolve(method, path)
        except BridgeRefused:
            return False
        return True

    # ── Calling ─────────────────────────────────────────────────────────────

    async def acall(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> BridgeResponse:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://assistant.internal", timeout=120
        ) as client:
            response = await client.request(
                method,
                f"{self._prefix}{path}",
                params=params or None,
                json=body if method in WRITE_METHODS and body is not None else None,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        content_type = response.headers.get("content-type", "")
        if response.status_code == 204 or not response.content:
            data: Any = None
        elif "json" in content_type:
            data = response.json()
        else:
            data = {"detail": f"La ruta ha retornat {content_type or 'contingut'} en lloc de dades."}
        return BridgeResponse(response.status_code, data, response.is_success)

    def call(self, method: str, path: str, **kwargs) -> BridgeResponse:
        """:meth:`acall` from a worker thread, which is where a chat turn runs."""
        return anyio.from_thread.run(lambda: self.acall(method, path, **kwargs))

    # ── Describing ──────────────────────────────────────────────────────────

    def catalog(self, search: str = "") -> str:
        """The API as one line per operation, with what a write's body takes."""
        spec = self.app.openapi()
        components = spec.get("components", {}).get("schemas", {})
        needle = (search or "").strip().lower()
        lines: list[str] = []
        for full_path, operations in spec.get("paths", {}).items():
            template = full_path[len(self._prefix):] if full_path.startswith(self._prefix) else full_path
            for method, operation in operations.items():
                verb = method.upper()
                readable, writable = self.readable(verb, template), self.writable(verb, template)
                if not (readable or writable):
                    continue
                summary = operation.get("summary", "")
                text = f"{verb} {template} {summary} {' '.join(operation.get('tags', []))}".lower()
                if needle and not all(word in text for word in needle.split()):
                    continue
                line = f"{verb} {template} — {summary}" + ("" if readable else " [escriptura: només via proposta]")
                query = [
                    _param(item) for item in operation.get("parameters", []) if item.get("in") == "query"
                ]
                if query:
                    line += f"\n    query: {', '.join(query)}"
                body = (
                    operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
                )
                if body:
                    line += f"\n    body: {_describe_schema(body, components)}"
                lines.append(line)
        if not lines:
            return "Cap ruta coincideix amb la cerca."
        return "\n".join(lines)


def _param(item: dict[str, Any]) -> str:
    schema = item.get("schema", {})
    kind = schema.get("type") or "/".join(
        sub.get("type", "") for sub in schema.get("anyOf", []) if sub.get("type") != "null"
    )
    return f"{item.get('name')}{'' if item.get('required') else '?'}:{kind or 'any'}"


def _describe_schema(schema: dict[str, Any], components: dict[str, Any], depth: int = 0) -> str:
    if "$ref" in schema:
        schema = components.get(schema["$ref"].rsplit("/", 1)[-1], {})
    if "anyOf" in schema:
        options = [s for s in schema["anyOf"] if s.get("type") != "null"]
        nullable = len(options) < len(schema["anyOf"])
        inner = " | ".join(_describe_schema(s, components, depth) for s in options) or "any"
        return f"{inner}{'?' if nullable else ''}"
    if "enum" in schema:
        return "|".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    kind = schema.get("type")
    if kind == "object" and "properties" in schema and depth < 2:
        fields = [
            f"{name}: {_describe_schema(sub, components, depth + 1)}"
            for name, sub in schema["properties"].items()
        ]
        return "{" + ", ".join(fields) + "}"
    if kind == "array":
        return f"[{_describe_schema(schema.get('items', {}), components, depth + 1)}]"
    if schema.get("format") in {"date", "date-time"}:
        return schema["format"]
    return kind or "any"
