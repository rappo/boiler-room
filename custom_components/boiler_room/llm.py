"""LLM tools for Boiler Room: one tool per intent, for the Assist API.

Home Assistant discovers this module by name (``llm.py`` in the
integration) and calls :func:`async_get_tools` every time a conversation
agent that uses the Assist API builds its tool list, which is also what
the MCP Server integration serves to external clients. Without this
module the intents in ``intents.py`` exist but no LLM ever sees them.

Tool names are ``boiler_room__<IntentType>``, the prefix HA requires of
integration-provided tools. The prompt fragment names the devices, since
the tool descriptions cannot know them.
"""

from __future__ import annotations

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    IntentTool,
    LLMContext,
    Tool,
    ToolAnnotations,
)

from . import services
from .const import DOMAIN
from .intents import async_get_handlers
from .services import Action


def tool_name(action: Action) -> str:
    """The tool name an LLM calls for an action."""
    return f"{DOMAIN}__{action.intent_type}"


def tool_annotations(action: Action) -> ToolAnnotations:
    """How the tool behaves, from the action table.

    Nothing here reaches outside the user's own devices, so ``open_world``
    is always False.
    """
    return ToolAnnotations(
        read_only=action.read_only,
        destructive=action.destructive,
        idempotent=action.idempotent,
        open_world=False,
    )


def devices_prompt(hass: HomeAssistant) -> str | None:
    """One line naming the devices and their nicknames, for the system prompt."""
    entries = services.loaded_entries(hass)
    if not entries:
        return None
    described = []
    for entry, _ in entries:
        name = services.device_name(entry)
        nicknames = [nick for nick in services.entry_nicknames(entry) if nick != name.lower()]
        described.append(f"{name} (also called {', '.join(nicknames)})" if nicknames else name)
    return (
        "Boiler Room controls these SteamOS devices: "
        + "; ".join(described)
        + ". Use the boiler_room tools for games, apps, Jellyfin, YouTube, power and volume on them."
    )


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    """Return a tool per registered Boiler Room intent for the Assist API."""
    if api_id != LLM_API_ASSIST:
        return None
    handlers = async_get_handlers(hass)
    if not handlers:
        return None
    tools: list[Tool] = [
        IntentTool(
            tool_name(handler.action),
            handler,
            title=handler.action.title,
            integration=DOMAIN,
            annotations=tool_annotations(handler.action),
        )
        for handler in handlers
    ]
    return LLMTools(tools=tools, prompt=devices_prompt(hass))
