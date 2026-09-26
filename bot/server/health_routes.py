"""GET /healthz -- liveness/readiness check for load balancers and orchestrators.

Drop this in as bot/server/health_routes.py
"""

import asyncio
import logging

from aiohttp import web

from bot.helper.database import Database
from bot.telegram import StreamBot, multi_clients

LOGGER = logging.getLogger(__name__)
health_routes = web.RouteTableDef()
db = Database()


@health_routes.get('/healthz')
async def healthz(request: web.Request):
    checks = {"mongo": False, "telegram": False}

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, db.mongo_client.admin.command, 'ping')
        checks["mongo"] = True
    except Exception as e:
        LOGGER.error("Health check: Mongo ping failed: %s", e)

    try:
        checks["telegram"] = bool(getattr(StreamBot, "is_connected", False))
    except Exception as e:
        LOGGER.error("Health check: Telegram client check failed: %s", e)

    healthy = all(checks.values())
    return web.json_response(
        {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "worker_clients": len(multi_clients),
        },
        status=200 if healthy else 503,
    )
