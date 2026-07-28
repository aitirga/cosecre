"""AIM's tunables.

Stored in the shared per-app settings bag rather than a table of AIM's own,
which means every knob below is already editable through the tested
``PUT /api/v1/apps/cosecre-aim/settings`` endpoint without a line of new UI.
Unknown keys are ignored and missing ones fall back to the defaults here, so a
hub that has never been configured still runs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ...config import AIM_APP_SLUG
from ...models import AppSetting


class AimSettings(BaseModel):
    """Defaults chosen so a fresh install is usable without configuration."""

    #: Tokens a student may spend on tutor turns in one session.
    default_token_budget: int = Field(default=60_000, ge=1_000)
    #: Null means "whatever the provider's default is".
    tutor_model: str | None = None
    authoring_model: str | None = None
    #: How often the student profile is rebuilt, in student turns.
    context_refresh_every_turns: int = Field(default=3, ge=1)
    #: Turns sent verbatim. Older ones are represented by the profile instead —
    #: without this, input tokens grow quadratically and a 60k budget is gone in
    #: about fifteen exchanges.
    history_window_messages: int = Field(default=20, ge=2)
    max_output_tokens: int = Field(default=1_200, ge=128)
    #: Prepended to the tutor's instructions, for a hub with house rules.
    tutor_preamble_override: str = ""


def read_aim_settings(session: Session) -> AimSettings:
    rows = {
        row.key: row.value
        for row in session.query(AppSetting).filter(AppSetting.app_slug == AIM_APP_SLUG).all()
    }
    try:
        return AimSettings.model_validate(rows)
    except ValidationError:
        # A hand-edited setting that no longer validates must not take the app
        # down; the defaults are always safe.
        return AimSettings()
