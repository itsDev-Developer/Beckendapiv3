"""Shared error-response helper for the aiohttp routes.

Drop this in as bot/server/errors.py

Replaces the old per-route pattern of:

    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e)) from e

which had two problems: `e.with_traceback(None)` strips the traceback
before logging it, so `logging.critical(...)` only ever recorded the
exception's one-line repr -- the actual traceback (line numbers, call
stack) was thrown away right when you'd need it most. And returning
`text=str(e)` to the client leaks internal details (file paths, query
values, library internals) in a production HTTP response.
"""

import logging

from aiohttp import web

LOGGER = logging.getLogger(__name__)


def log_and_fail(e: Exception) -> web.HTTPInternalServerError:
    LOGGER.critical("Unhandled error: %s", e, exc_info=True)
    return web.HTTPInternalServerError(
        text='{"error": "internal_error"}',
        content_type="application/json",
    )
