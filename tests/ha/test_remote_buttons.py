"""Remote button events pushed over the WebSocket drive the chosen media player."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service

DOMAIN = "boiler_room"
RECEIVER = "media_player.receiver"


def _push(hass: HomeAssistant, entry, button: str, action: str) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator._handle_ws_message(json.dumps(
        {"type": "remote_button", "timestamp": 1, "data": {"button": button, "action": action}}
    ))


async def _setup(hass: HomeAssistant, entry, options: dict) -> None:
    """Set up the entry. Mock media_player services only after this: the
    integration's media_player platform registers the real ones."""
    hass.states.async_set(RECEIVER, "on", {"is_volume_muted": False})
    hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_volume_buttons_step_the_chosen_player(hass: HomeAssistant, entry, agent_online):
    await _setup(hass, entry, {"volume_buttons_entity": RECEIVER})
    up = async_mock_service(hass, "media_player", "volume_up")
    down = async_mock_service(hass, "media_player", "volume_down")

    _push(hass, entry, "volume_up", "press")
    _push(hass, entry, "volume_up", "repeat")  # inside the repeat interval: dropped
    _push(hass, entry, "volume_up", "release")
    _push(hass, entry, "volume_down", "press")
    await hass.async_block_till_done()

    assert [c.data["entity_id"] for c in up] == [RECEIVER]
    assert [c.data["entity_id"] for c in down] == [RECEIVER]


async def test_mute_toggles_from_the_players_state(hass: HomeAssistant, entry, agent_online):
    await _setup(hass, entry, {"volume_buttons_entity": RECEIVER})
    mute = async_mock_service(hass, "media_player", "volume_mute")

    hass.states.async_set(RECEIVER, "on", {"is_volume_muted": True})
    _push(hass, entry, "volume_mute", "press")
    await hass.async_block_till_done()
    hass.states.async_set(RECEIVER, "on", {"is_volume_muted": False})
    _push(hass, entry, "volume_mute", "press")
    await hass.async_block_till_done()

    assert [c.data["is_volume_muted"] for c in mute] == [False, True]


async def test_every_button_is_an_event_and_no_player_means_no_call(hass: HomeAssistant, entry, agent_online):
    events = async_capture_events(hass, "boiler_room_remote_button")
    await _setup(hass, entry, {})
    up = async_mock_service(hass, "media_player", "volume_up")

    _push(hass, entry, "volume_up", "press")
    _push(hass, entry, "ok", "press")
    await hass.async_block_till_done()

    assert up == []
    assert [(e.data["button"], e.data["action"], e.data["device_id"]) for e in events] == [
        ("volume_up", "press", "abc123"),
        ("ok", "press", "abc123"),
    ]


async def test_malformed_events_are_ignored(hass: HomeAssistant, entry, agent_online):
    events = async_capture_events(hass, "boiler_room_remote_button")
    await _setup(hass, entry, {"volume_buttons_entity": RECEIVER})
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    coordinator._handle_ws_message(json.dumps({"type": "remote_button", "data": {"button": "volume_up"}}))
    coordinator._handle_ws_message(json.dumps({"type": "remote_button", "data": "volume_up"}))
    await hass.async_block_till_done()

    assert events == []


async def test_option_can_be_set_and_cleared(hass: HomeAssistant, entry, agent_online):
    await _setup(hass, entry, {})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "volume_buttons_entity" in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"volume_buttons_entity": RECEIVER}
    )
    assert entry.options["volume_buttons_entity"] == RECEIVER

    # Submitting the form with the field emptied removes the option: it is a
    # suggested value, not a default that would come back.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert "volume_buttons_entity" not in entry.options
