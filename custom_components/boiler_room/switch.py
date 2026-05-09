"""Switch entities for Boiler Room (session mode toggle)."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Boiler Room switch entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    coordinator = data["coordinator"]

    device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)
    device_name = entry.data.get(CONF_DEVICE_NAME, "SteamOS Device")

    async_add_entities([
        BoilerRoomGamingModeSwitch(api, coordinator, device_id, device_name),
    ])


class BoilerRoomGamingModeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle between Gaming Mode (on) and Desktop Mode (off)."""

    _attr_has_entity_name = True
    _attr_name = "Gaming Mode"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, api, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the gaming mode switch."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_gaming_mode"

    @property
    def device_info(self):
        """Return device information."""
        return {"identifiers": {(DOMAIN, self._device_id)}}

    @property
    def is_on(self) -> bool:
        """Return True if in Gaming Mode."""
        if self.coordinator.data:
            status = self.coordinator.data.get("status", {})
            return status.get("gaming_mode", False)
        return False

    async def async_turn_on(self, **kwargs) -> None:
        """Switch to Gaming Mode."""
        _LOGGER.info("Switching to Gaming Mode")
        await self._api.set_session_mode("gaming")

    async def async_turn_off(self, **kwargs) -> None:
        """Switch to Desktop Mode."""
        _LOGGER.info("Switching to Desktop Mode")
        await self._api.set_session_mode("desktop")
