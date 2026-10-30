"""Voice sentences: one conversation trigger, a thin lane onto the intents.

No automation, blueprint or button is needed. On every entry setup,
unload and options change the trigger is rebuilt from the loaded entries
and their nicknames (``core/sentences.py`` builds the templates), so a
second device or a renamed nickname takes effect at once.

``register_trigger`` is the only way an integration can give the default
Home Assistant agent sentences, and sentence triggers run before any
conversation agent in every pipeline, so this is the fast, offline lane.
It owns no command logic: a match maps the template to an action's intent
type and slots and calls ``intent.async_handle``; the intent's speech is
the Assist response. Free phrasing is the LLM agents' lane (``llm.py``),
which ends in the same intents.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.conversation import get_agent_manager
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent

from . import services
from .const import DOMAIN
from .core.sentences import (
    HANDLER_AMBIGUOUS_DEVICE,
    SLOT_VOLUME,
    Command,
    build_commands,
    by_template,
    intent_slots,
    templates,
)
from .intents import INTENT_TYPES, which_device_speech
from .services import FIELD_DEVICE

_LOGGER = logging.getLogger(__name__)

VOICE_DATA_KEY = f"{DOMAIN}.voice"

FAILED_SPEECH = "Sorry, that did not work. Check the Boiler Room log."


@callback
def async_refresh_voice_triggers(hass: HomeAssistant) -> None:
    """Replace the registered sentences with the current entries' set."""
    state = hass.data.setdefault(VOICE_DATA_KEY, {"unsubscribe": None})
    if state["unsubscribe"] is not None:
        state["unsubscribe"]()
        state["unsubscribe"] = None

    entries = services.loaded_entries(hass)
    devices = {entry.entry_id: services.entry_nicknames(entry) for entry, _ in entries}
    own_names = {entry.entry_id: services.device_name(entry) for entry, _ in entries}
    commands = build_commands(devices, own_names)
    if not commands:
        _LOGGER.debug("No Boiler Room devices loaded; voice sentences unregistered")
        return

    index = by_template(commands)

    async def _on_match(user_input: Any, result: Any) -> str | None:
        return await _handle_match(hass, index, user_input, result)

    state["unsubscribe"] = get_agent_manager(hass).register_trigger(
        sentences=templates(commands), trigger_callback=_on_match
    )
    _LOGGER.info(
        "Registered %d voice sentences for %d device(s): %s",
        len(commands),
        len(devices),
        "; ".join(f"{own_names[eid]}: {', '.join(nicks)}" for eid, nicks in devices.items()),
    )


@callback
def async_remove_voice_triggers(hass: HomeAssistant) -> None:
    """Unregister everything (last entry unloaded)."""
    state = hass.data.pop(VOICE_DATA_KEY, None)
    if state and state["unsubscribe"] is not None:
        state["unsubscribe"]()


async def _handle_match(
    hass: HomeAssistant, index: dict[str, Command], user_input: Any, result: Any
) -> str | None:
    """Turn a hassil match into an intent call and return the speech."""
    template = result.intent_sentence.text if result.intent_sentence is not None else None
    command = index.get(template or "")
    if command is None:
        _LOGGER.warning("Voice match with unknown template %r for %r", template, user_input.text)
        return None

    matched = {name: entity.value for name, entity in result.entities.items()}
    try:
        values = intent_slots(command, matched)
    except ValueError as err:
        _LOGGER.debug("Unusable slots for %r: %s", user_input.text, err)
        if SLOT_VOLUME in command.slots:
            return "I didn't catch the volume level. Say a number from 0 to 100."
        return "I didn't catch what you want me to open."

    if command.handler == HANDLER_AMBIGUOUS_DEVICE:
        return which_device_speech(hass)

    slots = {name: {"value": value} for name, value in values.items()}
    if command.entry_id is not None:
        # The nickname that was spoken belongs to this entry.
        slots[FIELD_DEVICE] = {"value": command.entry_id}

    _LOGGER.debug("Voice: %r -> %s %s", user_input.text, INTENT_TYPES[command.handler], slots)
    try:
        response = await intent.async_handle(
            hass,
            DOMAIN,
            INTENT_TYPES[command.handler],
            slots,
            text_input=user_input.text,
            context=user_input.context,
            language=user_input.language,
            device_id=user_input.device_id,
            satellite_id=user_input.satellite_id,
            conversation_agent_id=user_input.agent_id,
        )
    except intent.IntentError:
        _LOGGER.exception("Voice command %r failed", user_input.text)
        return FAILED_SPEECH
    return response.speech.get("plain", {}).get("speech") or None
