"""HA service handlers for Boiler Room.

Exposes the integration's smart logic (fuzzy matching, Jellyfin search,
phonetic cache, power control) as standard HA services that can be called
from automations, scripts, and blueprints.

All services return a dict with at minimum a 'speech' key containing a
natural-language response suitable for set_conversation_response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote_plus

import aiohttp
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import DOMAIN
from .intents import (
    DEFAULT_ALIASES,
    _BROWSE_TYPE_DEFAULT,
    _MEDIA_TYPE_DEFAULT,
    _TYPE_LABELS,
    _fuzzy_match_app,
    _get_device_context,
    _get_jellyfin_cache,
    _get_jellyfin_config,
    _jellyfin_find_session,
    _jellyfin_search,
    fuzzy_match_game,
)

_LOGGER = logging.getLogger(__name__)


# ─── Service Schemas ───

LAUNCH_GAME_SCHEMA = vol.Schema({
    vol.Required("name"): str,
    vol.Optional("device"): str,
})

LAUNCH_APP_SCHEMA = vol.Schema({
    vol.Required("name"): str,
    vol.Optional("device"): str,
})

JELLYFIN_PLAY_SCHEMA = vol.Schema({
    vol.Required("query"): str,
    vol.Optional("type"): str,
})

JELLYFIN_BROWSE_SCHEMA = vol.Schema({
    vol.Required("query"): str,
    vol.Optional("type"): str,
})

JELLYFIN_CONTROL_SCHEMA = vol.Schema({
    vol.Required("action"): vol.In(
        ["pause", "unpause", "stop", "rewind", "fastforward"]
    ),
})

YOUTUBE_SEARCH_SCHEMA = vol.Schema({
    vol.Required("query"): str,
    vol.Optional("device"): str,
})

POWER_SCHEMA = vol.Schema({
    vol.Required("action"): vol.In(["suspend", "shutdown", "reboot"]),
    vol.Optional("device"): str,
})

WAKE_SCHEMA = vol.Schema({
    vol.Optional("device"): str,
})

VOLUME_SCHEMA = vol.Schema({
    vol.Required("level"): vol.All(int, vol.Range(min=0, max=100)),
    vol.Optional("device"): str,
})


# ─── Registration ───


def async_register_services(hass: HomeAssistant) -> None:
    """Register all Boiler Room services."""
    if hass.services.has_service(DOMAIN, "launch_game"):
        return  # Already registered

    hass.services.async_register(
        DOMAIN, "launch_game", _handle_launch_game,
        schema=LAUNCH_GAME_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "launch_app", _handle_launch_app,
        schema=LAUNCH_APP_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "jellyfin_play", _handle_jellyfin_play,
        schema=JELLYFIN_PLAY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "jellyfin_browse", _handle_jellyfin_browse,
        schema=JELLYFIN_BROWSE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "jellyfin_control", _handle_jellyfin_control,
        schema=JELLYFIN_CONTROL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "youtube_search", _handle_youtube_search,
        schema=YOUTUBE_SEARCH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "power", _handle_power,
        schema=POWER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "wake", _handle_wake,
        schema=WAKE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "set_volume", _handle_set_volume,
        schema=VOLUME_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    _LOGGER.info("Boiler Room services registered")


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services (called when last config entry is unloaded)."""
    for svc in [
        "launch_game", "launch_app", "jellyfin_play", "jellyfin_browse",
        "jellyfin_control", "youtube_search", "power", "wake", "set_volume",
    ]:
        hass.services.async_remove(DOMAIN, svc)


# ─── Service Handlers ───


async def _handle_launch_game(call: ServiceCall) -> dict[str, Any]:
    """Launch a game by name with fuzzy matching."""
    hass = call.hass
    name = call.data["name"]

    api, games, apps, aliases = _get_device_context(hass)
    if not api:
        return {"speech": "No SteamOS device is connected."}

    game = fuzzy_match_game(name, games, aliases)
    if game:
        result = await api.launch(appid=game["appid"])
        if result.get("status") == "launching":
            return {
                "speech": f"Launching {game['name']}.",
                "matched_name": game["name"],
                "appid": game["appid"],
            }
        return {"speech": f"Failed to launch {game['name']}."}

    # Fallback: try apps
    app = _fuzzy_match_app(name, apps)
    if app:
        result = await api.launch(appid=app["id"], launch_type="app")
        if result.get("status") == "launching":
            return {
                "speech": f"Opening {app['name']}.",
                "matched_name": app["name"],
                "app_id": app["id"],
            }
        return {"speech": f"Failed to open {app['name']}."}

    return {"speech": f"I couldn't find a game or app matching '{name}'."}


