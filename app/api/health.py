
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rate_limit import get_redis
from app.database import get_db
from app.utils.helpers import utcnow

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Liveness probe. Always returns 200 so orchestrators accept the service."""
    database = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        database = f"error: {type(exc).__name__}"

    redis = "disabled"
    if settings.REDIS_URL:
        try:
            client = await get_redis()
            await client.ping()
            redis = "ok"
        except Exception as exc:
            redis = f"error: {type(exc).__name__}"

    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": database,
        "redis": redis,
        "celery": settings.CELERY_ENABLED,
        "timestamp": utcnow(),
    }


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return {"status": "not ready", "database": f"error: {type(exc).__name__}"}
    return {"status": "ready"}
