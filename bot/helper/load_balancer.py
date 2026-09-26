"""Load balancing across Telegram worker clients.

Drop this in as bot/helper/load_balancer.py

In-memory by default -- a shared dict keyed by client index, same as the
original `work_loads` global. That's correct for a single process. If
REDIS_URL is set, workload counters are additionally kept in Redis so
multiple horizontally-scaled instances of this API pick the truly
least-loaded worker bot across the whole fleet, not just within their own
process.

If the `redis` package isn't installed, or REDIS_URL is unset, this
degrades transparently to local-only tracking -- nothing else needs to
change.
"""

import logging

from bot.config import Telegram

LOGGER = logging.getLogger(__name__)

_redis = None
if Telegram.REDIS_URL:
    try:
        from redis.asyncio import from_url
        _redis = from_url(Telegram.REDIS_URL, decode_responses=True)
        LOGGER.info("Load balancing: Redis-backed (shared across instances)")
    except Exception as e:
        LOGGER.warning(
            "REDIS_URL is set but the Redis client could not be created (%s); "
            "falling back to in-memory, per-process load balancing.", e,
        )
        _redis = None
else:
    LOGGER.info("Load balancing: in-memory (single-process only)")


class WorkloadTracker:
    """Tracks active-stream counts per Telegram client index.

    `local` is always kept up to date and is the fallback source of truth.
    When Redis is configured, counts are mirrored there so other instances
    can see this process's load, and `least_loaded()` reads the fleet-wide
    totals instead of just the local ones.
    """

    def __init__(self, local: dict):
        self.local = local

    def _key(self, index) -> str:
        return f"surftg:workload:{index}"

    async def incr(self, index) -> None:
        self.local[index] = self.local.get(index, 0) + 1
        if _redis is not None:
            try:
                await _redis.incr(self._key(index))
            except Exception as e:
                LOGGER.debug("Redis incr failed, continuing with local count only: %s", e)

    async def decr(self, index) -> None:
        self.local[index] = max(0, self.local.get(index, 0) - 1)
        if _redis is not None:
            try:
                await _redis.decr(self._key(index))
            except Exception as e:
                LOGGER.debug("Redis decr failed, continuing with local count only: %s", e)

    async def least_loaded(self):
        """Return the client index with the fewest active streams."""
        if _redis is not None:
            try:
                counts = {}
                for index in self.local:
                    raw = await _redis.get(self._key(index))
                    counts[index] = int(raw) if raw is not None else 0
                if counts:
                    return min(counts, key=counts.get)
            except Exception as e:
                LOGGER.debug("Redis read failed, falling back to local counts: %s", e)
        return min(self.local, key=self.local.get)