async def _handle_launch_app(call: ServiceCall) -> dict[str, Any]:
    """Launch an app by name with fuzzy matching and alias support."""
    hass = call.hass
    name = call.data["name"]

    api, games, apps, aliases = _get_device_context(hass)
    if not api:
        return {"speech": "No SteamOS device is connected."}

    # Check user-defined app aliases from options
    app_aliases = _get_app_aliases(hass)
    name_lower = name.lower().strip()
    if name_lower in app_aliases:
        flatpak_id = app_aliases[name_lower]
        result = await api.launch(appid=flatpak_id, launch_type="app")
        if result.get("status") == "launching":
            return {
                "speech": f"Opening {name}.",
                "matched_name": name,
                "app_id": flatpak_id,
            }
        return {"speech": f"Failed to open {name}."}

    # Fuzzy match against installed apps
    app = _fuzzy_match_app(name, apps)
    if app:
        result = await api.launch(appid=app["id"], launch_type="app")
        if result.get("status") == "launching":
            return {
                "speech": f"Opening {app['name']}.",
                "matched_name": app["name"],
                "app_id": app["id"],
            }
        return {"speech": f"Failed to open {app['name']}."}

    # Fallback: try games
    game = fuzzy_match_game(name, games)
    if game:
        result = await api.launch(appid=game["appid"])
        if result.get("status") == "launching":
            return {
                "speech": f"Launching {game['name']}.",
                "matched_name": game["name"],
                "appid": game["appid"],
            }
        return {"speech": f"Failed to launch {game['name']}."}

    hint = (
        f"Couldn't find an app or game named {name}. "
        "You can add an app alias in Settings → Integrations → Boiler Room → Configure."
    )
    return {"speech": hint}


async def _handle_jellyfin_play(call: ServiceCall) -> dict[str, Any]:
    """Search Jellyfin and play the top result."""
    hass = call.hass
    query = call.data["query"]
    media_type = call.data.get("type")

    jf_config = _get_jellyfin_config(hass)
    if not jf_config:
        return {"speech": "Jellyfin is not configured."}

    jf_url, jf_key, jf_app = jf_config["url"], jf_config["api_key"], jf_config["app_id"]

    # Try phonetic cache first
    cache = _get_jellyfin_cache(hass)
    search_query = query
    if cache:
        resolved_name, _ = cache.match_or_query(query)
        if resolved_name != query:
            _LOGGER.info("Cache resolved '%s' → '%s'", query, resolved_name)
            search_query = resolved_name

    items = await _jellyfin_search(jf_url, jf_key, search_query, media_type)
    if not items:
        hint = f" {media_type.lower()}" if media_type else ""
        return {"speech": f"I couldn't find a{hint} matching '{query}' on Jellyfin."}

    item = items[0]
    item_name = item.get("Name", query)
    item_id = item.get("Id", "")
    item_type = item.get("Type", "")
    type_label = _TYPE_LABELS.get(item_type, item_type.lower())

    # Find or launch session
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
        headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}
        play_url = f"{jf_url}/Sessions/{session_id}/Playing?ItemIds={item_id}&PlayCommand=PlayNow"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                play_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status < 400:
                    return {
                        "speech": f"Playing the {type_label} {item_name} on Jellyfin.",
                        "item_name": item_name,
                        "item_id": item_id,
                        "item_type": item_type,
                    }

    return {
        "speech": f"Found the {type_label} {item_name}, but no active Jellyfin session.",
        "item_name": item_name,
        "item_id": item_id,
        "item_type": item_type,
    }


