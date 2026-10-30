"""Fixtures for the Home Assistant harness tests.

These need `pytest-homeassistant-custom-component` (which pins a Home
Assistant release) and are slower than the unit tests in tests/, so they
live in their own directory and run with `pytest tests/ha`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import custom_components
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

# Under pytest the harness's own testing_config/custom_components package is
# already imported as `custom_components`, and a regular package shadows this
# repo's namespace package. Extend its search path (what pkgutil.extend_path
# would do) so both `import custom_components.boiler_room` and HA's loader,
# which walks custom_components.__path__, find the integration in this repo.
_REPO_COMPONENTS = str(Path(__file__).resolve().parents[2] / "custom_components")
if _REPO_COMPONENTS not in custom_components.__path__:
    custom_components.__path__.append(_REPO_COMPONENTS)

DOMAIN = "boiler_room"
ENTRY_DATA = {"host": "192.0.2.10", "port": 9451, "device_name": "deck", "device_id": "abc123"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let the harness load custom_components/boiler_room."""
    yield


@pytest.fixture(autouse=True)
def no_websocket():
    """Keep the WebSocket listener from dialing a fake host during tests."""
    async def _idle(self):
        return None

    with patch(
        "custom_components.boiler_room.BoilerRoomCoordinator.async_start_websocket",
        _idle,
    ):
        yield


@pytest.fixture
def entry(hass):
    """A config entry for a device at a test-net address."""
    e = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=ENTRY_DATA["device_id"], title="deck")
    e.add_to_hass(hass)
    return e


@pytest.fixture
def agent_offline():
    """Every agent call fails as if the machine were asleep."""
    with patch("custom_components.boiler_room.BoilerRoomAPI.get_status", AsyncMock(side_effect=aiohttp.ClientError("down"))):
        yield


@pytest.fixture
def agent_online():
    """Agent answers with a minimal healthy payload."""
    status = {"power_state": "on", "state": "idle", "device_id": "abc123", "version": "t", "game_count": 1}
    patches = [
        patch("custom_components.boiler_room.BoilerRoomAPI.get_status", AsyncMock(return_value=status)),
        patch("custom_components.boiler_room.BoilerRoomAPI.get_games", AsyncMock(return_value=[{"appid": "1", "name": "Balatro"}])),
        patch("custom_components.boiler_room.BoilerRoomAPI.get_apps", AsyncMock(return_value=[])),
        patch("custom_components.boiler_room.BoilerRoomAPI.get_sensors", AsyncMock(return_value={"cpu_temp": 50.0, "battery_level": -1})),
        patch("custom_components.boiler_room.BoilerRoomAPI.get_shortcuts", AsyncMock(return_value=[])),
        patch("custom_components.boiler_room.BoilerRoomAPI.get_users", AsyncMock(return_value={})),
    ]
    for p in patches:
        p.start()
    yield status
    for p in patches:
        p.stop()
