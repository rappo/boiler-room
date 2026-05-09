"""Media player entity for Boiler Room."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
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
    """Set up Boiler Room media player from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    async_add_entities(
        [BoilerRoomMediaPlayer(coordinator, api, entry)],
        update_before_add=True,
    )


class BoilerRoomMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of a SteamOS device as a media player."""

    _attr_has_entity_name = True
    _attr_name = None  # Uses device name as entity name
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
    )

    def __init__(self, coordinator, api, entry: ConfigEntry) -> None:
        """Initialize the media player."""
        super().__init__(coordinator)
        self._api = api
        self._entry = entry
        self._device_name = entry.data.get(CONF_DEVICE_NAME, "SteamOS Device")
        self._device_id = entry.data.get(CONF_DEVICE_ID, entry.entry_id)

        self._attr_unique_id = f"{self._device_id}_media_player"

    @property
    def device_info(self):
        """Return device information."""
        status = self._status
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Valve",
            "model": "SteamOS Device",
            "sw_version": status.get("version", "unknown") if status else "unknown",
            "configuration_url": f"http://{self._entry.data['host']}:{self._entry.data['port']}",
        }

    @property
    def _status(self) -> dict[str, Any] | None:
        """Get the current status from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get("status")
        return None

    @property
    def _games(self) -> list[dict[str, Any]]:
        """Get the game list from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get("games", [])
        return []

    @property
    def _apps(self) -> list[dict[str, Any]]:
        """Get the app list from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get("apps", [])
        return []

    @property
    def _shortcuts(self) -> list[dict[str, Any]]:
        """Get Non-Steam shortcuts from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get("shortcuts", [])
        return []

    @property
    def _sensors(self) -> dict[str, Any]:
        """Get sensor data."""
        if self.coordinator.data:
            return self.coordinator.data.get("sensors", {})
        return {}

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the media player."""
        if not self._status:
            return MediaPlayerState.OFF

        state = self._status.get("state", "idle")
        if state == "playing":
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        """Return the title of the currently playing game."""
        if self._status and self._status.get("state") == "playing":
            return self._status.get("current_app")
        return None

    @property
    def volume_level(self) -> float | None:
        """Return the volume level (0.0 to 1.0)."""
        vol = self._sensors.get("volume")
        if vol is not None:
            return vol / 100.0
        return None

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level (0.0 to 1.0)."""
        await self._api.set_volume(int(volume * 100))
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}
        if self._status:
            attrs["gaming_mode"] = self._status.get("gaming_mode", False)
            attrs["game_count"] = self._status.get("game_count", 0)
            attrs["app_count"] = self._status.get("app_count", 0)
            attrs["shortcut_count"] = self._status.get("shortcut_count", 0)
            attrs["plugin_count"] = self._status.get("plugin_count", 0)
            attrs["mac_address"] = self._status.get("mac_address", "")
            attrs["ip_address"] = self._status.get("ip_address", "")
            attrs["uptime_seconds"] = self._status.get("uptime_seconds", 0)
        return attrs

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Launch a game or app."""
        _LOGGER.info("Launching: type=%s, id=%s", media_type, media_id)

        if media_type == "app":
            result = await self._api.launch(appid=media_id, launch_type="app")
        else:
            # Default: game launch
            result = await self._api.launch(appid=media_id)

        if result.get("status") == "error":
            _LOGGER.error("Failed to launch: %s", result.get("message"))
        else:
            launched = result.get("game") or result.get("app") or {}
            _LOGGER.info("Launched: %s", launched.get("name", media_id))

        await self.coordinator.async_request_refresh()

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Show the game/app library in HA's media browser."""

        # Sub-folder: Games
        if media_content_id == "games":
            children = []
            for game in self._games:
                appid = game["appid"]
                thumbnail = self._api.get_artwork_url(appid, "grid")
                children.append(
                    BrowseMedia(
                        title=game["name"],
                        media_class="game",
                        media_content_type="game",
                        media_content_id=appid,
                        can_play=True,
                        can_expand=False,
                        thumbnail=thumbnail,
                    )
                )
            return BrowseMedia(
                title="Steam Games",
                media_class="directory",
                media_content_type="library",
                media_content_id="games",
                can_play=False,
                can_expand=True,
                children=children,
                children_media_class="game",
            )

        # Sub-folder: Non-Steam Shortcuts
        if media_content_id == "shortcuts":
            children = []
            for shortcut in self._shortcuts:
                children.append(
                    BrowseMedia(
                        title=shortcut["name"],
                        media_class="game",
                        media_content_type="game",
                        media_content_id=shortcut.get("appid", ""),
                        can_play=True,
                        can_expand=False,
                    )
                )
            return BrowseMedia(
                title="Non-Steam Games",
                media_class="directory",
                media_content_type="library",
                media_content_id="shortcuts",
                can_play=False,
                can_expand=True,
                children=children,
                children_media_class="game",
            )

        # Sub-folder: Apps
        if media_content_id == "apps":
            children = []
            for app in self._apps:
                children.append(
                    BrowseMedia(
                        title=app["name"],
                        media_class="app",
                        media_content_type="app",
                        media_content_id=app["id"],
                        can_play=True,
                        can_expand=False,
                    )
                )
            return BrowseMedia(
                title="Apps",
                media_class="directory",
                media_content_type="library",
                media_content_id="apps",
                can_play=False,
                can_expand=True,
                children=children,
                children_media_class="app",
            )

        # Root — show categories
        children = [
            BrowseMedia(
                title=f"Steam Games ({len(self._games)})",
                media_class="directory",
                media_content_type="library",
                media_content_id="games",
                can_play=False,
                can_expand=True,
                children_media_class="game",
            ),
        ]

        if self._shortcuts:
            children.append(
                BrowseMedia(
                    title=f"Non-Steam Games ({len(self._shortcuts)})",
                    media_class="directory",
                    media_content_type="library",
                    media_content_id="shortcuts",
                    can_play=False,
                    can_expand=True,
                    children_media_class="game",
                )
            )

        if self._apps:
            children.append(
                BrowseMedia(
                    title=f"Apps ({len(self._apps)})",
                    media_class="directory",
                    media_content_type="library",
                    media_content_id="apps",
                    can_play=False,
                    can_expand=True,
                    children_media_class="app",
                )
            )

        return BrowseMedia(
            title="Boiler Room",
            media_class="directory",
            media_content_type="library",
            media_content_id="root",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def async_turn_off(self) -> None:
        """Suspend the SteamOS device."""
        _LOGGER.info("Suspending SteamOS device")
        await self._api.power_action("suspend")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
