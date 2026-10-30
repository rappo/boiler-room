"""Power state persistence across HA restarts (the 2026-10-29 review bug)."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

DOMAIN = "boiler_room"

POWER_SENSOR = "sensor.deck_power_state"


def _store_key(entry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.power_state"


def _stored(hass_storage, key, state):
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"power_state": state}}


async def test_restored_sleep_shows_while_device_unreachable(hass: HomeAssistant, hass_storage, entry, agent_offline):
    """HA restarts while the machine sleeps: every poll fails, sensor must still say sleep."""
    _stored(hass_storage, _store_key(entry), "sleep")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(POWER_SENSOR)
    assert state is not None
    assert state.state == "sleep"
    # Other coordinator entities are unavailable because the device is down.
    assert hass.states.get("sensor.deck_installed_games").state == "unavailable"


async def test_no_store_and_unreachable_is_unknown(hass: HomeAssistant, entry, agent_offline):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(POWER_SENSOR).state == "unknown"


async def test_legacy_shared_store_is_migrated(hass: HomeAssistant, hass_storage, entry, agent_offline):
    """Pre-2026.10.29 installs had one store for every device."""
    _stored(hass_storage, f"{DOMAIN}.power_state", "shutdown")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(POWER_SENSOR).state == "shutdown"
    assert f"{DOMAIN}.power_state" not in hass_storage


async def test_successful_poll_persists_agent_state(hass: HomeAssistant, hass_storage, entry, agent_online):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(POWER_SENSOR).state == "on"
    assert hass_storage[_store_key(entry)]["data"] == {"power_state": "on"}


async def test_pushed_event_updates_sensor_and_store(hass: HomeAssistant, hass_storage, entry, agent_online):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator._handle_ws_message(json.dumps({"type": "power_state_changed", "data": {"power_state": "sleep"}}))
    await hass.async_block_till_done()

    assert hass.states.get(POWER_SENSOR).state == "sleep"
    assert hass_storage[_store_key(entry)]["data"] == {"power_state": "sleep"}
    # Garbage is ignored.
    coordinator._handle_ws_message("not json")
    coordinator._handle_ws_message(json.dumps(["list"]))
    assert hass.states.get(POWER_SENSOR).state == "sleep"


async def test_unload_cleans_up(hass: HomeAssistant, entry, agent_online):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
