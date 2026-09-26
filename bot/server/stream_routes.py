import logging
import math
import mimetypes
import secrets
from aiohttp import web
from bot.helper.chats import get_chats, post_playlist, posts_chat, posts_db_file
from bot.helper.database import Database
from bot.helper.search import search
from bot.helper.thumbnail import get_image
from bot.telegram import multi_clients, workload_tracker
from aiohttp_session import get_session
from bot.config import Telegram
from bot.helper.exceptions import FIleNotFound, InvalidHash
from bot.helper.index import get_files, posts_file
from bot.helper.peers import safe_get_chat, warm_up_all
from bot.server.custom_dl import ByteStreamer
from bot.server.errors import log_and_fail
from bot.helper.cache import rm_cache

from bot.telegram import StreamBot, UserBot

routes = web.RouteTableDef()
db = Database()


@routes.get('/login')
async def login_form(request):
    session = await get_session(request)
    return web.json_response({
        'authenticated': 'user' in session,
    })


@routes.post('/login')
async def login_route(request):
    session = await get_session(request)
    if 'user' in session:
        return web.json_response({'authenticated': True, 'is_admin': session['user'] == Telegram.ADMIN_USERNAME})
    data = await request.post()
    username = data.get('username')
    password = data.get('password')
    if (username == Telegram.USERNAME and password == Telegram.PASSWORD) or (username == Telegram.ADMIN_USERNAME and password == Telegram.ADMIN_PASSWORD):
        session['user'] = username
        return web.json_response({'authenticated': True, 'is_admin': username == Telegram.ADMIN_USERNAME})
    return web.json_response({'authenticated': False, 'error': 'Invalid username or password'}, status=401)


@routes.post('/logout')
async def logout_route(request):
    session = await get_session(request)
    session.pop('user', None)
    return web.json_response({'authenticated': False})


@routes.post('/create')
async def create_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    folderName = data.get('folderName')
    thumbnail = data.get('thumbnail')
    parent_dir = data.get('parent_dir')
    parent_dir = parent_dir.split('db=')[-1] if 'db=' in parent_dir else 'root'
    await db.create_folder(parent_dir, folderName, thumbnail)
    return web.json_response({'created': True, 'parent_folder': parent_dir})


@routes.post('/delete')
async def delete_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.json()
    id = data.get('delete_id')
    parent = data.get('parent')
    if not (success := db.delete(id)):
        return web.HTTPInternalServerError()
    return web.json_response({'deleted': True, 'parent_folder': parent})


@routes.post('/edit')
async def editFolder_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    folderName = data.get('folderName')
    thumbnail = data.get('thumbnail')
    id = data.get('folder_id')
    parent = data.get('parent')
    success = await db.edit(id, folderName, thumbnail)
    if not success:
        return web.HTTPInternalServerError()
    return web.json_response({'updated': True, 'parent_folder': parent})


@routes.post('/edit_post')
async def editPost_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    fileName = data.get('fileName')
    thumbnail = data.get('filethumbnail')
    id = data.get('file_id')
    parent = data.get('file_folder_id')
    success = await db.edit(id, fileName, thumbnail)
    if not success:
        return web.HTTPInternalServerError()
    return web.json_response({'updated': True, 'parent_folder': parent})


@routes.get('/searchDbFol')
async def searchDbFolder_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    query = request.query.get('query', '')
    folder_names = await db.search_DbFolder(query)
    return web.json_response(folder_names)


@routes.post('/send')
async def send_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    chat_id = data.get('chatId')
    chat_id = f"-100{chat_id}"
    folder_id = data.get('folderId')
    selected_ids = data.get('selectedIds')
    if not all([chat_id, folder_id, selected_ids]):
        return web.json_response({'error': 'Missing required data in request'}, status=400)

    formatted_entries = []
    try:
        for entry in selected_ids.split(','):
            file_id, hash, filename, size, file_type, thumbnail = entry.split('|')
            formatted_entries.append({
                'chat_id': chat_id,
                'parent_folder': folder_id,
                'file_id': file_id,
                'hash': hash,
                'name': filename,
                'size': size,
                'file_type': file_type,
                'thumbnail': thumbnail,
                'type': 'file'
            })
    except ValueError:
        return web.json_response(
            {'error': 'Each selectedIds entry must have exactly 6 "|"-separated fields'},
            status=400,
        )

    await db.add_json(formatted_entries)
    return web.json_response({'created': len(formatted_entries), 'parent_folder': folder_id})


