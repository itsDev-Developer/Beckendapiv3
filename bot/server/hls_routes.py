"""New routes to add to bot/server/stream_routes.py (or import and register
this RouteTableDef from bot/server/__init__.py's web_server()).

    GET /{chat_id}/{message_id}/hls.m3u8?hash=xxxxxx
    GET /{chat_id}/{message_id}/hls/{segment}?hash=xxxxxx

Auth mirrors the existing raw stream route: a valid `hash` (first six chars
of the Telegram file's unique_id) is required. If you want this gated
behind login instead of the hash-only scheme, add the same
`session.get('user')` check used elsewhere in stream_routes.py.
"""

import logging

from aiohttp import web

from bot.helper.exceptions import FIleNotFound, InvalidHash
from bot.helper.hls import ensure_hls, playlist_path, segment_path
from bot.server.custom_dl import ByteStreamer
from bot.server.errors import log_and_fail
from bot.telegram import multi_clients, workload_tracker

hls_routes = web.RouteTableDef()

# Reuse the same per-client ByteStreamer cache pattern as stream_routes.py.
_class_cache = {}


async def _get_streamer():
    index = await workload_tracker.least_loaded()
    client = multi_clients[index]
    if client not in _class_cache:
        _class_cache[client] = ByteStreamer(client)
    return index, _class_cache[client]


@hls_routes.get('/{chat_id}/{message_id}/hls.m3u8')
async def hls_playlist(request: web.Request):
    try:
        chat_id = int(f"-100{request.match_info['chat_id']}")
        message_id = int(request.match_info['message_id'])
        file_hash = request.query.get('hash', '')

        index, tg_connect = await _get_streamer()
        file_id = await tg_connect.get_file_properties(chat_id=chat_id, message_id=message_id)

        if file_id.unique_id[:6] != file_hash:
            raise InvalidHash

        m3u8_path = await ensure_hls(tg_connect, file_id, index, chat_id, message_id, file_hash)
        return web.FileResponse(
            m3u8_path,
            headers={"Content-Type": "application/vnd.apple.mpegurl"},
        )
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message) from e
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message) from e
    except RuntimeError as e:
        raise log_and_fail(e) from e
    except Exception as e:
        raise log_and_fail(e) from e


@hls_routes.get('/{chat_id}/{message_id}/hls/{segment}')
async def hls_segment(request: web.Request):
    try:
        chat_id = int(f"-100{request.match_info['chat_id']}")
        message_id = int(request.match_info['message_id'])
        file_hash = request.query.get('hash', '')
        segment = request.match_info['segment']

        path = segment_path(chat_id, message_id, file_hash, segment)
        if not path or not __import__("os").path.exists(path):
            raise web.HTTPNotFound(text="Segment not found")

        return web.FileResponse(path, headers={"Content-Type": "video/mp2t"})
    except ValueError as e:
        raise web.HTTPBadRequest(text=str(e)) from e
