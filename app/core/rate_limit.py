
from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.config import settings

_redis_client: Redis | None = None


async def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            str(settings.REDIS_URL),
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


TIER_LIMITS = {
    "free": settings.RATE_LIMIT_FREE,
    "starter": settings.RATE_LIMIT_STARTER,
    "pro": settings.RATE_LIMIT_PRO,
    "business": settings.RATE_LIMIT_BUSINESS,
}


async def check_rate_limit(
    user_id: str,
    tier: str,
    endpoint: str = "default",
) -> tuple[bool, dict]:
    """
    Returns (allowed, headers_dict)
    """
    redis = await get_redis()
    limit = TIER_LIMITS.get(tier, settings.RATE_LIMIT_FREE)

    key = f"ratelimit:{tier}:{user_id}:{endpoint}"
    current = await redis.incr(key)

    if current == 1:
        await redis.expire(key, 60)  # 1 minute window

    ttl = await redis.ttl(key)
    reset_time = 60 - ttl if ttl > 0 else 60

    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, limit - current)),
        "X-RateLimit-Reset": str(reset_time),
    }

    if current > limit:
        return False, headers

    return True, headers


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/ready", "/api/v1/health"]:
            await self.app(scope, receive, send)
            return

        # Get user from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        tier = getattr(request.state, "user_tier", "free")

        if user_id:
            allowed, headers = await check_rate_limit(str(user_id), tier, request.url.path)
            if not allowed:
                response = HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers=headers,
                )
                await response(scope, receive, send)
                return

        # Add headers to response
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers_list = list(message.get("headers", []))
                for k, v in headers.items():
                    headers_list.append((k.encode(), v.encode()))
                message["headers"] = headers_list
            await send(message)

        await self.app(scope, receive, send_wrapper)
