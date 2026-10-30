"""Voice commands: one conversation trigger registered by the integration.

No automation, blueprint or button is needed. On every entry setup,
unload and options change the trigger is rebuilt from the loaded entries
and their nicknames (``core/sentences.py`` builds the templates), so a
second device or a renamed nickname takes effect at once.

A match comes back with the template text that matched; that text is the
key to the command, which names the handler in ``services.py``, its
static parameters and the config entry the spoken nickname belongs to.
The handler's ``speech`` is returned to Assist as the response.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.conversation import get_agent_manager
from homeassistant.core import HomeAssistant, callback

from . import services
from .const import DOMAIN
from .core.sentences import (
    HANDLER_AMBIGUOUS_DEVICE,
    HANDLER_JELLYFIN_BROWSE,
    HANDLER_JELLYFIN_CONTROL,
    HANDLER_JELLYFIN_PLAY,
    HANDLER_LAUNCH_APP,
    HANDLER_LAUNCH_GAME,
    HANDLER_POWER,
    HANDLER_SET_VOLUME,
    HANDLER_WAKE,
    HANDLER_YOUTUBE_SEARCH,
    SLOT_VOLUME,
    Command,
    build_commands,
    by_template,
    handler_arguments,
    templates,
)

_LOGGER = logging.getLogger(__name__)

VOICE_DATA_KEY = f"{DOMAIN}.voice"

_HANDLERS = {
    HANDLER_LAUNCH_GAME: services.launch_game,
    HANDLER_LAUNCH_APP: services.launch_app,
    HANDLER_JELLYFIN_PLAY: services.jellyfin_play,
    HANDLER_JELLYFIN_BROWSE: services.jellyfin_browse,
    HANDLER_JELLYFIN_CONTROL: services.jellyfin_control,
    HANDLER_YOUTUBE_SEARCH: services.youtube_search,
    HANDLER_POWER: services.power,
    HANDLER_WAKE: services.wake,
    HANDLER_SET_VOLUME: services.set_volume,
}

# Handlers that act on one device. A sentence without a device name only
# reaches them when a single device is configured; otherwise Assist asks.
_NEEDS_DEVICE = frozenset(
    {
        HANDLER_LAUNCH_GAME,
        HANDLER_LAUNCH_APP,
        HANDLER_YOUTUBE_SEARCH,
        HANDLER_POWER,
        HANDLER_WAKE,
        HANDLER_SET_VOLUME,
    }
)


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


def _which_device(hass: HomeAssistant) -> str:
    names = [services.device_name(entry) for entry, _ in services.loaded_entries(hass)]
    if len(names) > 1:
        listed = ", ".join(names[:-1]) + f" or {names[-1]}"
    else:
        listed = names[0] if names else "no device"
    return f"Which device do you mean? I know {listed}."


async def _handle_match(
    hass: HomeAssistant, index: dict[str, Command], user_input: Any, result: Any
) -> str | None:
    """Route a hassil match to its handler and return the speech."""
    template = result.intent_sentence.text if result.intent_sentence is not None else None
    command = index.get(template or "")
    if command is None:
        _LOGGER.warning("Voice match with unknown template %r for %r", template, user_input.text)
        return None

    slots = {name: entity.value for name, entity in result.entities.items()}
    try:
        kwargs = handler_arguments(command, slots)
    except ValueError as err:
        _LOGGER.debug("Unusable slots for %r: %s", user_input.text, err)
        if SLOT_VOLUME in command.slots:
            return "I didn't catch the volume level. Say a number from 0 to 100."
        return "I didn't catch what you want me to open."

    if command.handler == HANDLER_AMBIGUOUS_DEVICE:
        return _which_device(hass)

    if (
        command.entry_id is None
        and command.handler in _NEEDS_DEVICE
        and len(services.loaded_entries(hass)) > 1
    ):
        return _which_device(hass)

    _LOGGER.debug(
        "Voice: %r -> %s(%s) entry=%s", user_input.text, command.handler, kwargs, command.entry_id
    )
    try:
        response = await _HANDLERS[command.handler](hass, entry_id=command.entry_id, **kwargs)
    except Exception:
        _LOGGER.exception("Voice command %r failed", user_input.text)
        return "Sorry, that did not work. Check the Boiler Room log."
    return response.get("speech") or None