async def _handle_jellyfin_browse(call: ServiceCall) -> dict[str, Any]:
    """Search Jellyfin and navigate to the item's page."""
    hass = call.hass
    query = call.data["query"]
    media_type = call.data.get("type")

    jf_config = _get_jellyfin_config(hass)
    if not jf_config:
        return {"speech": "Jellyfin is not configured."}

    jf_url, jf_key, jf_app = jf_config["url"], jf_config["api_key"], jf_config["app_id"]
    search_types = media_type or _BROWSE_TYPE_DEFAULT

    cache = _get_jellyfin_cache(hass)
    search_query = query
    if cache:
        resolved_name, _ = cache.match_or_query(query)
        if resolved_name != query:
            _LOGGER.info("Cache resolved '%s' → '%s'", query, resolved_name)
            search_query = resolved_name

    items = await _jellyfin_search(jf_url, jf_key, search_query, search_types)
    if not items:
        return {"speech": f"I couldn't find anything matching '{query}' on Jellyfin."}

    item = items[0]
    item_name = item.get("Name", query)
    item_id = item.get("Id", "")
    item_type = item.get("Type", "")

    session_id = await _jellyfin_find_session(jf_url, jf_key)
    if not session_id:
        api, _, _, _ = _get_device_context(hass)
        if api and jf_app:
            try:
                await api.launch(appid=jf_app, launch_type="app")
            except Exception:
                pass
            await asyncio.sleep(5)
            session_id = await _jellyfin_find_session(jf_url, jf_key)

    if session_id and item_id:
        headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}
        view_url = (
            f"{jf_url}/Sessions/{session_id}/Viewing"
            f"?itemType={item_type}&itemId={item_id}&itemName={item_name}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                view_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status < 400:
                    return {
                        "speech": f"Showing {item_name} on Jellyfin.",
                        "item_name": item_name,
                        "item_id": item_id,
                    }

    return {"speech": f"Found {item_name}, but no active Jellyfin session."}


async def _handle_jellyfin_control(call: ServiceCall) -> dict[str, Any]:
    """Control Jellyfin playback (pause, resume, stop, rewind, fast-forward)."""
    hass = call.hass
    action = call.data["action"]

    jf_config = _get_jellyfin_config(hass)
    if not jf_config:
        return {"speech": "Jellyfin is not configured."}

    jf_url, jf_key = jf_config["url"], jf_config["api_key"]
    session_id = await _jellyfin_find_session(jf_url, jf_key)
    if not session_id:
        return {"speech": "No active Jellyfin session found."}

    headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}

    # Map actions to Jellyfin session commands
    command_map = {
        "pause": ("PlayState", "Pause"),
        "unpause": ("PlayState", "Unpause"),
        "stop": ("PlayState", "Stop"),
        "rewind": ("PlayState", "Rewind"),
        "fastforward": ("PlayState", "FastForward"),
    }

    category, command = command_map[action]
    url = f"{jf_url}/Sessions/{session_id}/Playing/{command}"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status < 400:
                labels = {
                    "pause": "Paused", "unpause": "Resumed", "stop": "Stopped",
                    "rewind": "Rewinding", "fastforward": "Fast-forwarding",
                }
                return {"speech": f"{labels[action]} Jellyfin playback."}

    return {"speech": f"Failed to {action} Jellyfin playback."}


async def _handle_youtube_search(call: ServiceCall) -> dict[str, Any]:
    """Open a YouTube search in the configured client app."""
    hass = call.hass
    query = call.data["query"]

    api, _, _, _ = _get_device_context(hass)
    if not api:
        return {"speech": "No SteamOS device is connected."}

    jf_config = _get_jellyfin_config(hass)
    youtube_app = ""
    if jf_config:
        youtube_app = jf_config.get("youtube_app_id", "")

    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    if youtube_app:
        await api.launch(appid=youtube_app, launch_type="app")
        await asyncio.sleep(2)

    await api.launch(url=search_url, launch_type="url")
    return {"speech": f"Searching YouTube for {query}."}


async def _handle_power(call: ServiceCall) -> dict[str, Any]:
    """Execute a power action."""
    hass = call.hass
    action = call.data["action"]

    api, _, _, _ = _get_device_context(hass)
    if not api:
        return {"speech": "No SteamOS device is connected."}

    labels = {"suspend": "Suspending", "shutdown": "Shutting down", "reboot": "Rebooting"}
    await api.power_action(action)
    return {"speech": f"{labels[action]} the SteamOS device."}


async def _handle_wake(call: ServiceCall) -> dict[str, Any]:
    """Send Wake-on-LAN magic packet."""
    hass = call.hass

    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)

    wol_entity_id = None
    for entity in registry.entities.values():
        if entity.domain == "button" and entity.platform == DOMAIN:
            if entity.unique_id.endswith("_wake_on_lan"):
                wol_entity_id = entity.entity_id
                break

    if not wol_entity_id:
        return {"speech": "No Wake-on-LAN button found."}

    await hass.services.async_call("button", "press", {"entity_id": wol_entity_id})
    return {"speech": "Sending wake-up signal to the SteamOS device."}


async def _handle_set_volume(call: ServiceCall) -> dict[str, Any]:
    """Set system volume."""
    hass = call.hass
    level = call.data["level"]

    api, _, _, _ = _get_device_context(hass)
    if not api:
        return {"speech": "No SteamOS device is connected."}

    await api.set_volume(level)
    return {"speech": f"Volume set to {level} percent."}


# ─── Helpers ───


def _get_app_aliases(hass: HomeAssistant) -> dict[str, str]:
    """Get user-defined app aliases from the config entry options."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        aliases_raw = entry.options.get("app_aliases", "")
        if not aliases_raw:
            continue
        # Format: "youtube=rocks.shy.VacuumTube,browser=org.mozilla.firefox"
        aliases = {}
        for pair in aliases_raw.split(","):
            pair = pair.strip()
            if "=" in pair:
                key, val = pair.split("=", 1)
                aliases[key.strip().lower()] = val.strip()
        return aliases
    return {}
