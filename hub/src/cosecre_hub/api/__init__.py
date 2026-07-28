from fastapi import APIRouter

from .aim import router as aim_router
from .app_settings import router as app_settings_router
from .auth import router as auth_router
from .documents import router as documents_router
from .llm import router as llm_router
from .meta import router as meta_router
from .users import router as users_router

#: Everything under the versioned prefix. Grouped core-first so the generated
#: OpenAPI page reads in the order a new client integrates them.
api_router = APIRouter()
api_router.include_router(meta_router, prefix="/meta", tags=["meta"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(app_settings_router, prefix="/apps", tags=["apps"])
api_router.include_router(llm_router, prefix="/llm", tags=["llm"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(aim_router, prefix="/aim", tags=["aim"])

__all__ = ["api_router"]
