"""TMDb lookup helpers for the JSON file API."""

import os
import re
from difflib import SequenceMatcher
from typing import Any

import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"
FALLBACK_POSTER = "https://cdn-icons-png.flaticon.com/512/565/565547.png"
HTTP_TIMEOUT = 6
EPISODE_CAPTION_PATTERN = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$")


def _request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return an empty response when TMDb is not configured or unavailable."""
    if not TMDB_API_KEY:
        return {}
    try:
        response = requests.get(
            f"{TMDB_BASE_URL}{endpoint}",
            params={"api_key": TMDB_API_KEY, **params},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return {}


def _clean_title(raw_title: str) -> tuple[str, int | None, str | None]:
    title = raw_title.replace(".", " ").replace("_", " ").replace("-", " ")
    forced_type = None
    marker = re.search(r"\((tv|series|movie|film)\)", title, re.IGNORECASE)
    if marker:
        forced_type = "tv" if marker.group(1).lower() in {"tv", "series"} else "movie"
        title = title.replace(marker.group(0), " ")

    year_match = re.search(r"\b(?:19|20)\d{2}\b", title)
    year = int(year_match.group()) if year_match else None
    title = re.sub(r"\b(?:19|20)\d{2}\b", " ", title)
    title = re.sub(r"\b(?:s\d{1,3}|season\s*\d{1,3}|e\d{1,3}|ep(?:isode)?\s*\d{1,3}|part\s*\d{1,3})\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:480p|720p|1080p|2160p|4k|web[- ]?dl|webrip|bluray|x264|x265|hevc|aac|remux)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\[[^]]*]|\([^)]*\)", " ", title)
    return re.sub(r"\s+", " ", title).strip(), year, forced_type


def _score(result: dict[str, Any], title: str, year: int | None) -> float:
    candidate = result.get("title") or result.get("name") or ""
    similarity = SequenceMatcher(None, title.lower(), candidate.lower()).ratio()
    date = result.get("release_date") or result.get("first_air_date") or ""
    return similarity + (0.25 if year and date.startswith(str(year)) else 0)


def fetch_metadata(raw_title: str) -> dict[str, Any]:
    """Return the TMDb ID, media type, and poster for a Telegram file title.

    ``tmdb_id`` is ``None`` when no key is configured or no match is found, so
    clients can always rely on the field being present in JSON responses.
    """
    metadata = {
        "tmdb_id": None,
        "tmdb_type": None,
        "season": None,
        "episode": None,
        "poster_url": FALLBACK_POSTER,
    }
    episode_caption = EPISODE_CAPTION_PATTERN.fullmatch(raw_title)
    if episode_caption:
        tmdb_id, season, episode = (int(value) for value in episode_caption.groups())
        metadata.update({
            "tmdb_id": tmdb_id,
            "tmdb_type": "tv",
            "season": season,
            "episode": episode,
        })
        details = _request(f"/tv/{tmdb_id}", {})
        if poster_path := details.get("poster_path"):
            metadata["poster_url"] = f"{POSTER_BASE_URL}{poster_path}"
        return metadata

    title, year, forced_type = _clean_title(raw_title)
    if not title or not TMDB_API_KEY:
        return metadata

    search_types = [forced_type] if forced_type else ["movie", "tv"]
    best: tuple[float, str, dict[str, Any]] | None = None
    for media_type in search_types:
        if not media_type:
            continue
        params: dict[str, Any] = {"query": title, "page": 1}
        if media_type == "movie" and year:
            params["year"] = year
        results = _request(f"/search/{media_type}", params).get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            score = _score(result, title, year)
            if best is None or score > best[0]:
                best = (score, media_type, result)

    if best is None:
        return metadata
    _, media_type, result = best
    poster_path = result.get("poster_path")
    metadata.update({
        "tmdb_id": result.get("id"),
        "tmdb_type": media_type,
        "poster_url": f"{POSTER_BASE_URL}{poster_path}" if poster_path else FALLBACK_POSTER,
    })
    return metadata


def fetch_poster(raw_title: str) -> str:
    """Backward-compatible poster-only helper."""
    return fetch_metadata(raw_title)["poster_url"]
