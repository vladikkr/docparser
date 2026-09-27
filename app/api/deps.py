from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_token, hash_api_key
from app.database import get_db
from app.models import APIKey, User, UserTier


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(None),
) -> User:
    """Get current user from JWT token"""
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("Missing or invalid authorization header")

    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise AuthenticationError("Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Invalid token payload")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise AuthenticationError("User not found")

    if not user.is_active:
        raise AuthorizationError("User account is disabled")

    # Attach to request state for rate limiting
    request.state.user_id = user.id
    request.state.user_tier = user.tier.value

    return user


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(None),
) -> User | None:
    """Get current user if token provided, otherwise None"""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    try:
        return await get_current_user(request, db, authorization)
    except (AuthenticationError, AuthorizationError):
        return None


async def get_api_key_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> User:
    """Get user from API key"""
    if not x_api_key:
        raise AuthenticationError("Missing X-API-Key header")

    key_hash = hash_api_key(x_api_key)

    result = await db.execute(
        select(APIKey, User)
        .join(User, APIKey.user_id == User.id)
        .where(APIKey.key_hash == key_hash, APIKey.is_active == True, User.is_active == True)
    )
    row = result.first()

    if not row:
        raise AuthenticationError("Invalid API key")

    api_key, user = row

    # Update last used
    from datetime import datetime
    api_key.last_used_at = datetime.utcnow()
    await db.commit()

    # Attach to request state
    request.state.user_id = user.id
    request.state.user_tier = user.tier.value
    request.state.api_key_id = api_key.id

    return user


async def get_tier_limit(user: User = Depends(get_current_user)) -> int:
    """Get rate limit for user's tier"""
    from app.core.rate_limit import TIER_LIMITS
    return TIER_LIMITS.get(user.tier.value, settings.RATE_LIMIT_FREE)


async def require_tier(*allowed_tiers: UserTier):
    """Dependency to require specific tier(s)"""
    async def check_tier(user: User = Depends(get_current_user)) -> User:
        if user.tier not in allowed_tiers:
            raise AuthorizationError(f"Requires one of: {[t.value for t in allowed_tiers]}")
        return user
    return check_tier


# Convenience dependencies
require_starter = require_tier(UserTier.STARTER, UserTier.PRO, UserTier.BUSINESS)
require_pro = require_tier(UserTier.PRO, UserTier.BUSINESS)
require_business = require_tier(UserTier.BUSINESS)
