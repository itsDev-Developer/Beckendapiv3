from asyncio import gather, create_task
from bot.helper.database import Database
from bot.helper.peers import safe_get_chat
from bot.telegram import StreamBot
from bot.config import Telegram


db = Database()


def _public_chat_id(chat_id):
    return str(chat_id).replace("-100", "")


def _stream_url(chat_id, file_id, file_hash):
    return f"/{_public_chat_id(chat_id)}/stream?id={file_id}&hash={file_hash}"


def _watch_url(chat_id, file_id, file_hash):
    return f"/watch/{_public_chat_id(chat_id)}?id={file_id}&hash={file_hash}"


async def get_chats():
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]

    return [{"chat-id": chat.id, "title": chat.title or chat.first_name, "type": chat.type.name} for chat in await gather(*[create_task(safe_get_chat(StreamBot, int(channel_id))) for channel_id in AUTH_CHANNEL])]


async def posts_chat(channels):
    return [
        {
            "id": _public_chat_id(channel["chat-id"]),
            "kind": "channel",
            "title": channel["title"],
            "chat_type": channel["type"],
            "thumbnail": f"/api/thumb/{channel['chat-id']}",
            "url": f"/channel/{_public_chat_id(channel['chat-id'])}",
        }
        for channel in channels
    ]


async def post_playlist(playlists):
    return [
        {
            # NOTE: playlist["_id"] is a bson.ObjectId, which json.dumps can't
            # serialize -- this used to crash every /playlist and / request
            # whenever a playlist folder existed. str() it explicitly.
            "id": str(playlist["_id"]),
            "kind": "folder",
            "title": playlist["name"],
            "thumbnail": playlist.get("thumbnail"),
            "parent_folder": playlist.get("parent_folder"),
            "url": f"/playlist?db={playlist['_id']}",
        }
        for playlist in playlists
    ]


async def posts_db_file(posts):
    return [
        {
            "id": str(post["_id"]),
            "kind": "file",
            "chat_id": _public_chat_id(post["chat_id"]),
            # NOTE: these documents (written by POST /send) only ever have a
            # "name" field, never "title" -- the old code did post["title"]
            # unconditionally and raised KeyError on every request here.
            "title": post.get("name") or post.get("title"),
            "size": post.get("size"),
            "mime_type": post.get("file_type"),
            "hash": post.get("hash"),
            "tmdb_id": post.get("tmdb_id"),
            "tmdb_type": post.get("tmdb_type"),
            "season": post.get("season"),
            "episode": post.get("episode"),
            "poster_url": post.get("thumbnail"),
            "parent_folder": post.get("parent_folder"),
            "stream_url": _stream_url(post["chat_id"], post["file_id"], post.get("hash")),
            "watch_url": _watch_url(post["chat_id"], post["file_id"], post.get("hash")),
        }
        for post in posts
    ]
