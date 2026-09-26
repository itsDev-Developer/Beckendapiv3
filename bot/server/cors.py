"""CORS middleware -- restrict browser access to configured frontend origins.

Drop this in as bot/server/cors.py

If Telegram.FRONTEND_URLS is empty (the default), this middleware is a
no-op: no CORS headers are added, matching the previous behaviour exactly.

Once FRONTEND_URL is set, this:
  - answers CORS preflight (OPTIONS) requests directly;
  - echoes Access-Control-Allow-Origin only for an Origin in the allow-list;
  - returns 403 for a request whose Origin header is present but NOT in the
    allow-list (this is a server-side rejection, on top of the browser's own
    CORS enforcement -- it stops a disallowed *browser* origin from reading
    responses, and also stops it from triggering side effects at all);
  - lets requests through unchanged when there's no Origin header at all
    (native apps, curl, video players, and server-to-server calls typically
    don't send one, and none of those are the "frontend in a browser"
    scenario this feature targets).
"""

from aiohttp import web

from bot.config import Telegram

_ALLOWED_METHODS = "GET, POST, OPTIONS"
_ALLOWED_HEADERS = "Content-Type, Authorization"


@web.middleware
async def cors_middleware(request: web.Request, handler):
    allowed = Telegram.FRONTEND_URLS
    if not allowed:
        return await handler(request)

    origin = request.headers.get("Origin")

    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    elif origin and origin not in allowed:
        return web.json_response(
            {"error": "origin_not_allowed"},
            status=403,
        )
    else:
        resp = await handler(request)

    if origin and origin in allowed:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
    resp.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
    return resp
