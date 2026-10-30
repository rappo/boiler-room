"""Boiler Room actions: plain handlers plus thin HA services over them.

Every handler is an async function taking ``hass``, its parameters and an
optional ``entry_id`` (which device), and returns a dict with at least a
``speech`` key. Two callers share them:

- the sentence triggers in ``voice.py``, which know the entry from the
  nickname that was spoken and return ``speech`` to Assist;
- the ``boiler_room.*`` services below, which resolve their optional
  ``device`` argument to an entry first and return the dict as the
  service response.

Pure logic (matching, Jellyfin requests, sentence templates) lives in
``core/`` and is unit-tested without HA.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote_plus

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICE_NAME, CONF_DEVICE_NICKNAMES, DOMAIN
from .core import jellyfin
from .core.matching import fuzzy_match_app, fuzzy_match_game, parse_app_aliases
from .core.sentences import default_nicknames, match_device, parse_nicknames
from .core.wol import send_magic_packet

_LOGGER = logging.getLogger(__name__)

Response = dict[str, Any]
Handler = Callable[..., Awaitable[Response]]

DEFAULT_JELLYFIN_APP = "org.jellyfin.JellyfinDesktop"

_POWER_LABELS = {"suspend": "Suspending", "shutdown": "Shutting down", "reboot": "Rebooting"}
_PLAYSTATE_LABELS = {
    "pause": "Paused",
    "unpause": "Resumed",
    "stop": "Stopped",
    "rewind": "Rewinding",
    "fastforward": "Fast-forwarding",
}


# ─── Entries and targets ───


def loaded_entries(hass: HomeAssistant) -> list[tuple[ConfigEntry, dict[str, Any]]]:
    """Config entries that finished setup, with their hass.data records."""
    records = hass.data.get(DOMAIN, {})
    return [
        (entry, records[entry.entry_id])
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id in records
    ]


def device_name(entry: ConfigEntry) -> str:
    """The name the agent reported for this device."""
    return entry.data.get(CONF_DEVICE_NAME) or entry.title or "the SteamOS device"


def entry_nicknames(entry: ConfigEntry) -> list[str]:
    """Nicknames this device answers to; blank option means the defaults."""
    configured = parse_nicknames(entry.options.get(CONF_DEVICE_NICKNAMES))
    return configured or default_nicknames(device_name(entry))


def device_names(hass: HomeAssistant) -> dict[str, list[str]]:
    """Every name each loaded entry answers to, for resolving ``device``."""
    return {
        entry.entry_id: [*entry_nicknames(entry), device_name(entry), entry.title]
        for entry, _ in loaded_entries(hass)
    }


def resolve_entry_id(hass: HomeAssistant, device: str | None) -> str | None:
    """Map a spoken or typed device name to a loaded entry id."""
    return match_device(device, device_names(hass))


def _target(
    hass: HomeAssistant, entry_id: str | None
) -> tuple[ConfigEntry, dict[str, Any]] | None:
    """The entry to act on: the one named, else the first that was reached."""
    entries = loaded_entries(hass)
    if entry_id is not None:
        return next(((e, r) for e, r in entries if e.entry_id == entry_id), None)
    for entry, record in entries:
        if record["coordinator"].data:
            return entry, record
    return entries[0] if entries else None


def _no_device() -> Response:
    return {"speech": "No SteamOS device is connected."}


def _unreachable(entry: ConfigEntry) -> Response:
    return {"speech": f"{device_name(entry)} did not answer."}


def _coordinator_list(record: dict[str, Any], key: str) -> list[dict[str, Any]]:
    data = record["coordinator"].data or {}
    return data.get(key, [])


# ─── Jellyfin helpers ───


def _jellyfin_config(entry: ConfigEntry) -> dict[str, str] | None:
    options = entry.options
    jf_url = options.get("jellyfin_url", "").strip()
    jf_key = options.get("jellyfin_api_key", "").strip()
    if not jf_url or not jf_key:
        return None
    return {
        "url": jf_url.rstrip("/"),
        "api_key": jf_key,
        "app_id": options.get("jellyfin_app_id", DEFAULT_JELLYFIN_APP).strip(),
        "youtube_app_id": options.get("youtube_app_id", "").strip(),
    }


def _jellyfin_target(
    hass: HomeAssistant, entry_id: str | None
) -> tuple[ConfigEntry, dict[str, Any], dict[str, str]] | Response:
    """The entry whose Jellyfin settings apply, or the speech saying why not."""
    if entry_id is not None:
        target = _target(hass, entry_id)
        if target is None:
            return _no_device()
        config = _jellyfin_config(target[0])
        if config is None:
            return {"speech": f"Jellyfin is not configured for {device_name(target[0])}."}
        return target[0], target[1], config
    for entry, record in loaded_entries(hass):
        config = _jellyfin_config(entry)
        if config is not None:
            return entry, record, config
    return {"speech": "Jellyfin is not configured."}


def _resolve_query(record: dict[str, Any], query: str) -> str:
    """Run a voice query through the entry's phonetic cache, if running."""
    cache = record.get("jellyfin_cache")
    if not cache:
        return query
    resolved_name, _ = cache.match_or_query(query)
    if resolved_name != query:
        _LOGGER.info("Cache resolved '%s' -> '%s'", query, resolved_name)
    return resolved_name


