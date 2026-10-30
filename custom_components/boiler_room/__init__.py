"""The Boiler Room integration."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoilerRoomAPI
from .const import CONF_DEVICE_ID, CONF_HOST, CONF_PORT, DOMAIN, PLATFORMS, SCAN_INTERVAL
from .services import async_register_services, async_unregister_services
from .voice import async_refresh_voice_triggers, async_remove_voice_triggers

_LOGGER = logging.getLogger(__name__)

type BoilerRoomConfigEntry = ConfigEntry

# WebSocket reconnect parameters. The cap stays low on purpose: after the
# machine wakes, HA only notices once the socket reconnects, so a 30 s cap
# meant up to 30 s of stale "sleep". (Regressed to 30 once by accident in
# a1ccd82; keep this at 5.)
_WS_INITIAL_RETRY = 2  # seconds
_WS_MAX_RETRY = 5  # seconds
_WS_RECEIVE_TIMEOUT = 120  # seconds without a frame (agent pings every 30)
_WS_CLOSE_TIMEOUT = 10  # seconds

_STORAGE_VERSION = 1
# Pre-2026.10.29 store: one file shared by every device. Migrated on load.
_LEGACY_STORAGE_KEY = f"{DOMAIN}.power_state"

POWER_STATE_ON = "on"


async def async_setup_entry(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> bool:
    """Set up Boiler Room from a config entry.

    The setup succeeds even when the device is offline: the WoL button
    and the voice sentences must always be available. The coordinator
    polls in the background and entities that need live data show as
    unavailable until the device comes online.
    """
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    api = BoilerRoomAPI(host, port)
    coordinator = BoilerRoomCoordinator(hass, api, entry)

    # Restore the last known power state from disk BEFORE the first poll.
    # If the device is sleeping and HA just restarted, the sensor must show
    # "sleep" instead of "unknown" even though every poll will fail.
    await coordinator.async_load_persisted_state()

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        _LOGGER.warning(
            "Could not reach %s:%s on startup; will keep retrying. "
            "WoL and voice commands are still available.",
            host, port,
        )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await _start_jellyfin_cache(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _remove_legacy_entities(hass, entry)

    async_register_services(hass)
    async_refresh_voice_triggers(hass)

    ws_task = hass.async_create_background_task(
        coordinator.async_start_websocket(),
        f"boiler_room_ws_{entry.entry_id}",
    )
    hass.data[DOMAIN][entry.entry_id]["ws_task"] = ws_task

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        api: BoilerRoomAPI = data["api"]
        await api.close()

        ws_task = data.get("ws_task")
        if ws_task and not ws_task.done():
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass

        cache = data.get("jellyfin_cache")
        if cache:
            await cache.stop()

        if hass.data[DOMAIN]:
            async_refresh_voice_triggers(hass)
        else:
            async_remove_voice_triggers(hass)
            async_unregister_services(hass)

    return unload_ok


async def _async_options_updated(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> None:
    """Handle options update: new nicknames and Jellyfin cache settings."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not entry_data:
        return

    async_refresh_voice_triggers(hass)

    old_cache = entry_data.get("jellyfin_cache")
    if old_cache:
        await old_cache.stop()
        entry_data["jellyfin_cache"] = None

    await _start_jellyfin_cache(hass, entry)


def _remove_legacy_entities(hass: HomeAssistant, entry: BoilerRoomConfigEntry) -> None:
    """Drop registry entries for entities this version no longer creates.

    The "Create Voice Automations" button went away in 2026.10.29.1 when
    the integration started registering its sentences itself. Without
    this the button lingers as "unavailable" on the device page.
    """
    registry = er.async_get(hass)
    device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)
    for unique_id in (f"{device_id}_create_voice_automations",):
        entity_id = registry.async_get_entity_id("button", DOMAIN, unique_id)
        if entity_id:
            _LOGGER.info("Removing retired entity %s", entity_id)
            registry.async_remove(entity_id)


