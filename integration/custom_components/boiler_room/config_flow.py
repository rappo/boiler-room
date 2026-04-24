"""Config flow for Boiler Room integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
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
from .ssh_install import install_via_ssh

_LOGGER = logging.getLogger(__name__)

CONF_SSH_USERNAME = "ssh_username"
CONF_SSH_PASSWORD = "ssh_password"
CONF_SSH_PORT = "ssh_port"


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
        self._ssh_username: str = "deck"
        self._ssh_password: str = ""

    # ─── Step 1: Choose setup method ───

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — choose setup method."""
        if user_input is not None:
            method = user_input.get("method", "manual")
            if method == "ssh_install":
                return await self.async_step_ssh_credentials()
            elif method == "manual":
                return await self.async_step_manual()
            # "auto" — just wait for zeroconf (no action needed)
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("method", default="ssh_install"): vol.In(
                        {
                            "ssh_install": "Install agent on SteamOS via SSH",
                            "manual": "Connect to existing agent (manual IP)",
                        }
                    ),
                }
            ),
        )

    # ─── SSH Install Path ───

    async def async_step_ssh_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect SSH credentials for remote installation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._ssh_username = user_input.get(CONF_SSH_USERNAME, "deck")
            self._ssh_password = user_input.get(CONF_SSH_PASSWORD, "")

            # Proceed to install
            return await self.async_step_ssh_install()

        return self.async_show_form(
            step_id="ssh_credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_SSH_USERNAME, default="deck"): str,
                    vol.Optional(CONF_SSH_PASSWORD, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_ssh_install(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Execute the SSH installation."""
        errors: dict[str, str] = {}

        # Run the install
        result = await install_via_ssh(
            host=self._host,
            username=self._ssh_username,
            password=self._ssh_password if self._ssh_password else None,
        )

        if not result["success"]:
            _LOGGER.error("SSH install failed: %s", result["message"])
            _LOGGER.error("SSH install output: %s", result.get("output", ""))
            errors["base"] = "ssh_install_failed"
            detail = result["message"]
            if result.get("output"):
                detail += f"\n\nOutput:\n```\n{result['output'][-500:]}\n```"
            return self.async_show_form(
                step_id="ssh_credentials",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST, default=self._host): str,
                        vol.Optional(CONF_SSH_USERNAME, default=self._ssh_username): str,
                        vol.Optional(CONF_SSH_PASSWORD, default=""): str,
                    }
                ),
                errors=errors,
                description_placeholders={
                    "error_detail": detail,
                },
            )

        # Install succeeded — wait for the agent API to come online
        _LOGGER.info("Agent installed, waiting for API to come online...")
        self._port = DEFAULT_PORT
        api = BoilerRoomAPI(self._host, self._port)

        for attempt in range(15):
            _LOGGER.debug("Checking agent API (attempt %d/15)...", attempt + 1)
            if await api.test_connection():
                break
            await asyncio.sleep(2)
        else:
            await api.close()
            errors["base"] = "agent_not_responding"
            return self.async_show_form(
                step_id="ssh_credentials",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST, default=self._host): str,
                        vol.Optional(CONF_SSH_USERNAME, default=self._ssh_username): str,
                        vol.Optional(CONF_SSH_PASSWORD, default=""): str,
                    }
                ),
                errors=errors,
            )

        # Agent is online — fetch status
        try:
            status = await api.get_status()
            self._device_id = status.get("device_id", "")
            self._device_name = status.get("device_name", "SteamOS Device")
            self._game_count = status.get("game_count", 0)
            self._app_count = status.get("app_count", 0)
        except Exception:
            _LOGGER.exception("Failed to get agent status after install")
        finally:
            await api.close()

        if self._device_id:
            await self.async_set_unique_id(self._device_id)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host}
            )

        return await self.async_step_confirm()

    # ─── Manual Setup Path ───

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup by the user."""
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
            step_id="manual",
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
