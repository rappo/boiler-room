"""Boiler Room actions: plain handlers, and the table that describes them.

Every handler is an async function taking ``hass``, its parameters and an
optional ``entry_id`` (which device), and returns a dict with at least a
``speech`` key. ``ACTIONS`` lists them with their fields, written once and
read by three layers:

- ``intents.py`` registers one intent handler per action (the one code
  path every voice or LLM command goes through), and ``llm.py`` turns those
  into tools with the action's description and annotations;
- the sentence triggers in ``voice.py`` map a matched template to an
  action's intent and slots;
- the ``boiler_room.*`` services below, which resolve their optional
  ``device`` argument to an entry first and return the dict as the
  service response.

Schemas use ``probatio``, the validation library Home Assistant ships
(``voluptuous`` left its requirements in 2026 and is only installed by
accident, through other packages). Pure logic (matching, Jellyfin requests,
sentence templates, status summaries) lives in ``core/`` and is unit-tested
without HA.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

import aiohttp
import probatio as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICE_NAME, CONF_DEVICE_NICKNAMES, DOMAIN
from .core import jellyfin
from .core.matching import fuzzy_match_app, fuzzy_match_game, parse_app_aliases
from .core.sentences import (
    HANDLER_GET_STATUS,
    HANDLER_JELLYFIN_BROWSE,
    HANDLER_JELLYFIN_CONTROL,
    HANDLER_JELLYFIN_PLAY,
    HANDLER_LAUNCH_APP,
    HANDLER_LAUNCH_GAME,
    HANDLER_LIST_RECENT,
    HANDLER_POWER,
    HANDLER_SET_VOLUME,
    HANDLER_WAKE,
    HANDLER_YOUTUBE_SEARCH,
    default_nicknames,
    match_device,
    parse_nicknames,
)
from .core.status import summarize_recent, summarize_status
from .core.wol import send_magic_packet

_LOGGER = logging.getLogger(__name__)

Response = dict[str, Any]
Handler = Callable[..., Awaitable[Response]]

DEFAULT_JELLYFIN_APP = "org.jellyfin.JellyfinDesktop"

# What a call to the agent raises when the device is asleep, off or slow.
_AGENT_ERRORS = (aiohttp.ClientError, TimeoutError, OSError)

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
    """Map a device name, nickname or config entry id to a loaded entry id.

    An entry id is accepted as is (the sentence lane passes the entry its
    nickname belongs to); it is never part of the fuzzy name matching.
    """
    entries = loaded_entries(hass)
    if device and any(entry.entry_id == device for entry, _ in entries):
        return device
    own_names = {entry.entry_id: device_name(entry) for entry, _ in entries}
    return match_device(device, device_names(hass), own_names)


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
        except _AGENT_ERRORS:
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
    except _AGENT_ERRORS:
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
    except _AGENT_ERRORS:
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
    except _AGENT_ERRORS:
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
    except _AGENT_ERRORS:
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
    except _AGENT_ERRORS:
        _LOGGER.warning("Volume change on %s failed", device_name(entry))
        return _unreachable(entry)
    return {"speech": f"Volume set to {level} percent."}


# ─── Read-only ───


def _status_of(entry: ConfigEntry, record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = record["coordinator"].data or {}
    return summarize_status(device_name(entry), data.get("status"), data.get("sensors"))


async def get_status(hass: HomeAssistant, *, entry_id: str | None = None) -> Response:
    """What a device is doing; every device when none is named."""
    if entry_id is not None:
        target = _target(hass, entry_id)
        if target is None:
            return _no_device()
        speech, data = _status_of(*target)
        return {"speech": speech, **data}
    entries = loaded_entries(hass)
    if not entries:
        return _no_device()
    summaries = [_status_of(entry, record) for entry, record in entries]
    if len(summaries) == 1:
        speech, data = summaries[0]
        return {"speech": speech, **data}
    return {
        "speech": " ".join(speech for speech, _ in summaries),
        "devices": [data for _, data in summaries],
    }


async def list_recent(hass: HomeAssistant, *, entry_id: str | None = None) -> Response:
    """The games and apps launched most recently on a device, newest first."""
    target = _target(hass, entry_id)
    if target is None:
        return _no_device()
    entry, record = target
    try:
        items = await record["api"].get_recent()
    except _AGENT_ERRORS:
        _LOGGER.warning("Recent launches of %s unavailable", device_name(entry))
        return _unreachable(entry)
    speech, data = summarize_recent(device_name(entry), items)
    return {"speech": speech, **data}


# ─── The action table ───


@dataclass(frozen=True)
class Action:
    """One thing Boiler Room can do, described once for every caller.

    ``fields`` are the probatio markers and validators of the action's own
    parameters (the optional ``device`` is added by :attr:`schema`), and
    ``kwargs`` maps a field name to the handler keyword it feeds. The
    descriptions are read by LLM agents as the tool and parameter help, so
    they say when to pick this action over its neighbors.
    """

    name: str
    intent_type: str
    title: str
    description: str
    handler: Handler
    fields: dict[Any, Any] = field(default_factory=dict)
    kwargs: dict[str, str] = field(default_factory=dict)
    # True: the action changes one device, so a caller that cannot tell
    # which one must ask (the intent does). False: the handler picks the
    # device itself (Jellyfin), or reports on every device (read-only).
    targets_device: bool = True
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False

    @property
    def schema(self) -> dict[Any, Any]:
        """Every field including the optional ``device``, for schemas and slots."""
        return {**self.fields, **DEVICE_FIELD}


FIELD_DEVICE = "device"

DEVICE_FIELD: dict[Any, Any] = {
    vol.Optional(
        FIELD_DEVICE,
        description=(
            "Which SteamOS device: its name or one of its voice nicknames. "
            "Leave out when there is only one device."
        ),
    ): str
}

_QUERY_FIELD = {
    vol.Required("query", description="What to look for: a title, artist, album or person name."): str
}
_MEDIA_TYPES_PLAY = "Movie, Series, Episode, Audio (a song), MusicAlbum"
_MEDIA_TYPES_BROWSE = _MEDIA_TYPES_PLAY + ", MusicArtist, Person"

ACTIONS: tuple[Action, ...] = (
    Action(
        name=HANDLER_LAUNCH_GAME,
        intent_type="BoilerRoomLaunchGame",
        title="Launch a Steam game",
        description=(
            "Launch an installed Steam game on a SteamOS device (Steam Deck or SteamOS PC). "
            "The title is matched fuzzily against the installed games, so abbreviations work "
            "(bg3, civ, red dead). Use this for games. For a desktop app use "
            "BoilerRoomLaunchApp; for a movie, show or music use BoilerRoomJellyfinPlay. "
            "Falls back to the apps when no game matches."
        ),
        handler=launch_game,
        fields={
            vol.Required(
                "name", description="Game title as the user said it; matched fuzzily."
            ): str
        },
        kwargs={"name": "name"},
    ),
    Action(
        name=HANDLER_LAUNCH_APP,
        intent_type="BoilerRoomLaunchApp",
        title="Open a desktop app",
        description=(
            "Open a Flatpak desktop app (Firefox, Discord, the Jellyfin client, ...) on a "
            "SteamOS device, by name or by one of the user's app aliases. Not for Steam games "
            "(BoilerRoomLaunchGame) or for media (BoilerRoomJellyfinPlay). Falls back to the "
            "games when no app matches."
        ),
        handler=launch_app,
        fields={vol.Required("name", description="App name or alias."): str},
        kwargs={"name": "name"},
    ),
    Action(
        name=HANDLER_JELLYFIN_PLAY,
        intent_type="BoilerRoomJellyfinPlay",
        title="Play from Jellyfin",
        description=(
            "Search the Jellyfin media library and play the top result in the Jellyfin client "
            "on the SteamOS device, launching the client first if it is not running. For "
            "movies, series, episodes, albums and songs in the user's own library. Give type "
            "to narrow the search. Not for Steam games (BoilerRoomLaunchGame) or YouTube "
            "(BoilerRoomYoutubeSearch)."
        ),
        handler=jellyfin_play,
        fields={
            **_QUERY_FIELD,
            vol.Optional("type", description=f"Limit to one media type: {_MEDIA_TYPES_PLAY}."): str,
        },
        kwargs={"query": "query", "type": "media_type"},
        targets_device=False,
    ),
    Action(
        name=HANDLER_JELLYFIN_BROWSE,
        intent_type="BoilerRoomJellyfinBrowse",
        title="Show in Jellyfin",
        description=(
            "Open an item's page in the Jellyfin client without playing it, so the user can "
            "pick an episode or read about it. Use when the user wants to see, find or browse "
            "something; use BoilerRoomJellyfinPlay when they want it to start playing."
        ),
        handler=jellyfin_browse,
        fields={
            **_QUERY_FIELD,
            vol.Optional("type", description=f"Limit to one media type: {_MEDIA_TYPES_BROWSE}."): str,
        },
        kwargs={"query": "query", "type": "media_type"},
        targets_device=False,
    ),
    Action(
        name=HANDLER_JELLYFIN_CONTROL,
        intent_type="BoilerRoomJellyfinControl",
        title="Control Jellyfin playback",
        description=(
            "Control what the Jellyfin client is playing on the SteamOS device: pause, "
            "unpause (resume), stop, rewind or fastforward. Only for Jellyfin playback, not "
            "for games."
        ),
        handler=jellyfin_control,
        fields={
            vol.Required("action", description="pause, unpause, stop, rewind or fastforward."): vol.In(
                list(jellyfin.PLAYSTATE_COMMANDS)
            )
        },
        kwargs={"action": "action"},
        targets_device=False,
        idempotent=True,
    ),
    Action(
        name=HANDLER_YOUTUBE_SEARCH,
        intent_type="BoilerRoomYoutubeSearch",
        title="Search YouTube",
        description=(
            "Open a YouTube search for the query on the SteamOS device, in the configured "
            "YouTube app or the browser. Use for anything on YouTube; the user's own library "
            "is Jellyfin (BoilerRoomJellyfinPlay)."
        ),
        handler=youtube_search,
        fields={vol.Required("query", description="What to search YouTube for."): str},
        kwargs={"query": "query"},
    ),
    Action(
        name=HANDLER_POWER,
        intent_type="BoilerRoomPower",
        title="Suspend, shut down or reboot",
        description=(
            "Suspend (sleep), shut down or reboot a SteamOS device. This interrupts whatever "
            "is running on it. To turn a device on, use BoilerRoomWake."
        ),
        handler=power,
        fields={
            vol.Required("action", description="suspend, shutdown or reboot."): vol.In(
                list(_POWER_LABELS)
            )
        },
        kwargs={"action": "action"},
        destructive=True,
    ),
    Action(
        name=HANDLER_WAKE,
        intent_type="BoilerRoomWake",
        title="Wake a device",
        description=(
            "Turn on a sleeping or powered-off SteamOS device with Wake-on-LAN. Harmless when "
            "the device is already on. Use BoilerRoomPower to suspend or shut down."
        ),
        handler=wake,
        idempotent=True,
    ),
    Action(
        name=HANDLER_SET_VOLUME,
        intent_type="BoilerRoomSetVolume",
        title="Set the volume",
        description="Set the system volume of a SteamOS device, from 0 (mute) to 100 percent.",
        handler=set_volume,
        fields={
            vol.Required("level", description="Volume from 0 to 100."): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=100)
            )
        },
        kwargs={"level": "level"},
        idempotent=True,
    ),
    Action(
        name=HANDLER_GET_STATUS,
        intent_type="BoilerRoomGetStatus",
        title="Device status",
        description=(
            "Report on a SteamOS device: power state (on, sleep, shutdown), what it is doing "
            "(idle, or the game or app it is running), CPU and GPU temperature, volume and "
            "battery. Without device it reports on every device. Changes nothing."
        ),
        handler=get_status,
        targets_device=False,
        read_only=True,
        idempotent=True,
    ),
    Action(
        name=HANDLER_LIST_RECENT,
        intent_type="BoilerRoomListRecent",
        title="Recent launches",
        description=(
            "List the games and apps launched most recently on a SteamOS device, newest "
            "first, with their type (game, app or shortcut). Changes nothing."
        ),
        handler=list_recent,
        targets_device=False,
        read_only=True,
        idempotent=True,
    ),
)

ACTIONS_BY_NAME: dict[str, Action] = {action.name: action for action in ACTIONS}


# ─── HA services ───

def _service_handler(action: Action):
    async def _handle(call: ServiceCall) -> Response:
        hass = call.hass
        entry_id = None
        device = call.data.get(FIELD_DEVICE)
        if device:
            entry_id = resolve_entry_id(hass, device)
            if entry_id is None:
                return {"speech": f"I don't know a device called {device}."}
        kwargs = {kw: call.data[name] for name, kw in action.kwargs.items() if name in call.data}
        return await action.handler(hass, entry_id=entry_id, **kwargs)

    return _handle


def async_register_services(hass: HomeAssistant) -> None:
    """Register the boiler_room.* services once."""
    if hass.services.has_service(DOMAIN, ACTIONS[0].name):
        return
    for action in ACTIONS:
        hass.services.async_register(
            DOMAIN,
            action.name,
            _service_handler(action),
            schema=vol.Schema(action.schema),
            supports_response=SupportsResponse.OPTIONAL,
        )
    _LOGGER.info("Boiler Room services registered")


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the services (when the last config entry is unloaded)."""
    for action in ACTIONS:
        hass.services.async_remove(DOMAIN, action.name)
