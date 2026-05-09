"""Intent handlers for Boiler Room voice commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# Default game aliases — common abbreviations that voice assistants might hear
DEFAULT_ALIASES: dict[str, str] = {
    "bg3": "Baldur's Gate 3",
    "baldurs gate": "Baldur's Gate 3",
    "cyberpunk": "Cyberpunk 2077",
    "rdr2": "Red Dead Redemption 2",
    "red dead": "Red Dead Redemption 2",
    "gta": "Grand Theft Auto V",
    "gta5": "Grand Theft Auto V",
    "elden ring": "ELDEN RING",
    "skyrim": "The Elder Scrolls V: Skyrim",
    "witcher": "The Witcher 3: Wild Hunt",
    "botw": "The Legend of Zelda: Breath of the Wild",
    "totk": "The Legend of Zelda: Tears of the Kingdom",
    "ff7": "FINAL FANTASY VII REMAKE",
    "ds3": "DARK SOULS III",
    "hollow knight": "Hollow Knight",
    "stardew": "Stardew Valley",
    "terraria": "Terraria",
    "valheim": "Valheim",
    "satisfactory": "Satisfactory",
    "factorio": "Factorio",
    "rimworld": "RimWorld",
    "civ": "Sid Meier's Civilization VI",
    "civ6": "Sid Meier's Civilization VI",
    "portal": "Portal 2",
    "half life": "Half-Life 2",
    "dota": "Dota 2",
    "cs": "Counter-Strike 2",
    "csgo": "Counter-Strike 2",
    "apex": "Apex Legends",
}


def fuzzy_match_game(
    query: str,
    games: list[dict[str, Any]],
    aliases: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Find the best matching game for a voice query.

    Match priority:
    1. Exact alias match
    2. Exact name match (case-insensitive)
    3. Substring match (prefer shorter names = more specific)
    4. Word-boundary matching
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    # Merge default aliases with user-configured aliases
    all_aliases = {**DEFAULT_ALIASES}
    if aliases:
        all_aliases.update(aliases)

    # 1. Check aliases first
    if query_lower in all_aliases:
        alias_target = all_aliases[query_lower].lower()
        for game in games:
            if game.get("name", "").lower() == alias_target:
                return game

    # 2. Exact name match
    for game in games:
        if game.get("name", "").lower() == query_lower:
            return game

    # 3. Substring match
    substring_matches = []
    for game in games:
        name = game.get("name", "").lower()
        if query_lower in name:
            substring_matches.append(game)

    if len(substring_matches) == 1:
        return substring_matches[0]
    if len(substring_matches) > 1:
        # Return shortest name (most specific)
        return min(substring_matches, key=lambda g: len(g.get("name", "")))

    # 4. Word-boundary matching — check if all query words appear in the name
    query_words = query_lower.split()
    for game in games:
        name_lower = game.get("name", "").lower()
        if all(word in name_lower for word in query_words):
            return game

    return None


def _fuzzy_match_app(
    query: str,
    apps: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Fuzzy match an app name against installed Flatpak apps."""
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    # Exact match
    for app in apps:
        if app.get("name", "").lower() == query_lower:
            return app

    # Substring match
    matches = [a for a in apps if query_lower in a.get("name", "").lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return min(matches, key=lambda a: len(a.get("name", "")))

    return None


def _get_device_context(
    hass: HomeAssistant,
) -> tuple[Any, list[dict], list[dict], dict[str, str] | None]:
    """Get the API client, game list, app list, and aliases from the first available device."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        api = entry_data.get("api")
        coordinator = entry_data.get("coordinator")
        if api and coordinator and coordinator.data:
            games = coordinator.data.get("games", [])
            apps = coordinator.data.get("apps", [])
            aliases = entry_data.get("aliases")
            return api, games, apps, aliases
    return None, [], [], None


def _get_jellyfin_config(
    hass: HomeAssistant,
) -> dict[str, str] | None:
    """Get Jellyfin config from the first config entry's options."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        jf_url = entry.options.get("jellyfin_url", "").strip()
        jf_key = entry.options.get("jellyfin_api_key", "").strip()
        if jf_url and jf_key:
            return {
                "url": jf_url.rstrip("/"),
                "api_key": jf_key,
                "app_id": entry.options.get("jellyfin_app_id", "org.jellyfin.JellyfinDesktop").strip(),
                "youtube_app_id": entry.options.get("youtube_app_id", "").strip(),
            }
    return None


def _get_jellyfin_cache(hass: HomeAssistant):
    """Get the Jellyfin media cache from the first entry that has one."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        cache = entry_data.get("jellyfin_cache")
        if cache:
            return cache
    return None


# ─── Intent Registration ───


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register intent handlers for Boiler Room voice commands."""
    intent.async_register(hass, BoilerRoomLaunchGameIntent())
    intent.async_register(hass, BoilerRoomOpenAppIntent())
    intent.async_register(hass, BoilerRoomSystemControlIntent())
    intent.async_register(hass, BoilerRoomJellyfinSearchIntent())
    intent.async_register(hass, BoilerRoomJellyfinBrowseIntent())
    _LOGGER.info("Boiler Room voice command intents registered")


# ─── Game / App Intents ───


class BoilerRoomLaunchGameIntent(intent.IntentHandler):
    """Handle the BoilerRoomLaunchGame intent."""

    intent_type = "BoilerRoomLaunchGame"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        game_name = intent_obj.slots.get("game_name", {}).get("value", "")

        if not game_name:
            response = intent_obj.create_response()
            response.async_set_speech("I didn't catch the game name. What would you like to play?")
            return response

        api, games, apps, aliases = _get_device_context(hass)
        if not api:
            response = intent_obj.create_response()
            response.async_set_speech("No SteamOS device is connected.")
            return response

        game = fuzzy_match_game(game_name, games, aliases)
        if game:
            result = await api.launch(appid=game["appid"])
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Launching {game['name']}.")
            else:
                response.async_set_speech(f"Failed to launch {game['name']}.")
            return response

        app = _fuzzy_match_app(game_name, apps)
        if app:
            result = await api.launch(appid=app["id"], launch_type="app")
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Opening {app['name']}.")
            else:
                response.async_set_speech(f"Failed to open {app['name']}.")
            return response

        response = intent_obj.create_response()
        response.async_set_speech(f"I couldn't find a game or app matching '{game_name}'.")
        return response


class BoilerRoomOpenAppIntent(intent.IntentHandler):
    """Handle the BoilerRoomOpenApp intent."""

    intent_type = "BoilerRoomOpenApp"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        app_name = intent_obj.slots.get("app_name", {}).get("value", "")

        if not app_name:
            response = intent_obj.create_response()
            response.async_set_speech("Which app should I open?")
            return response

        api, games, apps, aliases = _get_device_context(hass)
        if not api:
            response = intent_obj.create_response()
            response.async_set_speech("No SteamOS device is connected.")
            return response

        app = _fuzzy_match_app(app_name, apps)
        if app:
            result = await api.launch(appid=app["id"], launch_type="app")
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Opening {app['name']}.")
            else:
                response.async_set_speech(f"Failed to open {app['name']}.")
            return response

        game = fuzzy_match_game(app_name, games)
        if game:
            result = await api.launch(appid=game["appid"])
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Launching {game['name']}.")
            else:
                response.async_set_speech(f"Failed to launch {game['name']}.")
            return response

        response = intent_obj.create_response()
        response.async_set_speech(f"Couldn't find an app or game named {app_name}.")
        return response


# ─── System Control ───


class BoilerRoomSystemControlIntent(intent.IntentHandler):
    """Handle the BoilerRoomSystemControl intent."""

    intent_type = "BoilerRoomSystemControl"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        action = intent_obj.slots.get("action", {}).get("value", "").lower()
        volume = intent_obj.slots.get("volume", {}).get("value")

        api, _, _, _ = _get_device_context(hass)
        if not api:
            response = intent_obj.create_response()
            response.async_set_speech("No SteamOS device is connected.")
            return response

        response = intent_obj.create_response()

        if volume is not None:
            try:
                vol = int(volume)
                await api.set_volume(vol)
                response.async_set_speech(f"Volume set to {vol} percent.")
            except (ValueError, TypeError):
                response.async_set_speech("I didn't understand the volume level.")
        elif action in ("suspend", "sleep"):
            await api.power_action("suspend")
            response.async_set_speech("Suspending the SteamOS device.")
        elif action in ("shutdown",):
            await api.power_action("shutdown")
            response.async_set_speech("Shutting down the SteamOS device.")
        elif action in ("reboot",):
            await api.power_action("reboot")
            response.async_set_speech("Rebooting the SteamOS device.")
        else:
            response.async_set_speech(f"I don't know the command '{action}'.")

        return response


# ─── Jellyfin Helpers ───

_MEDIA_TYPE_DEFAULT = "Movie,Series,Audio,MusicAlbum,Episode"
_BROWSE_TYPE_DEFAULT = "Movie,Series,Audio,MusicAlbum,MusicArtist,Person,Episode"
_TYPE_LABELS = {
    "Movie": "movie", "Series": "show", "MusicAlbum": "album",
    "Audio": "song", "Episode": "episode", "MusicArtist": "artist",
    "Person": "person",
}


async def _jellyfin_search(
    jf_url: str, jf_key: str, query: str,
    media_type: str | None = None, limit: int = 5,
) -> list[dict[str, Any]]:
    """Search the Jellyfin library."""
    headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}
    include_types = media_type or _MEDIA_TYPE_DEFAULT
    search_url = (
        f"{jf_url}/Items?searchTerm={query}"
        f"&Limit={limit}&Recursive=true"
        f"&IncludeItemTypes={include_types}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(
            search_url, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("Items", [])


async def _jellyfin_find_session(jf_url: str, jf_key: str) -> str | None:
    """Find a controllable Jellyfin session."""
    headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{jf_url}/Sessions", headers=headers,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status != 200:
                return None
            sessions = await resp.json()

    session_id = None
    for s in sessions:
        client = (s.get("Client") or "").lower()
        caps = s.get("Capabilities", {})
        if caps.get("SupportsMediaControl"):
            if any(kw in client for kw in ["jellyfin", "media player", "mpv"]):
                return s.get("Id")
            if not session_id:
                session_id = s.get("Id")
    return session_id


# ─── Jellyfin Play Intent ───


class BoilerRoomJellyfinSearchIntent(intent.IntentHandler):
    """Search Jellyfin with optional type filtering, launch app, play content."""

    intent_type = "BoilerRoomJellyfinSearch"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        query = intent_obj.slots.get("query", {}).get("value", "")
        media_type = intent_obj.slots.get("media_type", {}).get("value")

        if not query:
            response = intent_obj.create_response()
            response.async_set_speech("What would you like to watch?")
            return response

        jf_config = _get_jellyfin_config(hass)
        if not jf_config:
            response = intent_obj.create_response()
            response.async_set_speech(
                "Jellyfin is not configured. Go to Settings, Integrations, "
                "Boiler Room, Configure to add your Jellyfin server."
            )
            return response

        jf_url = jf_config["url"]
        jf_key = jf_config["api_key"]
        jf_app = jf_config["app_id"]

        try:
            # Try phonetic match against the local cache first
            cache = _get_jellyfin_cache(hass)
            cache_hit_id = None
            search_query = query
            if cache:
                resolved_name, cache_hit_id = cache.match_or_query(query)
                if resolved_name != query:
                    _LOGGER.info(
                        "Cache resolved voice query '%s' → '%s'",
                        query, resolved_name,
                    )
                    search_query = resolved_name

            items = await _jellyfin_search(jf_url, jf_key, search_query, media_type)
            if not items:
                hint = f" {media_type.lower()}" if media_type else ""
                response = intent_obj.create_response()
                response.async_set_speech(
                    f"I couldn't find a{hint} matching '{query}' on Jellyfin."
                )
                return response

            item = items[0]
            item_name = item.get("Name", query)
            item_id = item.get("Id", "")
            item_type = item.get("Type", "")
            type_label = _TYPE_LABELS.get(item_type, item_type.lower())

            # Check if Jellyfin already has an active session
            session_id = await _jellyfin_find_session(jf_url, jf_key)

            # Only launch the app if no session exists
            if not session_id:
                api, _, _, _ = _get_device_context(hass)
                if api and jf_app:
                    try:
                        await api.launch(appid=jf_app, launch_type="app")
                    except Exception:
                        _LOGGER.warning("Could not launch Jellyfin app")
                    await asyncio.sleep(5)
                    # Re-check for session after launching
                    session_id = await _jellyfin_find_session(jf_url, jf_key)

            if session_id and item_id:
                headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}
                play_url = (
                    f"{jf_url}/Sessions/{session_id}/Playing"
                    f"?ItemIds={item_id}&PlayCommand=PlayNow"
                )
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        play_url, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status < 400:
                            response = intent_obj.create_response()
                            response.async_set_speech(
                                f"Playing the {type_label} {item_name} on Jellyfin."
                            )
                            return response

            response = intent_obj.create_response()
            response.async_set_speech(
                f"Found the {type_label} {item_name}, but no active Jellyfin session. "
                f"Open Jellyfin on the SteamOS device first."
            )
            return response

        except asyncio.TimeoutError:
            response = intent_obj.create_response()
            response.async_set_speech("Jellyfin server didn't respond in time.")
            return response
        except Exception as err:
            _LOGGER.exception("Jellyfin search failed")
            response = intent_obj.create_response()
            response.async_set_speech(f"Jellyfin error: {err}")
            return response


