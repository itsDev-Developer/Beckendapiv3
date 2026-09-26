import re
from bot.config import Telegram
from bot.helper.database import Database
from bot.helper.peers import safe_iter
from bot.telegram import UserBot
from os.path import splitext
from bot.helper.tmdb import fetch_metadata
from bot.helper.file_size import get_readable_file_size

db = Database()
async def search(chat_id, query, page):
    if Telegram.SESSION_STRING == '':
        return await db.search_tgfiles(id=chat_id, query=query, page=page)
    posts = []
    search_call = lambda: UserBot.search_messages(chat_id=int(chat_id), limit=50, query=str(query), offset=(int(page) - 1) * 50)
    async for post in safe_iter(UserBot, search_call):
        file = post.video or post.document
        if not file:
            continue
        title = post.caption or file.file_name or file.file_id
        title, _ = splitext(title)
        title = re.sub(r'[.,|_\',]', ' ', title)
        metadata = fetch_metadata(title)
        posts.append({"msg_id": post.id, "title": title,
                     "hash": file.file_unique_id[:6], "size": get_readable_file_size(file.file_size), "type": file.mime_type, **metadata})
    return posts
