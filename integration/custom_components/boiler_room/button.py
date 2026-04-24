"""Button entities for Boiler Room (power controls)."""

from __future__ import annotations

import logging
import socket
import struct

from homeassistant.components.button import ButtonEntity
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
    """Set up Boiler Room button entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    coordinator = data["coordinator"]

    device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)
    device_name = entry.data.get(CONF_DEVICE_NAME, "SteamOS Device")

    entities = [
        BoilerRoomPowerButton(api, device_id, device_name, "Suspend", "suspend", "mdi:power-sleep"),
        BoilerRoomPowerButton(api, device_id, device_name, "Shutdown", "shutdown", "mdi:power"),
        BoilerRoomPowerButton(api, device_id, device_name, "Reboot", "reboot", "mdi:restart"),
        BoilerRoomWakeButton(coordinator, device_id, device_name),
    ]

    async_add_entities(entities)


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


class BoilerRoomWakeButton(CoordinatorEntity, ButtonEntity):
    """Wake-on-LAN button to power on the SteamOS device."""

    _attr_has_entity_name = True
    _attr_name = "Wake (WoL)"
    _attr_icon = "mdi:power-on"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        """Initialize the WoL button."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_wake_on_lan"

    @property
    def device_info(self):
        """Return device information."""
        return {"identifiers": {(DOMAIN, self._device_id)}}

    @property
    def _mac_address(self) -> str | None:
        """Get the MAC address from the last known status."""
        if self.coordinator.data:
            status = self.coordinator.data.get("status", {})
            return status.get("mac_address")
        return None

    async def async_press(self) -> None:
        """Send a Wake-on-LAN magic packet."""
        mac = self._mac_address
        if not mac:
            _LOGGER.error("Cannot send WoL: no MAC address known")
            return

        _LOGGER.info("Sending Wake-on-LAN to %s", mac)
        await self.hass.async_add_executor_job(self._send_magic_packet, mac)

    @staticmethod
    def _send_magic_packet(mac: str) -> None:
        """Send a WoL magic packet to the given MAC address."""
        # Normalize MAC
        mac_clean = mac.replace(":", "").replace("-", "")
        if len(mac_clean) != 12:
            raise ValueError(f"Invalid MAC address: {mac}")

        # Build magic packet: 6x 0xFF + 16x MAC
        mac_bytes = bytes.fromhex(mac_clean)
        packet = b"\xff" * 6 + mac_bytes * 16

        # Send via UDP broadcast
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, ("255.255.255.255", 9))
            _LOGGER.info("WoL magic packet sent to %s", mac)

