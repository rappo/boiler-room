"""Button entities for Boiler Room (power controls)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Boiler Room button entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]

    device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)
    device_name = entry.data.get(CONF_DEVICE_NAME, "SteamOS Device")

    async_add_entities(
        [
            BoilerRoomPowerButton(api, device_id, device_name, "Suspend", "suspend", "mdi:power-sleep"),
            BoilerRoomPowerButton(api, device_id, device_name, "Shutdown", "shutdown", "mdi:power"),
            BoilerRoomPowerButton(api, device_id, device_name, "Reboot", "reboot", "mdi:restart"),
        ]
    )


class BoilerRoomPowerButton(ButtonEntity):
    """Power control button for SteamOS device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        api,
        device_id: str,
        device_name: str,
        name: str,
        action: str,
        icon: str,
    ) -> None:
        """Initialize the power button."""
        self._api = api
        self._device_id = device_id
        self._action = action
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{device_id}_{action}"

    @property
    def device_info(self):
        """Return device information."""
        return {"identifiers": {(DOMAIN, self._device_id)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Power action: %s", self._action)
        await self._api.power_action(self._action)
