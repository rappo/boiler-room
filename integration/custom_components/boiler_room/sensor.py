"""Sensor entities for Boiler Room."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Boiler Room sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)
    device_name = entry.data.get(CONF_DEVICE_NAME, "SteamOS Device")

    async_add_entities(
        [
            BoilerRoomCurrentGameSensor(coordinator, device_id, device_name),
            BoilerRoomGameCountSensor(coordinator, device_id, device_name),
        ],
        update_before_add=True,
    )


class BoilerRoomSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Boiler Room sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name

    @property
    def device_info(self):
        """Return device information — ties sensors to the same device as the media player."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
        }

    @property
    def _status(self) -> dict[str, Any] | None:
        """Get the current status from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get("status")
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class BoilerRoomCurrentGameSensor(BoilerRoomSensorBase):
    """Sensor showing the currently running game."""

    _attr_name = "Current Game"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_current_game"

    @property
    def native_value(self) -> str:
        """Return the current game name, or 'Idle'."""
        if self._status and self._status.get("state") == "playing":
            return self._status.get("current_app", "Unknown")
        return "Idle"


class BoilerRoomGameCountSensor(BoilerRoomSensorBase):
    """Sensor showing the number of installed games."""

    _attr_name = "Installed Games"
    _attr_icon = "mdi:controller"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_game_count"

    @property
    def native_value(self) -> int:
        """Return the count of installed games."""
        if self._status:
            return self._status.get("game_count", 0)
        return 0
