from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

#: Slugs are used in URLs and as a storage key, so they are kept to a shape that
#: is unambiguous in both.
APP_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"
SETTING_KEY_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,126}$"


class AppSettingRead(BaseModel):
    app_slug: str
    key: str
    value: Any
    updated_at: datetime


class AppSettingWrite(BaseModel):
    value: Any = Field(description="Any JSON value. Replaces the stored value wholesale.")


class AppSettingsBundle(BaseModel):
    """Every key an app has stored, as one object.

    Apps read their whole configuration in a single request on startup, so the
    bundle — not the individual key — is the endpoint that matters.
    """

    app_slug: str
    settings: dict[str, Any]
