"""The Boiler Room integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoilerRoomAPI
from .const import CONF_HOST, CONF_PORT, DOMAIN, PLATFORMS, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type BoilerRoomConfigEntry = ConfigEntry

# WebSocket reconnect parameters
_WS_INITIAL_RETRY = 2  # seconds
_WS_MAX_RETRY = 30  # seconds
_STORAGE_KEY = f"{DOMAIN}.power_state"
_STORAGE_VERSION = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> bool:
    """Set up Boiler Room from a config entry.

    The setup succeeds even when the device is offline — WoL and
    Create Voice Automations buttons must always be available.
    The coordinator polls in the background and entities that need
    live data will show as unavailable until the device comes online.
    """
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    api = BoilerRoomAPI(host, port)

    coordinator = BoilerRoomCoordinator(hass, api, host, port)

    # Restore last known power state from disk BEFORE the first poll.
    # If the device is sleeping and HA just restarted, this ensures
    # the sensor shows "sleep" instead of defaulting to "on".
    await coordinator.async_load_persisted_state()

    # Try to fetch initial data, but don't fail setup if device is offline.
    # This is critical: WoL needs to work when the device is suspended/off.
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        _LOGGER.warning(
            "Could not reach %s:%s on startup — will keep retrying. "
            "WoL and Create Voice Automations are still available.",
            host, port,
        )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    # Start Jellyfin media cache if configured
    await _start_jellyfin_cache(hass, entry)

    # Restart cache when options change (Jellyfin URL, cache toggles, etc.)
    entry.async_on_unload(
        entry.add_update_listener(_async_options_updated)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register HA services (callable from automations/blueprints)
    from .services import async_register_services
    async_register_services(hass)

    # Start WebSocket listener for real-time power state updates
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

        # Cancel the WebSocket listener
        ws_task = data.get("ws_task")
        if ws_task and not ws_task.done():
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass

        # Stop the Jellyfin cache if running
        cache = data.get("jellyfin_cache")
        if cache:
            await cache.stop()

    return unload_ok


async def _async_options_updated(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> None:
    """Handle options update — restart Jellyfin cache with new settings."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not entry_data:
        return

    # Stop existing cache
    old_cache = entry_data.get("jellyfin_cache")
    if old_cache:
        await old_cache.stop()
        entry_data["jellyfin_cache"] = None

    # Start new cache with updated options
    await _start_jellyfin_cache(hass, entry)


