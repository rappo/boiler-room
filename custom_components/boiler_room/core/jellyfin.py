"""Jellyfin HTTP helpers shared by the services, the options flow and the cache.

Every request goes through aiohttp's `params=` so user text (voice queries,
item names) is URL-encoded. "Tom & Jerry" used to split the query string.
The param builders are pure functions so they can be unit-tested without HA.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

SEARCH_TYPES_DEFAULT = "Movie,Series,Audio,MusicAlbum,Episode"
BROWSE_TYPES_DEFAULT = "Movie,Series,Audio,MusicAlbum,MusicArtist,Person,Episode"

TYPE_LABELS = {
    "Movie": "movie", "Series": "show", "MusicAlbum": "album",
    "Audio": "song", "Episode": "episode", "MusicArtist": "artist",
    "Person": "person",
}

# Session commands accepted by /Sessions/{id}/Playing/{command}
PLAYSTATE_COMMANDS = {
    "pause": "Pause",
    "unpause": "Unpause",
    "stop": "Stop",
    "rewind": "Rewind",
    "fastforward": "FastForward",
}

_TIMEOUT_SHORT = aiohttp.ClientTimeout(total=5)
_TIMEOUT_SEARCH = aiohttp.ClientTimeout(total=10)


def auth_headers(api_key: str) -> dict[str, str]:
    """Authorization header for a Jellyfin API key."""
    return {"Authorization": f'MediaBrowser Token="{api_key}"'}


def search_params(
    query: str, media_type: str | None = None, limit: int = 5
) -> dict[str, str]:
    """Query parameters for GET /Items as a library search."""
    return {
        "searchTerm": query,
        "Limit": str(limit),
        "Recursive": "true",
        "IncludeItemTypes": media_type or SEARCH_TYPES_DEFAULT,
    }


def view_params(item: dict[str, Any]) -> dict[str, str]:
    """Query parameters for POST /Sessions/{id}/Viewing (navigate without playing)."""
    return {
        "itemType": item.get("Type", ""),
        "itemId": item.get("Id", ""),
        "itemName": item.get("Name", ""),
    }


def play_params(item_id: str) -> dict[str, str]:
    """Query parameters for POST /Sessions/{id}/Playing."""
    return {"ItemIds": item_id, "PlayCommand": "PlayNow"}


def pick_session(sessions: list[dict[str, Any]]) -> str | None:
    """Choose a controllable session: a Jellyfin desktop/mpv client first, else any."""
    fallback = None
    for s in sessions:
        caps = s.get("Capabilities") or {}
        if not caps.get("SupportsMediaControl"):
            continue
        client = (s.get("Client") or "").lower()
        if any(kw in client for kw in ("jellyfin", "media player", "mpv")):
            return s.get("Id")
        if fallback is None:
            fallback = s.get("Id")
    return fallback


async def check_connection(
    session: aiohttp.ClientSession, url: str, api_key: str
) -> int:
    """GET /System/Info and return the HTTP status (200 = URL and key are good)."""
    async with session.get(
        f"{url}/System/Info", headers=auth_headers(api_key), timeout=_TIMEOUT_SHORT
    ) as resp:
        return resp.status


async def search(
    session: aiohttp.ClientSession,
    url: str,
    api_key: str,
    query: str,
    media_type: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search the library; returns Jellyfin item dicts (empty on any non-200)."""
    async with session.get(
        f"{url}/Items",
        params=search_params(query, media_type, limit),
        headers=auth_headers(api_key),
        timeout=_TIMEOUT_SEARCH,
    ) as resp:
        if resp.status != 200:
            _LOGGER.debug("Jellyfin search returned HTTP %s", resp.status)
            return []
        data = await resp.json()
        return data.get("Items", [])


async def find_session(
    session: aiohttp.ClientSession, url: str, api_key: str
) -> str | None:
    """Return the id of a controllable Jellyfin session, or None."""
    async with session.get(
        f"{url}/Sessions", headers=auth_headers(api_key), timeout=_TIMEOUT_SHORT
    ) as resp:
        if resp.status != 200:
            return None
        return pick_session(await resp.json())


async def _post(
    session: aiohttp.ClientSession, url: str, api_key: str, params: dict[str, str]
) -> bool:
    async with session.post(
        url, params=params, headers=auth_headers(api_key), timeout=_TIMEOUT_SHORT
    ) as resp:
        return resp.status < 400


async def play(
    session: aiohttp.ClientSession, url: str, api_key: str, session_id: str, item_id: str
) -> bool:
    """Start playback of an item on a session."""
    return await _post(
        session, f"{url}/Sessions/{session_id}/Playing", api_key, play_params(item_id)
    )


async def view(
    session: aiohttp.ClientSession, url: str, api_key: str, session_id: str, item: dict[str, Any]
) -> bool:
    """Navigate a session to an item's page without playing it."""
    return await _post(
        session, f"{url}/Sessions/{session_id}/Viewing", api_key, view_params(item)
    )


async def playstate(
    session: aiohttp.ClientSession, url: str, api_key: str, session_id: str, command: str
) -> bool:
    """Send a PlayState command (pause, unpause, stop, rewind, fastforward)."""
    return await _post(
        session,
        f"{url}/Sessions/{session_id}/Playing/{PLAYSTATE_COMMANDS[command]}",
        api_key,
        {},
    )
