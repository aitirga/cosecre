"""Cosecre Hub — the shared backend every Cosecre app talks to.

The hub owns three things so that client apps never have to:

* **Identity** — accounts, password hashing, access/refresh tokens, sessions.
* **Storage** — the database, uploaded files, and a per-app settings bag.
* **Model access** — a provider-agnostic LLM gateway, so API keys live here
  and only here.

Domain features live in modules on top of that core; the invoice/ticket
pipeline is the first one (:mod:`cosecre_hub.api.documents`).
"""

from importlib.metadata import PackageNotFoundError, version as _package_version

try:
    __version__ = _package_version("cosecre-hub")
except PackageNotFoundError:  # running from a source checkout without an install
    __version__ = "0.1.0"

#: Bumped only when a client-visible contract changes shape. Clients read this
#: from ``GET /api/v1/meta`` to decide whether they can talk to a given hub.
API_VERSION = "1"

__all__ = ["API_VERSION", "__version__"]
