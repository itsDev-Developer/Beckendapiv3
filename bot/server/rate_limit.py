"""Per-IP rate limiting middleware.

Drop this in as bot/server/rate_limit.py

Uses a fixed-window counter per client IP. In-memory by default (correct
for a single instance); when Telegram.REDIS_URL is set, counters are kept
in Redis instead so the limit is enforced across every instance behind
your load balancer, not per-process.

POST /login gets its own, stricter window (LOGIN_RATE_LIMIT_*) to slow
down credential brute-forcing; every other route uses the general window
(RATE_LIMIT_*). Set either *_REQUESTS to 0 to disable that limit.
"""

import logging
import time

from aiohttp import web

from bot.config import Telegram

LOGGER = logging.getLogger(__name__)

_redis = None
if Telegram.REDIS_URL:
    try:
        from redis.asyncio import from_url
        _redis = from_url(Telegram.REDIS_URL, decode_responses=True)
    except Exception as e:
        LOGGER.warning(
            "REDIS_URL is set but the Redis client could not be created (%s); "
            "falling back to in-memory, per-process rate limiting.", e,
        )
        _redis = None

# In-memory fallback / default store: {bucket_key: (window_start_epoch, count)}
_local_buckets = {}


def _client_ip(request: web.Request) -> str:
    # Respect a reverse proxy's forwarded header if present (Heroku, most
    # container platforms, and typical nginx/Cloudflare setups set this).
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    peer = request.remote
    return peer or "unknown"


async def _hit(bucket_key: str, window_seconds: int) -> int:
    """Increment the counter for this window and return the new count."""
    now = int(time.time())
    window_start = now - (now % window_seconds)

    if _redis is not None:
        try:
            redis_key = f"surftg:ratelimit:{bucket_key}:{window_start}"
            count = await _redis.incr(redis_key)
            if count == 1:
                await _redis.expire(redis_key, window_seconds + 1)
            return count
        except Exception as e:
            LOGGER.debug("Redis rate-limit read failed, using local counter: %s", e)

    stored_start, count = _local_buckets.get(bucket_key, (window_start, 0))
    if stored_start != window_start:
        count = 0
        stored_start = window_start
    count += 1
    _local_buckets[bucket_key] = (stored_start, count)
    return count


def _limits_for(request: web.Request):
    if request.method == "POST" and request.path == "/login":
        return Telegram.LOGIN_RATE_LIMIT_REQUESTS, Telegram.LOGIN_RATE_LIMIT_WINDOW
    return Telegram.RATE_LIMIT_REQUESTS, Telegram.RATE_LIMIT_WINDOW


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    max_requests, window_seconds = _limits_for(request)
    if max_requests <= 0:
        return await handler(request)

    ip = _client_ip(request)
    scope = "login" if (request.method == "POST" and request.path == "/login") else "general"
    count = await _hit(f"{scope}:{ip}", window_seconds)

    if count > max_requests:
        return web.json_response(
            {"error": "rate_limited", "retry_after_seconds": window_seconds},
            status=429,
            headers={"Retry-After": str(window_seconds)},
        )
    return await handler(request)
