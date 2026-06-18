"""Select entity for Boiler Room (quick-launch dropdown)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
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
    """Set up Boiler Room select entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)
    device_name = entry.data.get(CONF_DEVICE_NAME, "SteamOS Device")

    async_add_entities(
        [
            BoilerRoomQuickLaunchSelect(coordinator, api, device_id, device_name),
        ],
        update_before_add=True,
    )


class BoilerRoomQuickLaunchSelect(CoordinatorEntity, SelectEntity):
    """Dropdown select entity for quickly launching a game."""

    _attr_has_entity_name = True
    _attr_name = "Quick Launch"
    _attr_icon = "mdi:rocket-launch"
    _attr_current_option = None

    def __init__(self, coordinator, api, device_id: str, device_name: str) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_quick_launch"
        self._game_map: dict[str, str] = {}  # name → appid

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
        }

    @property
    def options(self) -> list[str]:
        """Return the list of game/app names as select options."""
        self._game_map = {}
        names = []

        if self.coordinator.data:
            # Steam games
            for game in self.coordinator.data.get("games", []):
                name = game.get("name", "")
                appid = game.get("appid", "")
                if name and appid:
                    self._game_map[name] = ("game", appid)
                    names.append(name)

            # Flatpak apps
            for app in self.coordinator.data.get("apps", []):
                name = app.get("name", "")
                app_id = app.get("id", "")
                if name and app_id:
                    label = f"[App] {name}"
                    self._game_map[label] = ("app", app_id)
                    names.append(label)

            # Non-Steam shortcuts
            for shortcut in self.coordinator.data.get("shortcuts", []):
                name = shortcut.get("name", "")
                appid = shortcut.get("appid", "")
                if name and appid:
                    label = f"[Shortcut] {name}"
                    self._game_map[label] = ("game", appid)
                    names.append(label)

        return names if names else ["No games found"]

    async def async_select_option(self, option: str) -> None:
        """Handle selecting a game/app to launch."""
        entry = self._game_map.get(option)
        if not entry:
            _LOGGER.warning("Selected item '%s' not found in map", option)
            return

        launch_type, target_id = entry
        _LOGGER.info("Quick-launching: %s (type=%s, id=%s)", option, launch_type, target_id)
        result = await self._api.launch(appid=target_id, launch_type=launch_type)

        if result.get("status") == "error":
            _LOGGER.error("Quick launch failed: %s", result.get("message"))
        else:
            _LOGGER.info("Quick launch successful: %s", option)

        self._attr_current_option = option
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
