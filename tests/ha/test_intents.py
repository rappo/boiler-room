"""Intents: the one code path behind the voice sentences and the LLM tools.

Every action is driven through ``intent.async_handle`` the way the LLM
tools and the sentence lane do, with the agent API mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from conftest import ENTRY_DATA
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "boiler_room"
API = "custom_components.boiler_room.BoilerRoomAPI"
JELLYFIN = "custom_components.boiler_room.services.jellyfin"
SECOND_ENTRY = {"host": "192.0.2.11", "port": 9451, "device_name": "living room pc", "device_id": "def456"}
JELLYFIN_OPTIONS = {"jellyfin_url": "http://jf.test:8096", "jellyfin_api_key": "k"}


async def handle(hass: HomeAssistant, intent_type: str, **slots) -> intent.IntentResponse:
    """Call an intent the way IntentTool and the sentence lane do."""
    return await intent.async_handle(
        hass, "test", intent_type, {name: {"value": value} for name, value in slots.items()}
    )


def speech(response: intent.IntentResponse) -> str:
    return response.speech["plain"]["speech"]


async def setup(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def add_second_device(hass: HomeAssistant) -> MockConfigEntry:
    second = MockConfigEntry(domain=DOMAIN, data=SECOND_ENTRY, unique_id="def456", title="living room pc")
    second.add_to_hass(hass)
    return second


# ─── One intent per action ───


async def test_every_action_has_a_registered_intent(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    registered = {handler.intent_type for handler in intent.async_get(hass)}
    assert {
        "BoilerRoomLaunchGame",
        "BoilerRoomLaunchApp",
        "BoilerRoomJellyfinPlay",
        "BoilerRoomJellyfinBrowse",
        "BoilerRoomJellyfinControl",
        "BoilerRoomYoutubeSearch",
        "BoilerRoomPower",
        "BoilerRoomWake",
        "BoilerRoomSetVolume",
        "BoilerRoomGetStatus",
        "BoilerRoomListRecent",
    } <= registered
    for handler in intent.async_get(hass):
        if handler.intent_type.startswith("BoilerRoom"):
            assert handler.description, handler.intent_type
            assert handler.platforms is None
            assert "device" in {str(key) for key in handler.slot_schema}


async def test_launch_game_reaches_the_launcher(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch(f"{API}.launch", AsyncMock(return_value={"status": "launching"})) as launch:
        response = await handle(hass, "BoilerRoomLaunchGame", name="balatro")
    launch.assert_awaited_once_with(appid="1")
    assert speech(response) == "Launching Balatro."
    assert response.response_type is intent.IntentResponseType.ACTION_DONE
    # The facts behind the sentence travel with the response for LLM callers.
    assert response.speech_slots == {"matched_name": "Balatro", "appid": "1"}


async def test_launch_app_uses_the_alias_table(hass: HomeAssistant, entry, agent_online):
    hass.config_entries.async_update_entry(entry, options={"app_aliases": "tube=org.freetube.FreeTube"})
    await setup(hass, entry)
    with patch(f"{API}.launch", AsyncMock(return_value={"status": "launching"})) as launch:
        response = await handle(hass, "BoilerRoomLaunchApp", name="tube")
    launch.assert_awaited_once_with(appid="org.freetube.FreeTube", launch_type="app")
    assert speech(response) == "Opening tube."


async def test_power_wake_and_volume(hass: HomeAssistant, entry, agent_online):
    hass.config_entries.async_update_entry(entry, data={**ENTRY_DATA, "mac_address": "aa:bb:cc:dd:ee:ff"})
    await setup(hass, entry)
    with patch(f"{API}.power_action", AsyncMock(return_value={})) as power:
        assert speech(await handle(hass, "BoilerRoomPower", action="shutdown")) == "Shutting down deck."
    power.assert_awaited_once_with("shutdown")

    with patch(f"{API}.set_volume", AsyncMock(return_value={})) as volume:
        assert speech(await handle(hass, "BoilerRoomSetVolume", level="55")) == "Volume set to 55 percent."
    volume.assert_awaited_once_with(55)

    with patch("custom_components.boiler_room.services.send_magic_packet") as wol:
        response = await handle(hass, "BoilerRoomWake")
    wol.assert_called_once_with("aa:bb:cc:dd:ee:ff")
    assert speech(response) == "Sending a wake-up signal to deck."


async def test_invalid_slot_is_an_intent_error(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with pytest.raises(intent.InvalidSlotInfo):
        await handle(hass, "BoilerRoomSetVolume", level=500)
    with pytest.raises(intent.InvalidSlotInfo):
        await handle(hass, "BoilerRoomPower", action="explode")


async def test_youtube_search_opens_the_url(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch(f"{API}.launch", AsyncMock(return_value={})) as launch:
        response = await handle(hass, "BoilerRoomYoutubeSearch", query="lo-fi beats")
    launch.assert_awaited_once_with(
        url="https://www.youtube.com/results?search_query=lo-fi+beats", launch_type="url"
    )
    assert speech(response) == "Searching YouTube for lo-fi beats."


async def test_jellyfin_without_configuration_is_spoken(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    assert speech(await handle(hass, "BoilerRoomJellyfinPlay", query="Fargo")) == "Jellyfin is not configured."
    assert speech(await handle(hass, "BoilerRoomJellyfinControl", action="pause")) == "Jellyfin is not configured."


async def test_jellyfin_play_browse_and_control(hass: HomeAssistant, entry, agent_online):
    hass.config_entries.async_update_entry(entry, options=JELLYFIN_OPTIONS)
    await setup(hass, entry)
    item = {"Name": "Fargo", "Id": "item1", "Type": "Movie"}
    with (
        patch(f"{JELLYFIN}.search", AsyncMock(return_value=[item])) as search,
        patch(f"{JELLYFIN}.find_session", AsyncMock(return_value="session1")),
        patch(f"{JELLYFIN}.play", AsyncMock(return_value=True)) as play,
        patch(f"{JELLYFIN}.view", AsyncMock(return_value=True)) as view,
        patch(f"{JELLYFIN}.playstate", AsyncMock(return_value=True)) as playstate,
    ):
        response = await handle(hass, "BoilerRoomJellyfinPlay", query="fargo", type="Movie")
        assert speech(response) == "Playing the movie Fargo on Jellyfin."
        assert search.await_args.args[3:] == ("fargo", "Movie")
        play.assert_awaited_once()
        assert response.speech_slots["item_id"] == "item1"

        assert speech(await handle(hass, "BoilerRoomJellyfinBrowse", query="fargo")) == "Showing Fargo on Jellyfin."
        view.assert_awaited_once()

        assert speech(await handle(hass, "BoilerRoomJellyfinControl", action="pause")) == "Paused Jellyfin playback."
        assert playstate.await_args.args[-1] == "pause"


# ─── Read-only intents ───


async def test_get_status_reports_the_device(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    response = await handle(hass, "BoilerRoomGetStatus")
    assert speech(response) == "deck is on and idle. CPU 50°C."
    assert response.speech_slots["device"] == "deck"
    assert response.speech_slots["power_state"] == "on"
    assert response.speech_slots["cpu_temp"] == 50.0
    assert "battery_level" not in response.speech_slots


async def test_get_status_while_the_device_sleeps(hass: HomeAssistant, hass_storage, entry, agent_offline):
    key = f"{DOMAIN}.{entry.entry_id}.power_state"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"power_state": "sleep"}}
    await setup(hass, entry)
    response = await handle(hass, "BoilerRoomGetStatus")
    assert speech(response) == "deck is in sleep state."


async def test_list_recent_asks_the_agent(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    recent = [
        {"name": "Balatro", "id": "1", "type": "game", "timestamp": 2},
        {"name": "Firefox", "id": "org.mozilla.firefox", "type": "app", "timestamp": 1},
    ]
    with patch(f"{API}.get_recent", AsyncMock(return_value=recent)):
        response = await handle(hass, "BoilerRoomListRecent")
    assert speech(response) == "Recently launched on deck: Balatro (game), Firefox (app)."
    assert [item["id"] for item in response.speech_slots["recent"]] == ["1", "org.mozilla.firefox"]

    with patch(f"{API}.get_recent", AsyncMock(side_effect=OSError("down"))):
        assert speech(await handle(hass, "BoilerRoomListRecent")) == "deck did not answer."


# ─── Device resolution ───


async def test_one_device_needs_no_device_slot(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch(f"{API}.power_action", AsyncMock(return_value={})):
        assert speech(await handle(hass, "BoilerRoomPower", action="suspend")) == "Suspending deck."


async def test_two_devices_resolve_by_name_nickname_or_entry_id(hass: HomeAssistant, entry, agent_online):
    second = add_second_device(hass)
    await setup(hass, entry)
    assert second.state is ConfigEntryState.LOADED
    with patch(f"{API}.power_action", AsyncMock(return_value={})) as power:
        assert speech(await handle(hass, "BoilerRoomPower", action="reboot", device="living room")) == "Rebooting living room pc."
        assert speech(await handle(hass, "BoilerRoomPower", action="reboot", device="Deck")) == "Rebooting deck."
        # The sentence lane passes the entry its nickname belongs to.
        assert speech(await handle(hass, "BoilerRoomPower", action="reboot", device=second.entry_id)) == "Rebooting living room pc."
    assert power.await_count == 3


async def test_two_devices_without_a_device_slot_ask(hass: HomeAssistant, entry, agent_online):
    add_second_device(hass)
    await setup(hass, entry)
    with patch(f"{API}.power_action", AsyncMock()) as power:
        response = await handle(hass, "BoilerRoomPower", action="reboot")
    power.assert_not_awaited()
    assert response.response_type is intent.IntentResponseType.ERROR
    assert response.error_code is intent.IntentResponseErrorCode.NO_VALID_TARGETS
    assert speech(response) == "Which device do you mean? I know deck or living room pc."


async def test_unknown_device_is_an_error_response(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    response = await handle(hass, "BoilerRoomPower", action="reboot", device="toaster")
    assert response.response_type is intent.IntentResponseType.ERROR
    assert speech(response) == "I don't know a device called toaster."


async def test_read_only_intents_cover_every_device(hass: HomeAssistant, entry, agent_online):
    add_second_device(hass)
    await setup(hass, entry)
    response = await handle(hass, "BoilerRoomGetStatus")
    assert response.response_type is intent.IntentResponseType.ACTION_DONE
    assert speech(response) == "deck is on and idle. CPU 50°C. living room pc is on and idle. CPU 50°C."
    assert [device["device"] for device in response.speech_slots["devices"]] == ["deck", "living room pc"]
    assert speech(await handle(hass, "BoilerRoomGetStatus", device="living room")) == "living room pc is on and idle. CPU 50°C."


async def test_unload_removes_the_intents(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not [h for h in intent.async_get(hass) if h.intent_type.startswith("BoilerRoom")]
    with pytest.raises(intent.UnknownIntent):
        await handle(hass, "BoilerRoomPower", action="reboot")
