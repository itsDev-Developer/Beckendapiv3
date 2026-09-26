"""Peer resolution helpers -- fixes 'Peer id invalid' errors.

Drop this in as bot/helper/peers.py

Pyrogram can only resolve a numeric chat_id from its own local peer cache
(access hash storage). That cache is populated by receiving a live update
mentioning the peer, or by calling get_dialogs(), or by resolving a public
@username. Every Telegram client here -- StreamBot, each MULTI_TOKEN worker,
and the optional UserBot -- has an INDEPENDENT cache, so a channel StreamBot
already knows about is still unresolved for a freshly started worker bot or
a freshly authenticated user session, until it either gets lucky with an
update or is explicitly warmed up.
"""

import asyncio
import logging

from pyrogram.errors import ChannelPrivate, PeerIdInvalid

LOGGER = logging.getLogger(__name__)


async def warm_up_peers(client, channel_ids, label="client"):
    """Force this client to cache access hashes for every chat it's in.

    Call this once, right after client.start(), for StreamBot, UserBot,
    and every multi-client -- before it's put to any real use.
    """
    seen = set()
    try:
        async for dialog in client.get_dialogs():
            seen.add(dialog.chat.id)
    except Exception as e:
        LOGGER.error("%s: get_dialogs failed while warming up peers: %s", label, e)
        return

    for channel_id in channel_ids:
        if int(channel_id) not in seen:
            LOGGER.warning(
                "%s: channel %s did not appear in get_dialogs() -- this "
                "bot/account is probably not actually a member of it. "
                "Streaming/browsing for that channel will fail with "
                "PeerIdInvalid until it's added.",
                label, channel_id,
            )


async def warm_up_all(clients_with_labels, channel_ids):
    """Warm up several clients concurrently at startup."""
    await asyncio.gather(*[
        warm_up_peers(client, channel_ids, label=label)
        for client, label in clients_with_labels
    ])


async def _rescan_dialogs(client):
    async for _ in client.get_dialogs():
        pass


async def safe_get_messages(client, chat_id, message_id, _retried=False):
    """get_messages with one automatic re-resolve-and-retry on PeerIdInvalid.

    Use this in place of client.get_messages(...) anywhere a chat_id might
    not have been resolved yet -- e.g. right after an admin changes
    AUTH_CHANNEL via /config without restarting the service.
    """
    try:
        return await client.get_messages(chat_id, message_id)
    except PeerIdInvalid:
        if _retried:
            raise
        LOGGER.info("Peer %s unresolved, re-scanning dialogs and retrying", chat_id)
        await _rescan_dialogs(client)
        return await safe_get_messages(client, chat_id, message_id, _retried=True)


async def safe_get_chat(client, chat_id, _retried=False):
    try:
        return await client.get_chat(chat_id)
    except PeerIdInvalid:
        if _retried:
            raise
        LOGGER.info("Peer %s unresolved, re-scanning dialogs and retrying", chat_id)
        await _rescan_dialogs(client)
        return await safe_get_chat(client, chat_id, _retried=True)
    except ChannelPrivate as e:
        LOGGER.error("Client has no access to %s: %s", chat_id, e)
        raise


async def safe_iter(client, agen_factory, _retried=False):
    """Wrap an async-generator Telegram call (search_messages, get_chat_history)
    with the same re-resolve-and-retry behaviour.

    agen_factory is a zero-arg callable that returns a *fresh* async
    generator each time it's called, e.g.:

        safe_iter(UserBot, lambda: UserBot.get_chat_history(chat_id=..., limit=50))
    """
    try:
        async for item in agen_factory():
            yield item
    except PeerIdInvalid:
        if _retried:
            raise
        LOGGER.info("Peer unresolved mid-iteration, re-scanning dialogs and retrying")
        await _rescan_dialogs(client)
        async for item in safe_iter(client, agen_factory, _retried=True):
            yield item
