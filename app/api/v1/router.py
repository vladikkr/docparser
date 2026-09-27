from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.v1 import auth, billing, documents, webhooks

router = APIRouter()

router.include_router(health_router)
router.include_router(auth.router)
router.include_router(documents.router)
router.include_router(billing.router)
router.include_router(webhooks.router)


@router.get("/")
async def api_root():
    return {
        "name": "DocParser.ru API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
