from __future__ import annotations

from pydantic import BaseModel


class HubCapabilities(BaseModel):
    """What this hub can actually do right now.

    A client reads this before showing its own UI: no configured model provider
    means the extraction buttons should say why they are disabled rather than
    fail on click.
    """

    auth: bool = True
    app_settings: bool = True
    llm: bool = False
    documents: bool = False
    google_sheets: bool = False
    #: Jev is configured as the second opinion on closed-list fields.
    classifier: bool = False


class HubMeta(BaseModel):
    """Unauthenticated hub description.

    This is the endpoint a client hits to validate a URL someone typed into a
    "connect to your hub" box, which is why it must never require a token and
    must never leak configuration values — only whether things are present.
    """

    name: str
    product: str = "cosecre-hub"
    version: str
    api_version: str
    api_prefix: str
    capabilities: HubCapabilities
    apps: list[str]
    #: False once the hub has an account, so a client can offer "create the
    #: first admin" exactly when that is possible.
    accepts_registration: bool
    has_users: bool
