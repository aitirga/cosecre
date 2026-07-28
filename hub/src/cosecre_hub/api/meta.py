from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import API_VERSION, __version__
from ..config import DOCUMENTS_APP_SLUG, Settings
from ..deps import get_db, get_llm_registry, get_settings
from ..models import AppSetting, User
from ..schemas import HubCapabilities, HubMeta
from ..services.llm import LLMRegistry

router = APIRouter()


@router.get("", response_model=HubMeta)
def read_meta(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    registry: LLMRegistry = Depends(get_llm_registry),
):
    """Describe this hub. Deliberately unauthenticated.

    A client has to be able to check a URL someone just typed *before* it has any
    credentials for it, so this is the one endpoint that answers without a token.
    It reports presence, never values: which features are on, whether an account
    exists — nothing that would help someone who should not be here.
    """
    user_count = session.query(User).count()
    registered_apps = {
        slug for (slug,) in session.query(AppSetting.app_slug).distinct().all() if slug
    }
    registered_apps.add(DOCUMENTS_APP_SLUG)

    return HubMeta(
        name=settings.app_name,
        version=__version__,
        api_version=API_VERSION,
        api_prefix=settings.api_prefix,
        capabilities=HubCapabilities(
            llm=registry.any_configured(),
            documents=True,
            google_sheets=settings.google_service_account_file is not None,
        ),
        apps=sorted(registered_apps),
        accepts_registration=settings.allow_open_registration or user_count == 0,
        has_users=user_count > 0,
    )
