"""Sensor entities for Boiler Room."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
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

    entities = [
        BoilerRoomCurrentGameSensor(coordinator, device_id, device_name),
        BoilerRoomGameCountSensor(coordinator, device_id, device_name),
        BoilerRoomGameListSensor(coordinator, device_id, device_name),
        BoilerRoomAppListSensor(coordinator, device_id, device_name),
        BoilerRoomCPUTempSensor(coordinator, device_id, device_name),
        BoilerRoomGPUTempSensor(coordinator, device_id, device_name),
    ]

    # Only add battery sensor if the device reports one
    if coordinator.data and coordinator.data.get("sensors", {}).get("battery_level", -1) >= 0:
        entities.append(BoilerRoomBatterySensor(coordinator, device_id, device_name))

    async_add_entities(entities, update_before_add=True)


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

    @property
    def _sensors(self) -> dict[str, Any]:
        """Get sensor data from coordinator."""
        if self.coordinator.data:
            return self.coordinator.data.get("sensors", {})
        return {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class BoilerRoomCurrentGameSensor(BoilerRoomSensorBase):
    """Sensor showing the currently active game or app."""

    _attr_name = "Current Activity"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_current_game"

    @property
    def native_value(self) -> str:
        """Return the current game/app name, or 'Idle'."""
        if self._status:
            app_name = self._status.get("current_app", "")
            if app_name:
                return app_name
        return "Idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes about the current activity."""
        if not self._status:
            return {}
        return {
            "state": self._status.get("state", "idle"),
            "app_type": self._status.get("current_app_type", "idle"),
        }


class BoilerRoomGameCountSensor(BoilerRoomSensorBase):
    """Sensor showing the number of installed games."""

    _attr_name = "Installed Games"
    _attr_icon = "mdi:controller"
    _attr_state_class = SensorStateClass.MEASUREMENT

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


class BoilerRoomCPUTempSensor(BoilerRoomSensorBase):
    """Sensor showing CPU temperature."""

    _attr_name = "CPU Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_cpu_temp"

    @property
    def native_value(self) -> float | None:
        """Return the CPU temperature."""
        val = self._sensors.get("cpu_temp", 0)
        return round(val, 1) if val else None


class BoilerRoomGPUTempSensor(BoilerRoomSensorBase):
    """Sensor showing GPU temperature."""

    _attr_name = "GPU Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_gpu_temp"

    @property
    def native_value(self) -> float | None:
        """Return the GPU temperature."""
        val = self._sensors.get("gpu_temp", 0)
        return round(val, 1) if val else None


class BoilerRoomBatterySensor(BoilerRoomSensorBase):
    """Sensor showing battery level (Steam Deck only)."""

    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_battery"

    @property
    def native_value(self) -> int | None:
        """Return the battery level."""
        val = self._sensors.get("battery_level", -1)
        return val if val >= 0 else None


class BoilerRoomGameListSensor(BoilerRoomSensorBase):
    """Sensor listing all installed Steam games."""

    _attr_name = "Game Library"
    _attr_icon = "mdi:gamepad-square"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_game_list"

    @property
    def native_value(self) -> int:
        """Return the number of installed games."""
        if self.coordinator.data:
            return len(self.coordinator.data.get("games", []))
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full game list as attributes."""
        if not self.coordinator.data:
            return {"games": []}
        games = self.coordinator.data.get("games", [])
        return {
            "games": [
                {"name": g.get("name", ""), "appid": g.get("appid", "")}
                for g in games
            ]
        }


class BoilerRoomAppListSensor(BoilerRoomSensorBase):
    """Sensor listing all installed Flatpak apps."""

    _attr_name = "App Library"
    _attr_icon = "mdi:apps"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_app_list"

    @property
    def native_value(self) -> int:
        """Return the number of installed apps."""
        if self.coordinator.data:
            return len(self.coordinator.data.get("apps", []))
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full app list as attributes."""
        if not self.coordinator.data:
            return {"apps": []}
        apps = self.coordinator.data.get("apps", [])
        return {
            "apps": [
                {"name": a.get("name", ""), "id": a.get("id", "")}
                for a in apps
            ]
        }
