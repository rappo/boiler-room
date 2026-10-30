"""The LLM tool platform: what an Ollama or OpenAI agent, or the MCP Server, gets.

Registering an intent exposes nothing to LLMs; ``llm.py`` does. These tests
build the Assist API the way a conversation agent does and look at the tools.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import probatio
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import llm

from custom_components.boiler_room import llm as boiler_llm

DOMAIN = "boiler_room"
API = "custom_components.boiler_room.BoilerRoomAPI"

TOOL_NAMES = {
    "boiler_room__BoilerRoomLaunchGame",
    "boiler_room__BoilerRoomLaunchApp",
    "boiler_room__BoilerRoomJellyfinPlay",
    "boiler_room__BoilerRoomJellyfinBrowse",
    "boiler_room__BoilerRoomJellyfinControl",
    "boiler_room__BoilerRoomYoutubeSearch",
    "boiler_room__BoilerRoomPower",
    "boiler_room__BoilerRoomWake",
    "boiler_room__BoilerRoomSetVolume",
    "boiler_room__BoilerRoomGetStatus",
    "boiler_room__BoilerRoomListRecent",
}


def context() -> llm.LLMContext:
    return llm.LLMContext(platform="test", context=Context(), language="en", assistant="conversation", device_id=None)


async def assist_api(hass: HomeAssistant) -> llm.APIInstance:
    """The Assist API instance a conversation agent builds per turn."""
    return await llm.async_get_api(hass, llm.LLM_API_ASSIST, context())


async def setup(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_one_tool_per_intent_in_the_assist_api(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    api = await assist_api(hass)
    ours = {tool.name: tool for tool in api.tools if tool.name.startswith(f"{DOMAIN}__")}
    assert set(ours) == TOOL_NAMES
    for tool in ours.values():
        assert tool.integration == DOMAIN
        assert tool.description
        assert tool.annotations.open_world is False
        assert "device" in probatio.to_openapi(tool.parameters)["properties"]


async def test_annotations_say_what_each_tool_does(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    tools = {tool.name: tool for tool in (await assist_api(hass)).tools}
    for name in ("boiler_room__BoilerRoomGetStatus", "boiler_room__BoilerRoomListRecent"):
        assert tools[name].annotations.read_only is True
        assert tools[name].annotations.destructive is False
    power = tools["boiler_room__BoilerRoomPower"].annotations
    assert power.destructive is True and power.read_only is False
    launch = tools["boiler_room__BoilerRoomLaunchGame"].annotations
    assert launch.destructive is False and launch.read_only is False
    assert tools["boiler_room__BoilerRoomWake"].annotations.idempotent is True


async def test_parameters_carry_descriptions_and_limits(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    tools = {tool.name: tool for tool in (await assist_api(hass)).tools}
    volume = probatio.to_openapi(tools["boiler_room__BoilerRoomSetVolume"].parameters)
    assert volume["required"] == ["level"]
    assert volume["properties"]["level"]["minimum"] == 0
    assert volume["properties"]["level"]["maximum"] == 100
    assert volume["properties"]["device"]["description"]
    power = probatio.to_openapi(tools["boiler_room__BoilerRoomPower"].parameters)
    assert power["properties"]["action"]["enum"] == ["suspend", "shutdown", "reboot"]
    game = probatio.to_openapi(tools["boiler_room__BoilerRoomLaunchGame"].parameters)
    assert "fuzzily" in game["properties"]["name"]["description"]


async def test_prompt_names_the_devices(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    api = await assist_api(hass)
    assert "Boiler Room controls these SteamOS devices: deck (also called steam machine, gaming pc)" in api.api_prompt


async def test_a_tool_call_ends_in_the_handler(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    api = await assist_api(hass)
    with patch(f"{API}.launch", AsyncMock(return_value={"status": "launching"})) as launch:
        result = await api.async_call_tool(
            llm.ToolInput(tool_name="boiler_room__BoilerRoomLaunchGame", tool_args={"name": "balatro"})
        )
    launch.assert_awaited_once_with(appid="1")
    assert result.data["speech"]["plain"]["speech"] == "Launching Balatro."
    assert result.data["speech_slots"]["appid"] == "1"
    assert result.data["response_type"] == "action_done"

    with patch(f"{API}.get_recent", AsyncMock(return_value=[])):
        result = await api.async_call_tool(
            llm.ToolInput(tool_name="boiler_room__BoilerRoomListRecent", tool_args={"device": ""})
        )
    assert result.data["speech"]["plain"]["speech"] == "Nothing has been launched on deck yet."


async def test_other_apis_and_no_devices_get_nothing(hass: HomeAssistant, entry, agent_online):
    await setup(hass, entry)
    assert boiler_llm.async_get_tools(hass, context(), "some_other_api") is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert boiler_llm.async_get_tools(hass, context(), llm.LLM_API_ASSIST) is None
    api = await assist_api(hass)
    assert not [tool for tool in api.tools if tool.name.startswith(f"{DOMAIN}__")]
    assert "Boiler Room" not in api.api_prompt
