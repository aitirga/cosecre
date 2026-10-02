from fastapi import APIRouter

from .migration import router as migration_router
from .routes import router as records_router
from .workspace import router as workspace_router

router = APIRouter()
router.include_router(workspace_router, prefix="/settings")
router.include_router(migration_router, prefix="/migration")
router.include_router(records_router, prefix="/records")

__all__ = ["router"]
