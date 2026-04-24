"""Number entities for Boiler Room (volume control)."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up Boiler Room number entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)
    device_name = entry.data.get(CONF_DEVICE_NAME, "SteamOS Device")

    async_add_entities(
        [BoilerRoomVolumeNumber(coordinator, api, device_id, device_name)],
        update_before_add=True,
    )


class BoilerRoomVolumeNumber(CoordinatorEntity, NumberEntity):
    """Volume control for SteamOS device."""

    _attr_has_entity_name = True
    _attr_name = "Volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, api, device_id: str, device_name: str) -> None:
        """Initialize the volume control."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_volume"

    @property
    def device_info(self):
        """Return device information."""
        return {"identifiers": {(DOMAIN, self._device_id)}}

    @property
    def native_value(self) -> float | None:
        """Return the current volume."""
        if self.coordinator.data and "sensors" in self.coordinator.data:
            return self.coordinator.data["sensors"].get("volume")
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        await self._api.set_volume(int(value))
        await self.coordinator.async_request_refresh()
