"""Config flow for Boiler Room integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import BoilerRoomAPI
from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_JELLYFIN_URL = "jellyfin_url"
CONF_JELLYFIN_API_KEY = "jellyfin_api_key"


class BoilerRoomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Boiler Room."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str = ""
        self._port: int = DEFAULT_PORT
        self._device_name: str = "SteamOS Device"
        self._device_id: str = ""
        self._game_count: int = 0
        self._app_count: int = 0

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return BoilerRoomOptionsFlow()

    # ─── Step 1: Connect to agent ───

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle setup — connect to an already-running agent."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input.get(CONF_PORT, DEFAULT_PORT)

            api = BoilerRoomAPI(self._host, self._port)
            try:
                status = await api.get_status()
                self._device_id = status.get("device_id", "")
                self._device_name = status.get("device_name", "SteamOS Device")
                self._game_count = status.get("game_count", 0)
                self._app_count = status.get("app_count", 0)
                await api.close()

                if not self._device_id:
                    return self.async_abort(reason="missing_unique_id")

                await self.async_set_unique_id(self._device_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: self._host}
                )

                return await self.async_step_confirm()
            except Exception:
                _LOGGER.exception("Failed to connect to Boiler Room agent")
                errors["base"] = "cannot_connect"
            finally:
                await api.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    # ─── Zeroconf Discovery ───

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery of a Boiler Room agent."""
        _LOGGER.info(
            "Discovered Boiler Room agent at %s:%s",
            discovery_info.host,
            discovery_info.port,
        )

        properties = discovery_info.properties
        self._device_id = properties.get("device_id", "")
        self._device_name = properties.get("device_name", "SteamOS Device")
        self._host = str(discovery_info.host)
        self._port = discovery_info.port or DEFAULT_PORT

        if not self._device_id:
            return self.async_abort(reason="missing_unique_id")

        await self.async_set_unique_id(self._device_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: self._host}
        )

        # Test connection and get game count
        api = BoilerRoomAPI(self._host, self._port)
        try:
            status = await api.get_status()
            self._game_count = status.get("game_count", 0)
            self._app_count = status.get("app_count", 0)
        except Exception:
            _LOGGER.warning("Could not connect to discovered agent at %s", self._host)
            return self.async_abort(reason="cannot_connect")
        finally:
            await api.close()

        self.context["title_placeholders"] = {"name": self._device_name}
        return await self.async_step_confirm()

    # ─── Confirm ───

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm device addition."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._device_name,
                data={
                    CONF_HOST: self._host,
                    CONF_PORT: self._port,
                    CONF_DEVICE_NAME: self._device_name,
                    CONF_DEVICE_ID: self._device_id,
                },
            )

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._device_name,
                "host": self._host,
                "port": str(self._port),
                "game_count": str(self._game_count),
                "app_count": str(self._app_count),
            },
        )


class BoilerRoomOptionsFlow(OptionsFlow):
    """Handle options for Boiler Room (Jellyfin config, etc.)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate Jellyfin connection if URL provided
            jf_url = user_input.get(CONF_JELLYFIN_URL, "").strip()
            jf_key = user_input.get(CONF_JELLYFIN_API_KEY, "").strip()

            if jf_url and jf_key:
                import aiohttp
                try:
                    async with aiohttp.ClientSession() as session:
                        headers = {"Authorization": f'MediaBrowser Token="{jf_key}"'}
                        async with session.get(
                            f"{jf_url.rstrip('/')}/System/Info",
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=5),
                        ) as resp:
                            if resp.status != 200:
                                errors["base"] = "jellyfin_auth_failed"
                except Exception:
                    errors["base"] = "jellyfin_connect_failed"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_JELLYFIN_URL,
                        default=current.get(CONF_JELLYFIN_URL, ""),
                    ): str,
                    vol.Optional(
                        CONF_JELLYFIN_API_KEY,
                        default=current.get(CONF_JELLYFIN_API_KEY, ""),
                    ): str,
                }
            ),
            errors=errors,
        )
