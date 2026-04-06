from fastapi import APIRouter

from .auth import router as auth_router
from .invoices import router as invoices_router
from .settings import router as settings_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(settings_router, prefix="/settings", tags=["settings"])
api_router.include_router(invoices_router, prefix="/invoices", tags=["invoices"])
