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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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

    return unload_ok


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
            return {
                "status": status,
                "games": games,
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with agent: {err}") from err