@routes.get('/reload')
async def reload_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})

    chat_id = request.query.get('chatId', '')
    if chat_id == 'home':
        rm_cache()
        return web.json_response({'reloaded': 'home'})
    else:
        rm_cache(f"-100{chat_id}")
        return web.json_response({'reloaded': chat_id})


@routes.post('/config')
async def editConfig_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    channel = data.get('channel')
    theme = data.get('theme')
    success = await db.update_config(theme=theme, auth_channel=channel)
    if not success:
        return web.HTTPInternalServerError()
    if channel:
        new_channels = [c.strip() for c in channel.split(",") if c.strip()]
        warm_clients = [(StreamBot, "StreamBot")] + [
            (client, f"worker-{idx}") for idx, client in multi_clients.items() if idx != 0
        ]
        if Telegram.SESSION_STRING:
            warm_clients.append((UserBot, "UserBot"))
        await warm_up_all(warm_clients, new_channels)
    return web.json_response({'updated': True})



@routes.get('/')
async def home_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        try:
            channels = await get_chats()
            playlists = await db.get_Dbfolder()
            is_admin = username == Telegram.ADMIN_USERNAME
            return web.json_response({
                'channels': await posts_chat(channels),
                'playlists': await post_playlist(playlists),
                'is_admin': is_admin,
            })
        except Exception as e:
            raise log_and_fail(e) from e
    else:
        return web.json_response({'error': 'Authentication required'}, status=401)


@routes.get('/playlist')
async def playlist_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        try:
            parent_id = request.query.get('db')
            page = request.query.get('page', '1')
            playlists = await db.get_Dbfolder(parent_id, page=page)
            files = await db.get_dbFiles(parent_id, page=page)
            text = await db.get_info(parent_id)
            is_admin = username == Telegram.ADMIN_USERNAME
            return web.json_response({
                'parent_id': parent_id,
                'message': text,
                'playlists': await post_playlist(playlists),
                'files': await posts_db_file(files),
                'is_admin': is_admin,
            })
        except Exception as e:
            raise log_and_fail(e) from e
    else:
        return web.json_response({'error': 'Authentication required'}, status=401)


@routes.get('/search/db/{parent}')
async def dbsearch_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        parent = request.match_info['parent']
        page = request.query.get('page', '1')
        query = request.query.get('q')
        is_admin = username == Telegram.ADMIN_USERNAME
        try:
            files = await db.search_dbfiles(id=parent, page=page, query=query)
            name = await db.get_info(parent)
            text = f"{name} - {query}"
            return web.json_response({
                'parent_id': parent,
                'query': query,
                'message': text,
                'files': await posts_db_file(files),
                'is_admin': is_admin,
            })
        except Exception as e:
            raise log_and_fail(e) from e
    else:
        return web.json_response({'error': 'Authentication required'}, status=401)


@routes.get('/channel/{chat_id}')
async def channel_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        chat_id = request.match_info['chat_id']
        chat_id = f"-100{chat_id}"
        page = request.query.get('page', '1')
        is_admin = username == Telegram.ADMIN_USERNAME
        try:
            posts = await get_files(chat_id, page=page)
            chat = await safe_get_chat(StreamBot, int(chat_id))
            return web.json_response({
                'chat_id': chat_id.replace("-100", ""),
                'title': chat.title,
                'files': await posts_file(posts, chat_id),
                'is_admin': is_admin,
            })
        except Exception as e:
            raise log_and_fail(e) from e
    else:
        return web.json_response({'error': 'Authentication required'}, status=401)


