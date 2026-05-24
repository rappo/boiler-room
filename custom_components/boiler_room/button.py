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

    # Grab the MAC from the coordinator's initial data (if available)
    initial_mac = None
    if coordinator.data:
        status = coordinator.data.get("status", {})
        initial_mac = status.get("mac_address")

    # Store MAC in config entry data for persistence across restarts
    if initial_mac and "mac_address" not in entry.data:
        new_data = dict(entry.data)
        new_data["mac_address"] = initial_mac
        hass.config_entries.async_update_entry(entry, data=new_data)

    # Use stored MAC as fallback
    stored_mac = entry.data.get("mac_address", initial_mac)

    entities = [
        BoilerRoomPowerButton(api, device_id, device_name, "Suspend", "suspend", "mdi:power-sleep"),
        BoilerRoomPowerButton(api, device_id, device_name, "Shutdown", "shutdown", "mdi:power"),
        BoilerRoomPowerButton(api, device_id, device_name, "Reboot", "reboot", "mdi:restart"),
        BoilerRoomRestartSteamButton(api, device_id, device_name),
        BoilerRoomWakeButton(coordinator, entry, device_id, device_name, stored_mac),
        BoilerRoomCreateAutomationsButton(device_id, device_name),
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


class BoilerRoomRestartSteamButton(ButtonEntity):
    """Restart the Steam client UI (useful when gamescope freezes after a flatpak exit)."""

    _attr_has_entity_name = True
    _attr_name = "Restart Steam UI"
    _attr_icon = "mdi:steam"

    def __init__(self, api, device_id: str, device_name: str) -> None:
        """Initialize the restart Steam button."""
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_restart_steam"

    @property
    def device_info(self):
        """Return device information."""
        return {"identifiers": {(DOMAIN, self._device_id)}}

    async def async_press(self) -> None:
        """Restart the Steam client."""
        _LOGGER.info("Restarting Steam client UI")
        try:
            await self._api.restart_steam()
        except Exception:
            _LOGGER.warning("restart_steam API call failed, trying power_action fallback")
            try:
                await self._api.power_action("restart_steam")
            except Exception:
                _LOGGER.error("Failed to restart Steam client")


class BoilerRoomWakeButton(ButtonEntity):
    """Wake-on-LAN button to power on the SteamOS device.

    This does NOT extend CoordinatorEntity so it stays available
    even when the device is offline/suspended.
    """

    _attr_has_entity_name = True
    _attr_name = "Wake (WoL)"
    _attr_icon = "mdi:power-on"
    _attr_available = True  # Always available — WoL works when device is off

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        initial_mac: str | None,
    ) -> None:
        """Initialize the WoL button."""
        self._coordinator = coordinator
        self._entry = entry
        self._device_id = device_id
        self._mac = initial_mac
        self._attr_unique_id = f"{device_id}_wake_on_lan"

    @property
    def device_info(self):
        """Return device information."""
        return {"identifiers": {(DOMAIN, self._device_id)}}

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {"mac_address": self._mac or "unknown"}

    def _update_mac(self) -> None:
        """Update MAC from coordinator if available (device came back online)."""
        if self._coordinator.data:
            status = self._coordinator.data.get("status", {})
            new_mac = status.get("mac_address")
            if new_mac and new_mac != self._mac:
                self._mac = new_mac
                # Persist for next restart
                new_data = dict(self._entry.data)
                new_data["mac_address"] = new_mac
                self.hass.config_entries.async_update_entry(
                    self._entry, data=new_data
                )

    async def async_press(self) -> None:
        """Send a Wake-on-LAN magic packet."""
        self._update_mac()
        mac = self._mac
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


class BoilerRoomCreateAutomationsButton(ButtonEntity):
    """Button that creates the Boiler Room voice automations.

    Writes pre-built automations to automations.yaml so they appear
    in the HA UI as fully editable, standalone automations.
    """

    _attr_has_entity_name = True
    _attr_name = "Create Voice Automations"
    _attr_icon = "mdi:microphone-message"

    def __init__(self, device_id: str, device_name: str) -> None:
        """Initialize the button."""
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_create_voice_automations"

    @property
    def device_info(self):
        """Return device information."""
        return {"identifiers": {(DOMAIN, self._device_id)}}

    async def async_press(self) -> None:
        """Create the voice automations."""
        from .automations import async_create_voice_automations

        added = await async_create_voice_automations(self.hass)
        if added > 0:
            _LOGGER.info("Created %d voice automations", added)
        else:
            _LOGGER.info("Voice automations already exist")
