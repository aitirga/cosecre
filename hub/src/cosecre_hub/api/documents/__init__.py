from fastapi import APIRouter

from .routes import create_documents_router
from .workspace import router as workspace_router

router = APIRouter()
router.include_router(workspace_router, prefix="/settings")
router.include_router(create_documents_router("invoice"), prefix="/invoices")
router.include_router(create_documents_router("ticket"), prefix="/tickets")

__all__ = ["router"]
