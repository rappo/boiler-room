"""Boiler Room intents: the one code path every command goes through.

One :class:`BoilerRoomIntentHandler` per entry of ``services.ACTIONS`` is
registered with Home Assistant's intent helper when the first config entry
loads and removed when the last one unloads. Three callers reach them:

- the sentence trigger in ``voice.py`` (exact phrasings, every pipeline);
- LLM conversation agents and the MCP Server, through the tools that
  ``llm.py`` builds from these handlers;
- anything else that calls ``intent.async_handle`` or the HTTP intent API.

Registering an intent alone exposes nothing to LLMs; that is ``llm.py``.

The ``device`` slot takes a name, a voice nickname or a config entry id
(what the sentence lane passes). Left out, an action that changes one
device goes to the only device, or asks which one when there are several;
Jellyfin actions pick the device with Jellyfin configured, and the
read-only ones report on every device.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent

from . import services
from .const import DOMAIN
from .services import ACTIONS, FIELD_DEVICE, Action

_LOGGER = logging.getLogger(__name__)

INTENTS_DATA_KEY = f"{DOMAIN}.intents"

# Intent type per action name, for the sentence lane.
INTENT_TYPES: dict[str, str] = {action.name: action.intent_type for action in ACTIONS}


class TargetError(Exception):
    """The device could not be decided; the message is spoken as is."""


def which_device_speech(hass: HomeAssistant) -> str:
    """The question Assist asks when a command names no device but could mean several."""
    names = [services.device_name(entry) for entry, _ in services.loaded_entries(hass)]
    if len(names) > 1:
        listed = ", ".join(names[:-1]) + f" or {names[-1]}"
    else:
        listed = names[0] if names else "no device"
    return f"Which device do you mean? I know {listed}."


def resolve_target(hass: HomeAssistant, device: str | None, targets_device: bool) -> str | None:
    """The config entry id an action should act on, or None for "handler decides".

    Raises :class:`TargetError` when ``device`` names nothing, or when the
    action needs one device and several are loaded.
    """
    if device:
        entry_id = services.resolve_entry_id(hass, device)
        if entry_id is None:
            raise TargetError(f"I don't know a device called {device}.")
        return entry_id
    if targets_device and len(services.loaded_entries(hass)) > 1:
        raise TargetError(which_device_speech(hass))
    return None


class BoilerRoomIntentHandler(intent.IntentHandler):
    """Handle one action's intent by calling its handler in ``services.py``."""

    # platforms stays None: these intents do not act on HA entities, so
    # they are handled (and offered as tools) whatever is exposed.

    def __init__(self, action: Action) -> None:
        """Describe the intent from the action table."""
        self.action = action
        self.intent_type = action.intent_type
        self.description = action.description

    @property
    def slot_schema(self) -> dict:
        """The action's fields plus the optional device."""
        return self.action.schema

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Resolve the device, run the handler, speak its answer."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        values = {name: slot["value"] for name, slot in slots.items()}
        response = intent_obj.create_response()

        device = values.pop(FIELD_DEVICE, None)
        try:
            entry_id = resolve_target(hass, device, self.action.targets_device)
        except TargetError as err:
            response.async_set_error(intent.IntentResponseErrorCode.NO_VALID_TARGETS, str(err))
            return response

        kwargs = {kw: values[name] for name, kw in self.action.kwargs.items() if name in values}
        _LOGGER.debug(
            "Intent %s from %s: %s(%s) entry=%s",
            self.intent_type,
            intent_obj.platform,
            self.action.name,
            kwargs,
            entry_id,
        )
        result = await self.action.handler(hass, entry_id=entry_id, **kwargs)

        response.async_set_speech(result["speech"])
        details = {key: value for key, value in result.items() if key != "speech"}
        if details:
            # The facts behind the sentence (matched title, app id, status
            # values), for an LLM reading the tool result.
            response.async_set_speech_slots(details)
        return response


@callback
def async_register_intents(hass: HomeAssistant) -> None:
    """Register every action's intent once (first config entry loaded)."""
    if INTENTS_DATA_KEY in hass.data:
        return
    handlers = [BoilerRoomIntentHandler(action) for action in ACTIONS]
    for handler in handlers:
        intent.async_register(hass, handler)
    hass.data[INTENTS_DATA_KEY] = handlers
    _LOGGER.info("Registered %d Boiler Room intents", len(handlers))


@callback
def async_remove_intents(hass: HomeAssistant) -> None:
    """Remove the intents (last config entry unloaded)."""
    for handler in hass.data.pop(INTENTS_DATA_KEY, []):
        intent.async_remove(hass, handler.intent_type)


@callback
def async_get_handlers(hass: HomeAssistant) -> list[BoilerRoomIntentHandler]:
    """The registered Boiler Room handlers, for the LLM tool platform."""
    return [
        handler
        for handler in intent.async_get(hass)
        if isinstance(handler, BoilerRoomIntentHandler)
    ]
