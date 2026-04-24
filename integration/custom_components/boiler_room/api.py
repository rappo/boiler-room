"""API client for communicating with the Boiler Room agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class BoilerRoomAPI:
    """Async HTTP client for the Boiler Room agent REST API."""

    def __init__(self, host: str, port: int) -> None:
        """Initialize the API client."""
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/api/v1"
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── Phase 1: Core ───

    async def get_status(self) -> dict[str, Any]:
        """Get the agent status."""
        session = await self._get_session()
        async with session.get(f"{self.base_url}/status") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_games(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Get the list of installed games."""
        session = await self._get_session()
        params = {"refresh": "true"} if refresh else {}
        async with session.get(f"{self.base_url}/games", params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def launch(
        self,
        target: str | None = None,
        appid: str | None = None,
        launch_type: str = "game",
        url: str | None = None,
    ) -> dict[str, Any]:
        """Launch a game, app, or URL."""
        session = await self._get_session()
        payload: dict[str, str] = {"type": launch_type}
        if appid:
            payload["appid"] = appid
        elif target:
            payload["target"] = target
        elif url:
            payload["url"] = url
        else:
            raise ValueError("Must provide target, appid, or url")

        async with session.post(f"{self.base_url}/launch", json=payload) as resp:
            return await resp.json()

    async def test_connection(self) -> bool:
        """Test if the agent is reachable."""
        try:
            await self.get_status()
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return False

    # ─── Phase 2: Apps & Shortcuts ───

    async def get_apps(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Get the list of installed Flatpak apps."""
        session = await self._get_session()
        params = {"refresh": "true"} if refresh else {}
        async with session.get(f"{self.base_url}/apps", params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_shortcuts(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Get the list of Non-Steam game shortcuts."""
        session = await self._get_session()
        params = {"refresh": "true"} if refresh else {}
        async with session.get(f"{self.base_url}/shortcuts", params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ─── Phase 2: System ───

    async def get_sensors(self) -> dict[str, Any]:
        """Get system sensor data (CPU temp, GPU temp, battery, volume)."""
        session = await self._get_session()
        async with session.get(f"{self.base_url}/system/sensors") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def set_volume(self, level: int) -> dict[str, Any]:
        """Set system volume (0-100)."""
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}/system/volume", json={"level": level}
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def power_action(self, action: str) -> dict[str, Any]:
        """Execute a power action: suspend, shutdown, or reboot."""
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}/system/power", json={"action": action}
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ─── Phase 2: Plugins ───

    async def get_plugins(self) -> list[dict[str, Any]]:
        """Get the list of registered plugins."""
        session = await self._get_session()
        async with session.get(f"{self.base_url}/plugins") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def plugin_action(
        self, plugin_name: str, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a plugin action."""
        session = await self._get_session()
        payload = {"action": action, "params": params or {}}
        async with session.post(
            f"{self.base_url}/plugins/{plugin_name}/action", json=payload
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ─── Phase 2: Artwork ───

    def get_artwork_url(self, appid: str, art_type: str = "grid") -> str:
        """Return the URL for a game's artwork image."""
        return f"{self.base_url}/games/{appid}/artwork/{art_type}"
