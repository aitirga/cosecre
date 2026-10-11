from fastapi import APIRouter, Depends

from ..deps import require_staff

from .app_settings import router as app_settings_router
from .auth import router as auth_router
from .backups import router as backups_router
from .documents import router as documents_router
from .history import router as history_router
from .llm import router as llm_router
from .meta import router as meta_router
from .reconciliation import router as reconciliation_router
from .statements import router as statements_router
from .statements_mirror import router as statements_mirror_router
from .status import router as status_router
from .tools import router as tools_router
from .users import router as users_router

#: Everything under the versioned prefix. Grouped core-first so the generated
#: OpenAPI page reads in the order a new client integrates them.
#:
#: Access is denied by default: only the routers listed as open take any signed-in
#: role (and check ownership themselves); everything else is the office's —
#: admins and Secretaria — so a route added later cannot leak to Professor/a by
#: forgetting a dependency.
api_router = APIRouter()
api_router.include_router(meta_router, prefix="/meta", tags=["meta"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])

staff = [Depends(require_staff)]
api_router.include_router(app_settings_router, prefix="/apps", tags=["apps"], dependencies=staff)
api_router.include_router(llm_router, prefix="/llm", tags=["llm"], dependencies=staff)
api_router.include_router(
    documents_router, prefix="/documents", tags=["documents"], dependencies=staff
)
api_router.include_router(
    statements_router, prefix="/statements", tags=["statements"], dependencies=staff
)
api_router.include_router(
    statements_mirror_router, prefix="/statements/mirror", tags=["statements"], dependencies=staff
)
api_router.include_router(
    reconciliation_router, prefix="/reconciliation", tags=["reconciliation"], dependencies=staff
)
api_router.include_router(status_router, prefix="/status", tags=["status"], dependencies=staff)
api_router.include_router(tools_router, prefix="/tools", tags=["tools"], dependencies=staff)
api_router.include_router(backups_router, prefix="/backups", tags=["backups"], dependencies=staff)
api_router.include_router(history_router, prefix="/history", tags=["history"], dependencies=staff)

__all__ = ["api_router"]