async def _start_jellyfin_cache(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> None:
    """Start the Jellyfin media cache if Jellyfin is configured and caching is enabled."""
    options = entry.options
    jf_url = options.get("jellyfin_url", "").strip()
    jf_key = options.get("jellyfin_api_key", "").strip()

    if not jf_url or not jf_key:
        return

    cache_artists = options.get("cache_artists", True)
    cache_albums = options.get("cache_albums", True)

    if not cache_artists and not cache_albums:
        return

    # Build the list of Jellyfin item types to cache
    cache_types: list[str] = []
    if cache_artists:
        cache_types.append("MusicArtist")
    if cache_albums:
        cache_types.append("MusicAlbum")

    refresh_minutes = options.get("cache_interval", 30)

    from .jellyfin_cache import JellyfinMediaCache

    cache = JellyfinMediaCache(
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


class BoilerRoomCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch data from the Boiler Room agent.

    Combines HTTP polling (fallback, every SCAN_INTERVAL seconds) with a
    persistent WebSocket connection that receives instant push updates
    for power state changes and other real-time events.
    """

    def __init__(
        self, hass: HomeAssistant, api: BoilerRoomAPI, host: str, port: int
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self._host = host
        self._port = port
        self._ws_connected = False
        self._store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        # Holds the last power state pushed via WebSocket, so HTTP poll
        # failures don't overwrite it back to stale data.
        self._ws_power_state: str | None = None

    async def async_load_persisted_state(self) -> None:
        """Load the last known power state from disk.

        Called during setup so that if HA restarts while the device is
        sleeping, the sensor shows 'sleep' instead of defaulting to 'on'.
        """
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            last_state = stored.get("power_state")
            if last_state and last_state != "on":
                _LOGGER.info(
                    "Restoring persisted power state: %s", last_state
                )
                self._ws_power_state = last_state

    async def _async_save_power_state(self, state: str) -> None:
        """Persist the power state to disk."""
        await self._store.async_save({"power_state": state})

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the agent via HTTP.

        If the device is unreachable (sleeping/off), preserve the
        WebSocket-pushed power state instead of letting it revert.
        """
        try:
            status = await self.api.get_status()
            games = await self.api.get_games()
            apps = await self.api.get_apps()
            sensors = await self.api.get_sensors()
            shortcuts = await self.api.get_shortcuts()
            result = {
                "status": status,
                "games": games,
                "apps": apps,
                "sensors": sensors,
                "shortcuts": shortcuts,
            }
            # Successful poll — device is online. Clear the WS override
            # and persist "on" so HA restart doesn't show stale "sleep".
            if self._ws_power_state is not None:
                self._ws_power_state = None
                self.hass.async_create_task(
                    self._async_save_power_state("on")
                )
            return result
        except Exception as err:
            # Device unreachable. If the WebSocket already pushed a power
            # state (e.g. "sleep" or "shutdown"), preserve it in the
            # existing coordinator data so entities see the correct state.
            if self._ws_power_state and self.data:
                status = dict(self.data.get("status", {}))
                status["power_state"] = self._ws_power_state
                self.data["status"] = status
            raise UpdateFailed(f"Error communicating with agent: {err}") from err

    async def async_start_websocket(self) -> None:
        """Connect to the agent WebSocket and listen for real-time events.

        Automatically reconnects with exponential backoff on disconnect.
        Runs as a background task for the lifetime of the config entry.
        """
        retry_delay = _WS_INITIAL_RETRY
        ws_url = f"ws://{self._host}:{self._port}/api/v1/ws"

        while True:
            try:
                session = aiohttp.ClientSession()
                try:
                    async with session.ws_connect(
                        ws_url,
                        heartbeat=30,
                        timeout=aiohttp.ClientWSTimeout(ws_close=10),
                        receive_timeout=120,
                    ) as ws:
                        self._ws_connected = True
                        retry_delay = _WS_INITIAL_RETRY
                        _LOGGER.info(
                            "WebSocket connected to %s", ws_url
                        )

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_ws_message(msg.data)
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break
                finally:
                    await session.close()

            except asyncio.CancelledError:
                _LOGGER.debug("WebSocket listener cancelled")
                self._ws_connected = False
                return

            except Exception as err:
                _LOGGER.debug(
                    "WebSocket connection to %s failed: %s — retrying in %ds",
                    ws_url, err, retry_delay,
                )

            self._ws_connected = False

            # Wait before reconnecting (exponential backoff)
            try:
                await asyncio.sleep(retry_delay)
            except asyncio.CancelledError:
                return
            retry_delay = min(retry_delay * 2, _WS_MAX_RETRY)

    async def _handle_ws_message(self, raw: str) -> None:
        """Process an incoming WebSocket message from the agent."""
        import json

        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.debug("WebSocket: ignoring malformed message: %s", raw[:200])
            return

        event_type = event.get("type")

        if event_type == "power_state_changed":
            data = event.get("data", {})
            new_state = data.get("power_state")
            if new_state:
                _LOGGER.info(
                    "WebSocket: power state changed → %s", new_state
                )
                self._ws_power_state = new_state
                # Persist to disk so it survives HA restarts
                self.hass.async_create_task(
                    self._async_save_power_state(new_state)
                )
                # Immediately update coordinator data so entities reflect
                # the new state without waiting for the next HTTP poll.
                if self.data:
                    status = dict(self.data.get("status", {}))
                    status["power_state"] = new_state
                    updated = dict(self.data)
                    updated["status"] = status
                    self.async_set_updated_data(updated)
                else:
                    # No data yet — create minimal data so the sensor works
                    self.async_set_updated_data({
                        "status": {"power_state": new_state},
                        "games": [],
                        "apps": [],
                        "sensors": {},
                        "shortcuts": [],
                    })