@routes.get('/search/{chat_id}')
async def search_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        chat_id = request.match_info['chat_id']
        chat_id = f"-100{chat_id}"
        page = request.query.get('page', '1')
        query = request.query.get('q')
        is_admin = username == Telegram.ADMIN_USERNAME
        try:
            posts = await search(chat_id, page=page, query=query)
            chat = await safe_get_chat(StreamBot, int(chat_id))
            text = f"{chat.title} - {query}"
            return web.json_response({
                'chat_id': chat_id.replace("-100", ""),
                'query': query,
                'message': text,
                'files': await posts_file(posts, chat_id),
                'is_admin': is_admin,
            })
        except Exception as e:
            raise log_and_fail(e) from e
    else:
        return web.json_response({'error': 'Authentication required'}, status=401)


@routes.get('/api/thumb/{chat_id}', allow_head=True)
async def get_thumbnail(request):
    chat_id = request.match_info['chat_id']
    if message_id := request.query.get('id'):
        img = await get_image(chat_id, message_id)
    else:
        img = await get_image(chat_id, None)
    response = web.FileResponse(img)
    response.content_type = "image/jpeg"
    return response


@routes.get('/watch/{chat_id}', allow_head=True)
async def stream_handler_watch(request: web.Request):
    session = await get_session(request)
    if username := session.get('user'):
        try:
            chat_id = request.match_info['chat_id']
            chat_id = f"-100{chat_id}"
            message_id = request.query.get('id')
            secure_hash = request.query.get('hash')
            return web.json_response({
                'id': message_id,
                'chat_id': chat_id.removeprefix('-100'),
                'hash': secure_hash,
                'stream_url': f"/{chat_id.removeprefix('-100')}/stream?id={message_id}&hash={secure_hash}",
            })
        except Exception as e:
            raise log_and_fail(e) from e
    else:
        return web.json_response({'error': 'Authentication required'}, status=401)


@routes.get('/{chat_id}/{encoded_name}', allow_head=True)
async def stream_handler(request: web.Request):
    try:
        chat_id = request.match_info['chat_id']
        chat_id = f"-100{chat_id}"
        message_id = request.query.get('id')
        #name = request.match_info['encoded_name']
        secure_hash = request.query.get('hash')
        if not message_id or not secure_hash:
            return web.json_response(
                {"error": "id and hash query parameters are required"}, status=400,
            )
        return await media_streamer(request, int(chat_id), int(message_id), secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message) from e
    except FIleNotFound as e:
        await db.delete_file(chat_id=chat_id, msg_id=message_id, hash=secure_hash)
        raise web.HTTPNotFound(text=e.message) from e
    except ValueError:
        return web.json_response({"error": "id must be numeric"}, status=400)
    except Exception as e:
        raise log_and_fail(e) from e


class_cache = {}


async def media_streamer(request: web.Request, chat_id: int, id: int, secure_hash: str):
    range_header = request.headers.get("Range", 0)

    index = await workload_tracker.least_loaded()
    faster_client = multi_clients[index]

    if Telegram.MULTI_CLIENT:
        logging.info(f"Client {index} is now serving {request.remote}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logging.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logging.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    logging.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(chat_id=chat_id, message_id=id)
    logging.debug("after calling get_file_properties")

    if file_id.unique_id[:6] != secure_hash:
        logging.debug(f"Invalid hash for message with ID {id}")
        raise InvalidHash

    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - \
        math.floor(offset / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )

    mime_type = file_id.mime_type
    file_name = file_id.file_name
    disposition = "attachment"

    if mime_type:
        if not file_name:
            try:
                file_name = f"{secrets.token_hex(2)}.{mime_type.split('/')[1]}"
            except (IndexError, AttributeError):
                file_name = f"{secrets.token_hex(2)}.unknown"
    else:
        if file_name:
            mime_type = mimetypes.guess_type(file_id.file_name)
        else:
            mime_type = "application/octet-stream"
            file_name = f"{secrets.token_hex(2)}.unknown"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": f"{mime_type}",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        },
    )