# ─── Jellyfin Browse Intent ───


class BoilerRoomJellyfinBrowseIntent(intent.IntentHandler):
    """Search Jellyfin and open item page in the web UI (no playback)."""

    intent_type = "BoilerRoomJellyfinBrowse"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        query = intent_obj.slots.get("query", {}).get("value", "")
        media_type = intent_obj.slots.get("media_type", {}).get("value")

        if not query:
            response = intent_obj.create_response()
            response.async_set_speech("What would you like to find on Jellyfin?")
            return response

        jf_config = _get_jellyfin_config(hass)
        if not jf_config:
            response = intent_obj.create_response()
            response.async_set_speech(
                "Jellyfin is not configured. Go to Settings, Integrations, "
                "Boiler Room, Configure to add your Jellyfin server."
            )
            return response

        jf_url = jf_config["url"]
        jf_key = jf_config["api_key"]
        jf_app = jf_config["app_id"]

        try:
            # Browse uses broader types (includes Person, MusicArtist)
            search_types = media_type or _BROWSE_TYPE_DEFAULT

            # Try phonetic match against the local cache first
            cache = _get_jellyfin_cache(hass)
            search_query = query
            if cache:
                resolved_name, _ = cache.match_or_query(query)
                if resolved_name != query:
                    _LOGGER.info(
                        "Cache resolved voice query '%s' → '%s'",
                        query, resolved_name,
                    )
                    search_query = resolved_name

            items = await _jellyfin_search(jf_url, jf_key, search_query, search_types)
            if not items:
                response = intent_obj.create_response()
                response.async_set_speech(
                    f"I couldn't find anything matching '{query}' on Jellyfin."
                )
                return response

            item = items[0]
            item_name = item.get("Name", query)
            item_id = item.get("Id", "")
            item_type = item.get("Type", "")
            type_label = _TYPE_LABELS.get(item_type, item_type.lower())

            # Only launch the app if no session exists
            session_id = await _jellyfin_find_session(jf_url, jf_key)

            if not session_id:
                api, _, _, _ = _get_device_context(hass)
                if api and jf_app:
                    try:
                        await api.launch(appid=jf_app, launch_type="app")
                    except Exception:
                        _LOGGER.warning("Could not launch Jellyfin app")
                    await asyncio.sleep(5)
                    session_id = await _jellyfin_find_session(jf_url, jf_key)

            if session_id and item_id:
                # Use Jellyfin's DisplayContent API to navigate within the app
                headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}
                view_url = (
                    f"{jf_url}/Sessions/{session_id}/Viewing"
                    f"?itemType={item_type}&itemId={item_id}&itemName={item_name}"
                )
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        view_url, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status < 400:
                            response = intent_obj.create_response()
                            response.async_set_speech(
                                f"Showing {item_name} on Jellyfin."
                            )
                            return response

            response = intent_obj.create_response()
            response.async_set_speech(
                f"Found {item_name}, but no active Jellyfin session. "
                f"Open Jellyfin on the SteamOS device first."
            )
            return response

        except asyncio.TimeoutError:
            response = intent_obj.create_response()
            response.async_set_speech("Jellyfin server didn't respond in time.")
            return response
        except Exception as err:
            _LOGGER.exception("Jellyfin browse failed")
            response = intent_obj.create_response()
            response.async_set_speech(f"Jellyfin error: {err}")
            return response