async def _find_or_launch_session(
    record: dict[str, Any], session, config: dict[str, str]
) -> str | None:
    """Find a controllable Jellyfin session, launching the client app if needed."""
    jf_url, jf_key, jf_app = config["url"], config["api_key"], config["app_id"]
    session_id = await jellyfin.find_session(session, jf_url, jf_key)
    if session_id:
        return session_id
    if jf_app:
        try:
            await record["api"].launch(appid=jf_app, launch_type="app")
        except Exception:
            _LOGGER.warning("Could not launch Jellyfin app %s", jf_app)
        await asyncio.sleep(5)
        session_id = await jellyfin.find_session(session, jf_url, jf_key)
    return session_id


# ─── Launching ───


async def _launch_game_entry(
    entry: ConfigEntry, record: dict[str, Any], game: dict[str, Any]
) -> Response:
    try:
        result = await record["api"].launch(appid=game["appid"])
    except Exception:
        _LOGGER.warning("Launch of %s on %s failed", game["name"], device_name(entry))
        return _unreachable(entry)
    if result.get("status") == "launching":
        return {
            "speech": f"Launching {game['name']}.",
            "matched_name": game["name"],
            "appid": game["appid"],
        }
    return {"speech": f"Failed to launch {game['name']}."}


async def _launch_app_entry(
    entry: ConfigEntry, record: dict[str, Any], name: str, flatpak_id: str
) -> Response:
    try:
        result = await record["api"].launch(appid=flatpak_id, launch_type="app")
    except Exception:
        _LOGGER.warning("Launch of %s on %s failed", flatpak_id, device_name(entry))
        return _unreachable(entry)
    if result.get("status") == "launching":
        return {"speech": f"Opening {name}.", "matched_name": name, "app_id": flatpak_id}
    return {"speech": f"Failed to open {name}."}


def _match_app(
    entry: ConfigEntry, record: dict[str, Any], name: str
) -> tuple[str, str] | None:
    """(display name, flatpak id) from the entry's aliases, then installed apps."""
    aliases = parse_app_aliases(entry.options.get("app_aliases", ""))
    key = name.lower().strip()
    if key in aliases:
        return name, aliases[key]
    app = fuzzy_match_app(name, _coordinator_list(record, "apps"))
    if app:
        return app["name"], app["id"]
    return None


async def launch_game(hass: HomeAssistant, name: str, *, entry_id: str | None = None) -> Response:
    """Launch a game by name with fuzzy matching; falls back to apps."""
    target = _target(hass, entry_id)
    if target is None:
        return _no_device()
    entry, record = target

    game = fuzzy_match_game(name, _coordinator_list(record, "games"))
    if game:
        return await _launch_game_entry(entry, record, game)

    app = _match_app(entry, record, name)
    if app:
        return await _launch_app_entry(entry, record, *app)

    return {"speech": f"I couldn't find a game or app matching '{name}'."}


async def launch_app(hass: HomeAssistant, name: str, *, entry_id: str | None = None) -> Response:
    """Launch a Flatpak app by alias or name; falls back to games."""
    target = _target(hass, entry_id)
    if target is None:
        return _no_device()
    entry, record = target

    app = _match_app(entry, record, name)
    if app:
        return await _launch_app_entry(entry, record, *app)

    game = fuzzy_match_game(name, _coordinator_list(record, "games"))
    if game:
        return await _launch_game_entry(entry, record, game)

    return {
        "speech": (
            f"Couldn't find an app or game named {name}. "
            "You can add an app alias in Settings > Integrations > Boiler Room > Configure."
        )
    }


