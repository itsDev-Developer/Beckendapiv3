"""On-demand HLS (.m3u8) generation for Telegram-hosted files.

Drop this in as bot/helper/hls.py

How it works
------------
A progressive MP4/MKV can't be sliced into HLS segments by byte-range alone
(see the accompanying explanation) -- it has to be *remuxed*. This module
streams the source file's bytes straight from Telegram into ffmpeg's stdin
and lets ffmpeg's own `hls` muxer produce keyframe-aligned .ts segments and
a VOD playlist. Since we use `-c copy`, this is a container rewrite, not a
re-encode, so it's cheap on CPU -- it just costs one full read of the file.

Requires ffmpeg to be installed in the runtime image.
"""

import asyncio
import logging
import os
import shutil

from bot.server.custom_dl import ByteStreamer

LOGGER = logging.getLogger(__name__)

HLS_CACHE_DIR = "cache/hls"
SEGMENT_DURATION = 6  # seconds; shorter = faster start, more files
CHUNK_SIZE = 1024 * 1024

# One lock per (chat_id, message_id, hash) so two concurrent requests for
# the same file don't kick off duplicate ffmpeg processes.
_locks: dict[str, asyncio.Lock] = {}


def _cache_key(chat_id: int, message_id: int, file_hash: str) -> str:
    return f"{chat_id}-{message_id}-{file_hash}"


def _cache_dir(chat_id: int, message_id: int, file_hash: str) -> str:
    return os.path.join(HLS_CACHE_DIR, _cache_key(chat_id, message_id, file_hash))


def playlist_path(chat_id: int, message_id: int, file_hash: str) -> str:
    return os.path.join(_cache_dir(chat_id, message_id, file_hash), "index.m3u8")


def segment_path(chat_id: int, message_id: int, file_hash: str, segment_name: str) -> str:
    """Resolve a segment file, guarding against path traversal."""
    if "/" in segment_name or ".." in segment_name or not segment_name.endswith(".ts"):
        raise ValueError("invalid segment name")
    return os.path.join(_cache_dir(chat_id, message_id, file_hash), segment_name)


async def ensure_hls(
    tg_connect: ByteStreamer,
    file_id,
    client_index: int,
    chat_id: int,
    message_id: int,
    file_hash: str,
) -> str:
    """Return the path to a ready .m3u8 playlist, generating it if needed."""
    key = _cache_key(chat_id, message_id, file_hash)
    lock = _locks.setdefault(key, asyncio.Lock())

    async with lock:
        out_dir = _cache_dir(chat_id, message_id, file_hash)
        out_m3u8 = os.path.join(out_dir, "index.m3u8")
        if os.path.exists(out_m3u8):
            return out_m3u8

        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg is not installed in this environment")

        os.makedirs(out_dir, exist_ok=True)
        LOGGER.info("Generating HLS for %s", key)

        file_size = file_id.file_size
        part_count = -(-file_size // CHUNK_SIZE)  # ceil division

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i", "pipe:0",
            "-c", "copy",
            "-map", "0",
            "-f", "hls",
            "-hls_time", str(SEGMENT_DURATION),
            "-hls_playlist_type", "vod",
            "-hls_segment_filename", os.path.join(out_dir, "seg%05d.ts"),
            out_m3u8,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            async for chunk in tg_connect.yield_file(
                file_id, client_index, 0, 0, CHUNK_SIZE, part_count, CHUNK_SIZE
            ):
                proc.stdin.write(chunk)
                await proc.stdin.drain()
        finally:
            proc.stdin.close()

        _, stderr = await proc.communicate()

        if proc.returncode != 0 or not os.path.exists(out_m3u8):
            shutil.rmtree(out_dir, ignore_errors=True)
            LOGGER.error("ffmpeg failed for %s: %s", key, stderr.decode(errors="ignore")[-2000:])
            raise RuntimeError("HLS generation failed")

        return out_m3u8


def cleanup_hls(max_age_seconds: int = 24 * 60 * 60) -> None:
    """Evict cached HLS folders older than max_age_seconds. Run this periodically."""
    import time

    if not os.path.isdir(HLS_CACHE_DIR):
        return
    now = time.time()
    for name in os.listdir(HLS_CACHE_DIR):
        path = os.path.join(HLS_CACHE_DIR, name)
        try:
            if now - os.path.getmtime(path) > max_age_seconds:
                shutil.rmtree(path, ignore_errors=True)
                LOGGER.info("Evicted HLS cache folder %s", name)
        except OSError as e:
            LOGGER.error("HLS cleanup error for %s: %s", name, e)
