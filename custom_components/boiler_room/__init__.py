"""The Boiler Room integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoilerRoomAPI
from .const import CONF_HOST, CONF_PORT, DOMAIN, PLATFORMS, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type BoilerRoomConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: BoilerRoomConfigEntry
) -> bool:
    """Set up Boiler Room from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    api = BoilerRoomAPI(host, port)

    coordinator = BoilerRoomCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

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
    """Coordinator to fetch data from the Boiler Room agent."""

    def __init__(self, hass: HomeAssistant, api: BoilerRoomAPI) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the agent."""
        try:
            status = await self.api.get_status()
            games = await self.api.get_games()
            apps = await self.api.get_apps()
            sensors = await self.api.get_sensors()
            shortcuts = await self.api.get_shortcuts()
            return {
                "status": status,
                "games": games,
                "apps": apps,
                "sensors": sensors,
                "shortcuts": shortcuts,
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with agent: {err}") from err