# ─── Jellyfin ───


async def jellyfin_play(
    hass: HomeAssistant,
    query: str,
    media_type: str | None = None,
    *,
    entry_id: str | None = None,
) -> Response:
    """Search Jellyfin and play the top result."""
    target = _jellyfin_target(hass, entry_id)
    if isinstance(target, dict):
        return target
    _entry, record, config = target
    jf_url, jf_key = config["url"], config["api_key"]
    session = async_get_clientsession(hass)

    items = await jellyfin.search(
        session, jf_url, jf_key, _resolve_query(record, query), media_type
    )
    if not items:
        hint = f" {media_type.lower()}" if media_type else ""
        return {"speech": f"I couldn't find a{hint} matching '{query}' on Jellyfin."}

    item = items[0]
    item_name = item.get("Name", query)
    item_id = item.get("Id", "")
    item_type = item.get("Type", "")
    type_label = jellyfin.TYPE_LABELS.get(item_type, item_type.lower())
    details = {"item_name": item_name, "item_id": item_id, "item_type": item_type}

    session_id = await _find_or_launch_session(record, session, config)
    if session_id and item_id and await jellyfin.play(
        session, jf_url, jf_key, session_id, item_id
    ):
        return {"speech": f"Playing the {type_label} {item_name} on Jellyfin.", **details}

    return {
        "speech": f"Found the {type_label} {item_name}, but no active Jellyfin session.",
        **details,
    }


async def jellyfin_browse(
    hass: HomeAssistant,
    query: str,
    media_type: str | None = None,
    *,
    entry_id: str | None = None,
) -> Response:
    """Search Jellyfin and navigate to the item's page."""
    target = _jellyfin_target(hass, entry_id)
    if isinstance(target, dict):
        return target
    _entry, record, config = target
    jf_url, jf_key = config["url"], config["api_key"]
    session = async_get_clientsession(hass)

    items = await jellyfin.search(
        session, jf_url, jf_key, _resolve_query(record, query),
        media_type or jellyfin.BROWSE_TYPES_DEFAULT,
    )
    if not items:
        return {"speech": f"I couldn't find anything matching '{query}' on Jellyfin."}

    item = items[0]
    item_name = item.get("Name", query)
    item_id = item.get("Id", "")

    session_id = await _find_or_launch_session(record, session, config)
    if session_id and item_id and await jellyfin.view(
        session, jf_url, jf_key, session_id, item
    ):
        return {"speech": f"Showing {item_name} on Jellyfin.", "item_name": item_name, "item_id": item_id}

    return {"speech": f"Found {item_name}, but no active Jellyfin session."}


async def jellyfin_control(
    hass: HomeAssistant, action: str, *, entry_id: str | None = None
) -> Response:
    """Control Jellyfin playback (pause, unpause, stop, rewind, fastforward)."""
    target = _jellyfin_target(hass, entry_id)
    if isinstance(target, dict):
        return target
    _entry, _record, config = target
    jf_url, jf_key = config["url"], config["api_key"]
    session = async_get_clientsession(hass)

    session_id = await jellyfin.find_session(session, jf_url, jf_key)
    if not session_id:
        return {"speech": "No active Jellyfin session found."}

    if await jellyfin.playstate(session, jf_url, jf_key, session_id, action):
        return {"speech": f"{_PLAYSTATE_LABELS[action]} Jellyfin playback."}
    return {"speech": f"Failed to {action} Jellyfin playback."}


# ─── YouTube, power, volume ───


async def youtube_search(hass: HomeAssistant, query: str, *, entry_id: str | None = None) -> Response:
    """Open a YouTube search in the configured client app (or the browser)."""
    target = _target(hass, entry_id)
    if target is None:
        return _no_device()
    entry, record = target
    youtube_app = entry.options.get("youtube_app_id", "").strip()
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    try:
        if youtube_app:
            await record["api"].launch(appid=youtube_app, launch_type="app")
            await asyncio.sleep(2)
        await record["api"].launch(url=search_url, launch_type="url")
    except Exception:
        _LOGGER.warning("YouTube search on %s failed", device_name(entry))
        return _unreachable(entry)
    return {"speech": f"Searching YouTube for {query}."}


