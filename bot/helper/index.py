from os.path import splitext
import re
from bot.config import Telegram
from bot.helper.database import Database
from bot.telegram import StreamBot, UserBot
from bot.helper.file_size import get_readable_file_size
from bot.helper.cache import get_cache, save_cache
from bot.helper.peers import safe_get_messages, safe_iter
from bot.helper.tmdb import fetch_metadata
from asyncio import gather

db = Database()


async def fetch_message(chat_id, message_id):
    try:
        message = await safe_get_messages(StreamBot, chat_id, message_id)
        return message
    except Exception as e:
        return None


async def get_messages(chat_id, first_message_id, last_message_id, batch_size=50):
    messages = []
    current_message_id = first_message_id
    while current_message_id <= last_message_id:
        batch_message_ids = list(range(current_message_id, min(current_message_id + batch_size, last_message_id + 1)))
        tasks = [fetch_message(chat_id, message_id) for message_id in batch_message_ids]
        batch_messages = await gather(*tasks)
        for message in batch_messages:
            if message:
                if file := message.video or message.document:
                    title = message.caption or file.file_name or file.file_id
                    title, _ = splitext(title)
                    title = re.sub(r'[.,|_\',]', ' ', title)
                    metadata = fetch_metadata(title)
                    messages.append({"msg_id": message.id, "title": title,
                                     "hash": file.file_unique_id[:6], "size": get_readable_file_size(file.file_size),
                                     "type": file.mime_type, "chat_id": str(chat_id), **metadata})
        current_message_id += batch_size
    return messages


async def get_files(chat_id, page=1):
    if Telegram.SESSION_STRING == '':
        return await db.list_tgfiles(id=chat_id, page=page)
    if cache := get_cache(chat_id, int(page)):
        return cache
    posts = []
    history_call = lambda: UserBot.get_chat_history(chat_id=int(chat_id), limit=50, offset=(int(page) - 1) * 50)
    async for post in safe_iter(UserBot, history_call):
        file = post.video or post.document
        if not file:
            continue
        title = post.caption or file.file_name or file.file_id
        title, _ = splitext(title)
        title = re.sub(r'[.,|_\',]', ' ', title)
        metadata = fetch_metadata(title)
        posts.append({"msg_id": post.id, "title": title,
                    "hash": file.file_unique_id[:6], "size": get_readable_file_size(file.file_size), "type": file.mime_type, **metadata})
    save_cache(chat_id, {"posts": posts}, page)
    return posts


def _public_chat_id(chat_id):
    return str(chat_id).replace("-100", "")


def _stream_url(chat_id, file_id, file_hash):
    return f"/{_public_chat_id(chat_id)}/stream?id={file_id}&hash={file_hash}"


def _watch_url(chat_id, file_id, file_hash):
    return f"/watch/{_public_chat_id(chat_id)}?id={file_id}&hash={file_hash}"


async def posts_file(posts, chat_id):
    public_id = _public_chat_id(chat_id)
    return [
        {
            "id": post["msg_id"],
            "kind": "file",
            "chat_id": public_id,
            "title": post["title"],
            "size": post.get("size"),
            "mime_type": post.get("type"),
            "hash": post.get("hash"),
            "tmdb_id": post.get("tmdb_id"),
            "tmdb_type": post.get("tmdb_type"),
            "season": post.get("season"),
            "episode": post.get("episode"),
            "poster_url": post.get("poster_url"),
            "stream_url": _stream_url(chat_id, post["msg_id"], post.get("hash")),
            "watch_url": _watch_url(chat_id, post["msg_id"], post.get("hash")),
        }
        for post in posts
    ]
