"""A shared configuration bag, one namespace per app.

This is what lets a new Cosecre app skip having a server of its own: point it at
a hub, give it a slug, and it has authenticated storage for its settings. Reads
need a signed-in user; writes need an admin.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from ..config import DOCUMENTS_APP_SLUG
from ..deps import get_current_user, get_db, require_admin
from ..models import AppSetting, User
from ..schemas import (
    APP_SLUG_PATTERN,
    SETTING_KEY_PATTERN,
    AppSettingRead,
    AppSettingsBundle,
    AppSettingWrite,
    MessageResponse,
)

router = APIRouter()

AppSlug = Annotated[str, Path(pattern=APP_SLUG_PATTERN, description="Lowercase app identifier.")]
SettingKey = Annotated[str, Path(pattern=SETTING_KEY_PATTERN)]


def _rows(session: Session, app_slug: str) -> list[AppSetting]:
    return (
        session.query(AppSetting)
        .filter(AppSetting.app_slug == app_slug)
        .order_by(AppSetting.key.asc())
        .all()
    )


@router.get("", response_model=list[str])
def list_apps(session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    slugs = {slug for (slug,) in session.query(AppSetting.app_slug).distinct().all() if slug}
    slugs.add(DOCUMENTS_APP_SLUG)
    return sorted(slugs)


@router.get("/{app_slug}/settings", response_model=AppSettingsBundle)
def read_settings(
    app_slug: AppSlug,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return AppSettingsBundle(
        app_slug=app_slug,
        settings={row.key: row.value for row in _rows(session, app_slug)},
    )


@router.put("/{app_slug}/settings", response_model=AppSettingsBundle)
def replace_settings(
    app_slug: AppSlug,
    payload: dict[str, Any],
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Replace an app's whole settings bundle.

    Keys absent from the body are deleted — this is a PUT, and an app rewriting
    its configuration should not have to remember what it dropped.
    """
    invalid = [key for key in payload if not _valid_key(key)]
    if invalid:
        # 422 as a literal: Starlette renamed its constant, and the numeric code
        # is the one thing that is stable across both spellings.
        raise HTTPException(
            status_code=422, detail=f"Invalid setting key(s): {', '.join(sorted(invalid))}"
        )

    existing = {row.key: row for row in _rows(session, app_slug)}
    for key, value in payload.items():
        row = existing.pop(key, None)
        if row is None:
            session.add(
                AppSetting(app_slug=app_slug, key=key, value=value, updated_by_id=admin.id)
            )
        else:
            row.value = value
            row.updated_by_id = admin.id
    for orphan in existing.values():
        session.delete(orphan)

    session.commit()
    return AppSettingsBundle(
        app_slug=app_slug,
        settings={row.key: row.value for row in _rows(session, app_slug)},
    )


@router.get("/{app_slug}/settings/{key}", response_model=AppSettingRead)
def read_setting(
    app_slug: AppSlug,
    key: SettingKey,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = (
        session.query(AppSetting)
        .filter(AppSetting.app_slug == app_slug, AppSetting.key == key)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    return AppSettingRead(
        app_slug=row.app_slug, key=row.key, value=row.value, updated_at=row.updated_at
    )


@router.put("/{app_slug}/settings/{key}", response_model=AppSettingRead)
def write_setting(
    app_slug: AppSlug,
    key: SettingKey,
    payload: AppSettingWrite,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = (
        session.query(AppSetting)
        .filter(AppSetting.app_slug == app_slug, AppSetting.key == key)
        .first()
    )
    if row is None:
        row = AppSetting(app_slug=app_slug, key=key)
        session.add(row)
    row.value = payload.value
    row.updated_by_id = admin.id
    session.commit()
    session.refresh(row)
    return AppSettingRead(
        app_slug=row.app_slug, key=row.key, value=row.value, updated_at=row.updated_at
    )


@router.delete("/{app_slug}/settings/{key}", response_model=MessageResponse)
def delete_setting(
    app_slug: AppSlug,
    key: SettingKey,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = (
        session.query(AppSetting)
        .filter(AppSetting.app_slug == app_slug, AppSetting.key == key)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    session.delete(row)
    session.commit()
    return MessageResponse(message=f"{app_slug}.{key} deleted.")


def _valid_key(key: str) -> bool:
    return bool(re.fullmatch(SETTING_KEY_PATTERN, key))