async def power(hass: HomeAssistant, action: str, *, entry_id: str | None = None) -> Response:
    """Suspend, shut down or reboot the device."""
    target = _target(hass, entry_id)
    if target is None:
        return _no_device()
    entry, record = target
    try:
        await record["api"].power_action(action)
    except Exception:
        _LOGGER.warning("Power action %s on %s failed", action, device_name(entry))
        return _unreachable(entry)
    return {"speech": f"{_POWER_LABELS[action]} {device_name(entry)}."}


async def wake(hass: HomeAssistant, *, entry_id: str | None = None) -> Response:
    """Send a Wake-on-LAN magic packet to the device's last known MAC."""
    target = _target(hass, entry_id)
    if target is None:
        return _no_device()
    entry, record = target
    status = (record["coordinator"].data or {}).get("status", {})
    mac = entry.data.get("mac_address") or status.get("mac_address")
    if not mac:
        return {
            "speech": (
                f"I don't know the MAC address of {device_name(entry)} yet. "
                "It is learned the first time the device is online."
            )
        }
    await hass.async_add_executor_job(send_magic_packet, mac)
    return {"speech": f"Sending a wake-up signal to {device_name(entry)}.", "mac_address": mac}


async def set_volume(hass: HomeAssistant, level: int, *, entry_id: str | None = None) -> Response:
    """Set the system volume (0-100)."""
    target = _target(hass, entry_id)
    if target is None:
        return _no_device()
    entry, record = target
    try:
        await record["api"].set_volume(level)
    except Exception:
        _LOGGER.warning("Volume change on %s failed", device_name(entry))
        return _unreachable(entry)
    return {"speech": f"Volume set to {level} percent."}


# ─── HA services ───

_DEVICE_FIELD = {vol.Optional("device"): str}

_SERVICES: tuple[tuple[str, Handler, vol.Schema, dict[str, str]], ...] = (
    # service name, handler, schema, service field -> handler keyword
    ("launch_game", launch_game, vol.Schema({vol.Required("name"): str, **_DEVICE_FIELD}), {"name": "name"}),
    ("launch_app", launch_app, vol.Schema({vol.Required("name"): str, **_DEVICE_FIELD}), {"name": "name"}),
    (
        "jellyfin_play",
        jellyfin_play,
        vol.Schema({vol.Required("query"): str, vol.Optional("type"): str, **_DEVICE_FIELD}),
        {"query": "query", "type": "media_type"},
    ),
    (
        "jellyfin_browse",
        jellyfin_browse,
        vol.Schema({vol.Required("query"): str, vol.Optional("type"): str, **_DEVICE_FIELD}),
        {"query": "query", "type": "media_type"},
    ),
    (
        "jellyfin_control",
        jellyfin_control,
        vol.Schema({vol.Required("action"): vol.In(list(jellyfin.PLAYSTATE_COMMANDS)), **_DEVICE_FIELD}),
        {"action": "action"},
    ),
    ("youtube_search", youtube_search, vol.Schema({vol.Required("query"): str, **_DEVICE_FIELD}), {"query": "query"}),
    (
        "power",
        power,
        vol.Schema({vol.Required("action"): vol.In(list(_POWER_LABELS)), **_DEVICE_FIELD}),
        {"action": "action"},
    ),
    ("wake", wake, vol.Schema(_DEVICE_FIELD), {}),
    (
        "set_volume",
        set_volume,
        vol.Schema({vol.Required("level"): vol.All(int, vol.Range(min=0, max=100)), **_DEVICE_FIELD}),
        {"level": "level"},
    ),
)


def _service_handler(handler: Handler, fields: dict[str, str]):
    async def _handle(call: ServiceCall) -> Response:
        hass = call.hass
        entry_id = None
        device = call.data.get("device")
        if device:
            entry_id = resolve_entry_id(hass, device)
            if entry_id is None:
                return {"speech": f"I don't know a device called {device}."}
        kwargs = {kw: call.data[field] for field, kw in fields.items() if field in call.data}
        return await handler(hass, entry_id=entry_id, **kwargs)

    return _handle


def async_register_services(hass: HomeAssistant) -> None:
    """Register the boiler_room.* services once."""
    if hass.services.has_service(DOMAIN, _SERVICES[0][0]):
        return
    for name, handler, schema, fields in _SERVICES:
        hass.services.async_register(
            DOMAIN,
            name,
            _service_handler(handler, fields),
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
    _LOGGER.info("Boiler Room services registered")


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the services (when the last config entry is unloaded)."""
    for name, *_ in _SERVICES:
        hass.services.async_remove(DOMAIN, name)
