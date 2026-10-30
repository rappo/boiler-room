"""Voice sentences registered by the integration itself (no automation).

Runs the real conversation agent of the harness's HA release over the
sentences voice.py registers, with the agent API mocked. A match ends in
the action's intent, the same code path the LLM tools take.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.components import conversation
from homeassistant.components.conversation import get_agent_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "boiler_room"
SUSPEND_DECK = "(Suspend|Sleep) [the] (deck|steam machine|gaming pc)"
SECOND_ENTRY = {"host": "192.0.2.11", "port": 9451, "device_name": "living room pc", "device_id": "def456"}


async def say(hass: HomeAssistant, text: str) -> str:
    result = await conversation.async_converse(hass, text, None, Context(), language="en")
    return result.response.speech["plain"]["speech"]


async def setup(hass: HomeAssistant, entry) -> None:
    """Set the integration up. Every added entry of the domain loads with it."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def add_second_device(hass: HomeAssistant) -> MockConfigEntry:
    second = MockConfigEntry(domain=DOMAIN, data=SECOND_ENTRY, unique_id="def456", title="living room pc")
    second.add_to_hass(hass)
    return second


async def test_sentences_registered_on_setup(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    sentences = get_agent_manager(hass).trigger_sentences
    assert SUSPEND_DECK in sentences
    assert "(Launch|Play|Start|Open|Run|Boot up|Fire up) {game_name}" in sentences
    assert hass.services.has_service(DOMAIN, "power")


async def test_power_by_voice_names_the_device(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch("custom_components.boiler_room.BoilerRoomAPI.power_action", AsyncMock(return_value={})) as power:
        assert await say(hass, "Suspend the deck") == "Suspending deck."
        power.assert_awaited_once_with("suspend")
        assert await say(hass, "put the steam machine to sleep") == "Suspending deck."


async def test_a_match_is_handled_by_the_intent(hass: HomeAssistant, entry, agent_online):
    """The trigger lane owns no command logic: it calls the action's intent."""
    await setup(hass, entry)
    with (
        patch("custom_components.boiler_room.BoilerRoomAPI.power_action", AsyncMock(return_value={})),
        patch("custom_components.boiler_room.voice.intent.async_handle", wraps=intent.async_handle) as handle,
    ):
        assert await say(hass, "Reboot the deck") == "Rebooting deck."
    handle.assert_awaited_once()
    args, kwargs = handle.await_args
    assert args[1:3] == ("boiler_room", "BoilerRoomPower")
    assert args[3] == {"action": {"value": "reboot"}, "device": {"value": entry.entry_id}}
    assert kwargs["text_input"] == "Reboot the deck"


async def test_conversation_process_round_trip(hass: HomeAssistant, entry, agent_online):
    """What a dashboard or script calls: conversation.process on the HA agent."""
    await setup(hass, entry)
    with patch(
        "custom_components.boiler_room.BoilerRoomAPI.launch", AsyncMock(return_value={"status": "launching"})
    ) as launch:
        result = await hass.services.async_call(
            "conversation",
            "process",
            {"text": "launch balatro", "agent_id": "conversation.home_assistant"},
            blocking=True,
            return_response=True,
        )
    launch.assert_awaited_once_with(appid="1")
    assert result["response"]["speech"]["plain"]["speech"] == "Launching Balatro."


async def test_handler_failure_is_spoken_not_raised(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch("custom_components.boiler_room.BoilerRoomAPI.power_action", AsyncMock(side_effect=RuntimeError("bug"))):
        assert await say(hass, "Reboot the deck") == "Sorry, that did not work. Check the Boiler Room log."


async def test_generic_launch_targets_the_only_device(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch(
        "custom_components.boiler_room.BoilerRoomAPI.launch", AsyncMock(return_value={"status": "launching"})
    ) as launch:
        assert await say(hass, "Play Balatro") == "Launching Balatro."
        launch.assert_awaited_once_with(appid="1")


async def test_jellyfin_sentence_does_not_reach_the_game_launcher(hass: HomeAssistant, entry, agent_online):
    """The old automations fired both; one trigger in template order fires one."""
    await setup(hass, entry)
    with patch("custom_components.boiler_room.BoilerRoomAPI.launch", AsyncMock()) as launch:
        assert await say(hass, "Play Robocop on Jellyfin") == "Jellyfin is not configured."
        launch.assert_not_awaited()


async def test_volume_slot_is_parsed(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch("custom_components.boiler_room.BoilerRoomAPI.set_volume", AsyncMock(return_value={})) as vol:
        assert await say(hass, "Set volume to 30") == "Volume set to 30 percent."
        vol.assert_awaited_once_with(30)
        assert "didn't catch the volume" in await say(hass, "Set the deck volume to loud")
        vol.assert_awaited_once()


async def test_unreachable_device_is_spoken_not_raised(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    with patch("custom_components.boiler_room.BoilerRoomAPI.power_action", AsyncMock(side_effect=OSError("down"))):
        assert await say(hass, "Reboot the deck") == "deck did not answer."


async def test_two_devices_route_by_nickname_and_ask_when_shared(hass: HomeAssistant, entry, agent_online):
    second = add_second_device(hass)
    await setup(hass, entry)
    assert second.state is ConfigEntryState.LOADED

    sentences = get_agent_manager(hass).trigger_sentences
    # "deck" is the first device's own name, so it keeps it; the generic
    # nicknames both devices list are registered as ambiguous.
    assert "(Suspend|Sleep) [the] (deck)" in sentences
    assert "(Suspend|Sleep) [the] (living room pc)" in sentences
    assert "(Suspend|Sleep) [the] (steam machine|gaming pc)" in sentences

    with patch("custom_components.boiler_room.BoilerRoomAPI.power_action", AsyncMock(return_value={})) as power:
        assert await say(hass, "Suspend the living room pc") == "Suspending living room pc."
        assert await say(hass, "Suspend the deck") == "Suspending deck."
        assert power.await_count == 2
        assert await say(hass, "Suspend the gaming pc") == "Which device do you mean? I know deck or living room pc."
        assert await say(hass, "Play Balatro") == "Which device do you mean? I know deck or living room pc."
        assert power.await_count == 2


async def test_service_device_argument_is_honored(hass: HomeAssistant, entry, agent_online):
    second = add_second_device(hass)
    await setup(hass, entry)
    assert second.state is ConfigEntryState.LOADED
    with patch("custom_components.boiler_room.BoilerRoomAPI.power_action", AsyncMock(return_value={})):
        response = await hass.services.async_call(
            DOMAIN, "power", {"action": "reboot", "device": "living room"}, blocking=True, return_response=True
        )
        assert response["speech"] == "Rebooting living room pc."
        response = await hass.services.async_call(
            DOMAIN, "power", {"action": "reboot", "device": "toaster"}, blocking=True, return_response=True
        )
        assert response["speech"] == "I don't know a device called toaster."


async def test_nickname_option_rebuilds_sentences(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    hass.config_entries.async_update_entry(entry, options={"device_nicknames": "Big TV, deck"})
    await hass.async_block_till_done()
    sentences = get_agent_manager(hass).trigger_sentences
    assert "(Suspend|Sleep) [the] (big tv|deck)" in sentences
    assert SUSPEND_DECK not in sentences
    with patch("custom_components.boiler_room.BoilerRoomAPI.power_action", AsyncMock(return_value={})):
        assert await say(hass, "Suspend the big TV") == "Suspending deck."


async def test_unload_unregisters_everything(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert get_agent_manager(hass).trigger_sentences == []
    assert not hass.services.has_service(DOMAIN, "power")
    assert not [h for h in intent.async_get(hass) if h.intent_type.startswith("BoilerRoom")]


async def test_legacy_automation_button_is_removed(hass: HomeAssistant, entry, agent_online):
    registry = er.async_get(hass)
    registry.async_get_or_create("button", DOMAIN, "abc123_create_voice_automations", config_entry=entry)
    await setup(hass, entry)
    assert registry.async_get_entity_id("button", DOMAIN, "abc123_create_voice_automations") is None
    assert registry.async_get_entity_id("button", DOMAIN, "abc123_wake_on_lan") is not None