async def _start_jellyfin_cache(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> None:
    """Start the Jellyfin media cache if Jellyfin is configured and caching is enabled."""
    options = entry.options
    jf_url = options.get("jellyfin_url", "").strip()
    jf_key = options.get("jellyfin_api_key", "").strip()

    if not jf_url or not jf_key:
        return

    cache_types: list[str] = []
    if options.get("cache_artists", True):
        cache_types.append("MusicArtist")
    if options.get("cache_albums", True):
        cache_types.append("MusicAlbum")
    if not cache_types:
        return

    refresh_minutes = options.get("cache_interval", 30)

    from .core.jellyfin_cache import JellyfinMediaCache

    cache = JellyfinMediaCache(
        session=async_get_clientsession(hass),
        jf_url=jf_url,
        jf_key=jf_key,
        cache_types=cache_types,
        refresh_minutes=refresh_minutes,
    )

    try:
        await cache.start()
        hass.data[DOMAIN][entry.entry_id]["jellyfin_cache"] = cache
        _LOGGER.info(
            "Jellyfin media cache started: %d items cached (types: %s, refresh: %dm)",
            cache.item_count,
            ", ".join(cache_types),
            refresh_minutes,
        )
    except Exception:
        _LOGGER.exception("Failed to start Jellyfin media cache")


def _empty_data() -> dict[str, Any]:
    """Coordinator data shape with nothing in it (device never reached)."""
    return {
        "status": {},
        "games": [],
        "apps": [],
        "sensors": {},
        "shortcuts": [],
        "users": {},
    }


class BoilerRoomCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch data from the Boiler Room agent.

    Combines HTTP polling (every SCAN_INTERVAL seconds) with a persistent
    WebSocket connection that pushes power state changes instantly.

    Power state model:
    - A successful poll is authoritative: the agent reports its own
      power_state in /status (it knows about a pending suspend before
      the machine goes down).
    - A WebSocket event overwrites the power_state in the current data
      and notifies entities immediately.
    - Failed polls leave the data untouched, so the last pushed state
      ("sleep", "shutdown") survives while the machine is unreachable.
    - The last state is persisted per config entry and seeded back into
      the data on startup, so an HA restart while the machine sleeps
      still shows "sleep".
    """

    def __init__(
        self, hass: HomeAssistant, api: BoilerRoomAPI, entry: ConfigEntry
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self._host = entry.data[CONF_HOST]
        self._port = entry.data[CONF_PORT]
        self._store = Store(
            hass, _STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.power_state"
        )
        self._legacy_store = Store(hass, _STORAGE_VERSION, _LEGACY_STORAGE_KEY)
        # Last power state written to disk; writes only happen on change.
        self._persisted_power_state: str | None = None

    # ─── Power state ───

    @property
    def power_state(self) -> str | None:
        """Current power state from coordinator data, if any."""
        if self.data:
            return self.data.get("status", {}).get("power_state")
        return None

    async def async_load_persisted_state(self) -> None:
        """Seed the power state from disk before the first poll.

        Without this seed the sensor shows "unknown" after an HA restart
        while the device is asleep: every poll fails, so coordinator data
        never exists for the sensor to read.
        """
        stored = await self._store.async_load()
        if stored is None:
            stored = await self._legacy_store.async_load()
            if stored is not None:
                await self._legacy_store.async_remove()

        state = stored.get("power_state") if isinstance(stored, dict) else None
        if not state:
            return

        self._persisted_power_state = state
        if state != POWER_STATE_ON:
            _LOGGER.info("Restoring persisted power state: %s", state)
            self.async_set_updated_data(self._with_power_state(state))

    def _with_power_state(self, state: str) -> dict[str, Any]:
        """Return a copy of the current data with power_state replaced."""
        data = dict(self.data) if self.data else _empty_data()
        status = dict(data.get("status") or {})
        status["power_state"] = state
        data["status"] = status
        return data

    def _persist_power_state(self, state: str) -> None:
        """Write the power state to disk if it changed since the last write."""
        if state == self._persisted_power_state:
            return
        self._persisted_power_state = state
        self.hass.async_create_task(self._store.async_save({"power_state": state}))

    def _apply_pushed_power_state(self, state: str) -> None:
        """Apply a power state received over the WebSocket."""
        _LOGGER.info("WebSocket: power state changed -> %s", state)
        self._persist_power_state(state)
        self.async_set_updated_data(self._with_power_state(state))

    # ─── Polling ───

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the agent via HTTP."""
        try:
            status = await self.api.get_status()
            games = await self.api.get_games()
            apps = await self.api.get_apps()
            sensors = await self.api.get_sensors()
            shortcuts = await self.api.get_shortcuts()
            # Steam users are optional (older agents do not have the endpoint).
            try:
                users = await self.api.get_users()
            except Exception:
                users = {}
        except Exception as err:
            # Device unreachable (sleeping, off, rebooting). Data is left as
            # is, so the last pushed power state stays visible.
            raise UpdateFailed(f"Error communicating with agent: {err}") from err

        self._persist_power_state(status.get("power_state", POWER_STATE_ON))
        return {
            "status": status,
            "games": games,
            "apps": apps,
            "sensors": sensors,
            "shortcuts": shortcuts,
            "users": users,
        }

    # ─── WebSocket ───

    async def async_start_websocket(self) -> None:
        """Connect to the agent WebSocket and listen for real-time events.

        Reconnects with exponential backoff (capped at _WS_MAX_RETRY) for
        the lifetime of the config entry.
        """
        retry_delay = _WS_INITIAL_RETRY
        ws_url = f"ws://{self._host}:{self._port}/api/v1/ws"
        session = async_get_clientsession(self.hass)
        ws_timeout = aiohttp.ClientWSTimeout(
            ws_receive=_WS_RECEIVE_TIMEOUT, ws_close=_WS_CLOSE_TIMEOUT
        )

        while True:
            try:
                async with session.ws_connect(
                    ws_url, heartbeat=30, timeout=ws_timeout
                ) as ws:
                    retry_delay = _WS_INITIAL_RETRY
                    _LOGGER.info("WebSocket connected to %s", ws_url)

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_ws_message(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break

            except asyncio.CancelledError:
                _LOGGER.debug("WebSocket listener cancelled")
                return

            except Exception as err:
                _LOGGER.debug(
                    "WebSocket connection to %s failed: %s; retrying in %ds",
                    ws_url, err, retry_delay,
                )

            try:
                await asyncio.sleep(retry_delay)
            except asyncio.CancelledError:
                return
            retry_delay = min(retry_delay * 2, _WS_MAX_RETRY)

    def _handle_ws_message(self, raw: str) -> None:
        """Process an incoming WebSocket message from the agent."""
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.debug("WebSocket: ignoring malformed message: %s", raw[:200])
            return

        if not isinstance(event, dict):
            return

        if event.get("type") == "power_state_changed":
            new_state = (event.get("data") or {}).get("power_state")
            if new_state:
                self._apply_pushed_power_state(new_state)
