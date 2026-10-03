from fastapi import APIRouter

from .app_settings import router as app_settings_router
from .auth import router as auth_router
from .backups import router as backups_router
from .documents import router as documents_router
from .history import router as history_router
from .llm import router as llm_router
from .meta import router as meta_router
from .reconciliation import router as reconciliation_router
from .statements import router as statements_router
from .status import router as status_router
from .tools import router as tools_router
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
api_router.include_router(statements_router, prefix="/statements", tags=["statements"])
api_router.include_router(
    reconciliation_router, prefix="/reconciliation", tags=["reconciliation"]
)
api_router.include_router(status_router, prefix="/status", tags=["status"])
api_router.include_router(tools_router, prefix="/tools", tags=["tools"])
api_router.include_router(backups_router, prefix="/backups", tags=["backups"])
api_router.include_router(history_router, prefix="/history", tags=["history"])

__all__ = ["api_router"]
