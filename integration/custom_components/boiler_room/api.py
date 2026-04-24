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
        self, target: str | None = None, appid: str | None = None
    ) -> dict[str, Any]:
        """Launch a game by name or AppID."""
        session = await self._get_session()
        payload: dict[str, str] = {"type": "game"}
        if appid:
            payload["appid"] = appid
        elif target:
            payload["target"] = target
        else:
            raise ValueError("Must provide target or appid")

        async with session.post(f"{self.base_url}/launch", json=payload) as resp:
            return await resp.json()

    async def test_connection(self) -> bool:
        """Test if the agent is reachable."""
        try:
            await self.get_status()
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return False
