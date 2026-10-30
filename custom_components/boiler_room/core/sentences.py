"""Voice sentence templates for the conversation trigger, as pure functions.

The HA layer (``voice.py``) registers every template from
:func:`build_commands` in ONE conversation trigger and routes a match back
to a handler by the template text that matched. Nothing here imports Home
Assistant, so the templates and the routing are unit-tested in ``tests/``.

Ordering matters. hassil yields matches in template order and the default
agent keeps only the first match per trigger, so templates with more
literal text (``... on Jellyfin``, ``... on the deck``) come before the
generic ``(Launch|Play) {game_name}`` form that would otherwise swallow
them. ``tests/test_sentences.py`` pins this with real hassil matching.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

# Nicknames every device answers to unless the user changes them.
DEFAULT_NICKNAMES: tuple[str, ...] = ("deck", "steam machine", "gaming pc")

# Handler names the HA layer maps to functions in services.py.
HANDLER_LAUNCH_GAME = "launch_game"
HANDLER_LAUNCH_APP = "launch_app"
HANDLER_JELLYFIN_PLAY = "jellyfin_play"
HANDLER_JELLYFIN_BROWSE = "jellyfin_browse"
HANDLER_JELLYFIN_CONTROL = "jellyfin_control"
HANDLER_YOUTUBE_SEARCH = "youtube_search"
HANDLER_POWER = "power"
HANDLER_WAKE = "wake"
HANDLER_SET_VOLUME = "set_volume"
# A nickname shared by two devices: the callback asks which one was meant.
HANDLER_AMBIGUOUS_DEVICE = "ambiguous_device"

HANDLERS: frozenset[str] = frozenset(
    {
        HANDLER_LAUNCH_GAME,
        HANDLER_LAUNCH_APP,
        HANDLER_JELLYFIN_PLAY,
        HANDLER_JELLYFIN_BROWSE,
        HANDLER_JELLYFIN_CONTROL,
        HANDLER_YOUTUBE_SEARCH,
        HANDLER_POWER,
        HANDLER_WAKE,
        HANDLER_SET_VOLUME,
        HANDLER_AMBIGUOUS_DEVICE,
    }
)

# Slot names used in the templates and the handler keyword each one feeds.
SLOT_GAME_NAME = "game_name"
SLOT_APP_NAME = "app_name"
SLOT_QUERY = "query"
SLOT_VOLUME = "volume"

SLOT_TO_KWARG: dict[str, str] = {
    SLOT_GAME_NAME: "name",
    SLOT_APP_NAME: "name",
    SLOT_QUERY: "query",
    SLOT_VOLUME: "level",
}

_JELLYFIN = "(Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
_PLAYBACK = "(Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"
_DEVICE = "{device}"  # placeholder, replaced by the nickname alternation

# Characters hassil treats as template syntax. Stripped from nicknames so a
# user typing "deck (living room)" cannot break every other sentence.
_TEMPLATE_SYNTAX = re.compile(r"[()\[\]{}<>|;:]")
_SEPARATORS = re.compile(r"[,\n]")
_SLOT_REFERENCE = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class Command:
    """One sentence template and where a match goes."""

    template: str
    handler: str
    params: dict[str, str] = field(default_factory=dict)
    # Config entry the sentence names; None means "resolve at call time"
    # (the only device, or the one with Jellyfin configured).
    entry_id: str | None = None

    @property
    def slots(self) -> tuple[str, ...]:
        """Slot names referenced by the template, in order."""
        return tuple(_SLOT_REFERENCE.findall(self.template))


# ─── Nicknames ───


def clean_nickname(raw: str) -> str:
    """Normalize one nickname: lowercase, single spaces, no template syntax."""
    return " ".join(_TEMPLATE_SYNTAX.sub(" ", raw).lower().split())


def parse_nicknames(raw: str | None) -> list[str]:
    """Parse the options-flow text (comma or newline separated) into nicknames."""
    seen: list[str] = []
    for part in _SEPARATORS.split(raw or ""):
        nick = clean_nickname(part)
        if nick and nick not in seen:
            seen.append(nick)
    return seen


def default_nicknames(device_name: str | None) -> list[str]:
    """The device's own name followed by the generic nicknames."""
    names = [clean_nickname(device_name or "")] + list(DEFAULT_NICKNAMES)
    return parse_nicknames(", ".join(names))


def nicknames_text(nicknames: Sequence[str]) -> str:
    """Render nicknames the way the options field shows them."""
    return ", ".join(nicknames)


def split_shared_nicknames(
    devices: Mapping[str, Sequence[str]],
) -> tuple[dict[str, list[str]], list[str]]:
    """Separate nicknames unique to one device from ones several devices use.

    Two devices both called "deck" would both answer "Suspend the deck", so
    shared nicknames are taken away from every device and returned apart;
    the caller registers them with an "ambiguous device" response.
    """
    owners: dict[str, int] = {}
    for nicks in devices.values():
        for nick in dict.fromkeys(nicks):
            owners[nick] = owners.get(nick, 0) + 1
    shared = [nick for nick, count in owners.items() if count > 1]
    unique = {
        entry_id: [nick for nick in dict.fromkeys(nicks) if nick not in shared]
        for entry_id, nicks in devices.items()
    }
    return unique, shared


def match_device(
    spoken: str | None, devices: Mapping[str, Sequence[str]]
) -> str | None:
    """Find the entry whose names include ``spoken`` (exact, then substring).

    ``devices`` maps entry id to every name it answers to (nicknames, device
    name, entry title). Returns None when nothing matches or the match is
    not unique.
    """
    wanted = clean_nickname(spoken or "")
    if not wanted:
        return None
    cleaned = {
        entry_id: [clean_nickname(name) for name in names]
        for entry_id, names in devices.items()
    }
    exact = [eid for eid, names in cleaned.items() if wanted in names]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    partial = [
        eid
        for eid, names in cleaned.items()
        if any(wanted in name or name in wanted for name in names if name)
    ]
    return partial[0] if len(partial) == 1 else None


# ─── Templates ───


def _alternation(nicknames: Sequence[str]) -> str:
    return "(" + "|".join(nicknames) + ")"


def _with_device(template: str, nicknames: Sequence[str]) -> str:
    return template.replace(_DEVICE, _alternation(nicknames))


# Sentences that act on a named device. {device} is replaced per entry.
# "the {app_name} app" comes before the game launcher, whose wildcard would
# otherwise take "the Firefox app" as a game title.
_DEVICE_COMMANDS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("(Wake up|Turn on|Power on) [the] {device}", HANDLER_WAKE, {}),
    ("(Suspend|Sleep) [the] {device}", HANDLER_POWER, {"action": "suspend"}),
    ("Put [the] {device} to sleep", HANDLER_POWER, {"action": "suspend"}),
    (
        "(Turn off|Shut down|Shutdown|Power off) [the] {device}",
        HANDLER_POWER,
        {"action": "shutdown"},
    ),
    ("(Reboot|Restart) [the] {device}", HANDLER_POWER, {"action": "reboot"}),
    ("(Set|Change) [the] {device} volume to {volume}", HANDLER_SET_VOLUME, {}),
    ("Set [the] volume (on|of) [the] {device} to {volume}", HANDLER_SET_VOLUME, {}),
    ("Volume {volume} [on] [the] {device}", HANDLER_SET_VOLUME, {}),
    ("(Launch|Start|Open) the {app_name} app on [the] {device}", HANDLER_LAUNCH_APP, {}),
    (
        "(Launch|Play|Start|Open|Run|Boot up|Fire up) {game_name} on [the] {device}",
        HANDLER_LAUNCH_GAME,
        {},
    ),
    ("Put on {game_name} on [the] {device}", HANDLER_LAUNCH_GAME, {}),
)

# Sentences with a literal anchor other than a device name. Registered
# once; the handler picks the device (the one with Jellyfin configured, or
# the only device). Typed forms come before the untyped ones on purpose.
_ANCHORED_COMMANDS: tuple[tuple[str, str, dict[str, str]], ...] = (
    (
        f"(Play|Watch|Put on) the movie {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_PLAY,
        {"media_type": "Movie"},
    ),
    (
        f"(Play|Watch|Put on) the (show|series|tv show) {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_PLAY,
        {"media_type": "Series"},
    ),
    (
        f"(Play|Listen to|Put on) the album {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_PLAY,
        {"media_type": "MusicAlbum"},
    ),
    (
        f"(Play|Listen to|Put on) the song {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_PLAY,
        {"media_type": "Audio"},
    ),
    (
        f"(Show|Browse|Find|Look up|Go to) the movie {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_BROWSE,
        {"media_type": "Movie"},
    ),
    (
        f"(Show|Browse|Find|Look up|Go to) the (show|series|tv show) {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_BROWSE,
        {"media_type": "Series"},
    ),
    (
        f"(Show|Browse|Find|Look up|Go to) the (album|artist|band) {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_BROWSE,
        {"media_type": "MusicAlbum,MusicArtist"},
    ),
    (
        f"(Play|Watch|Listen to|Put on) {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_PLAY,
        {},
    ),
    (
        f"(Show me|Browse|Look up) {{query}} (on|in) {_JELLYFIN}",
        HANDLER_JELLYFIN_BROWSE,
        {},
    ),
    (f"Pause {_PLAYBACK}", HANDLER_JELLYFIN_CONTROL, {"action": "pause"}),
    (f"(Resume|Unpause) {_PLAYBACK}", HANDLER_JELLYFIN_CONTROL, {"action": "unpause"}),
    (f"Stop {_PLAYBACK}", HANDLER_JELLYFIN_CONTROL, {"action": "stop"}),
    (
        f"(Rewind|Go back|Skip back) {_PLAYBACK}",
        HANDLER_JELLYFIN_CONTROL,
        {"action": "rewind"},
    ),
    (
        f"(Fast forward|Skip forward|Skip ahead) {_PLAYBACK}",
        HANDLER_JELLYFIN_CONTROL,
        {"action": "fastforward"},
    ),
    ("Search YouTube for {query}", HANDLER_YOUTUBE_SEARCH, {}),
    ("(Open|Play|Watch) {query} on YouTube", HANDLER_YOUTUBE_SEARCH, {}),
)

# Generic sentences with no device and no anchor. Last, because the
# wildcard swallows anything after the verb; app before game as above.
_GENERIC_COMMANDS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("(Launch|Start|Open) the {app_name} app", HANDLER_LAUNCH_APP, {}),
    (
        "(Launch|Play|Start|Open|Run|Boot up|Fire up) {game_name}",
        HANDLER_LAUNCH_GAME,
        {},
    ),
    ("Put on {game_name}", HANDLER_LAUNCH_GAME, {}),
    ("(Set|Change) [the] volume to {volume}", HANDLER_SET_VOLUME, {}),
)


def build_commands(devices: Mapping[str, Sequence[str]]) -> list[Command]:
    """Every sentence to register, in match-priority order.

    ``devices`` maps config entry id to that device's nicknames. With no
    devices nothing is returned (nothing to control). Generic sentences
    carry ``entry_id=None``; the caller targets the only device or, with
    several, asks which one.
    """
    if not devices:
        return []

    unique, shared = split_shared_nicknames(devices)
    commands: list[Command] = []

    for template, handler, params in _ANCHORED_COMMANDS:
        commands.append(Command(template, handler, dict(params)))

    for entry_id, nicknames in unique.items():
        if not nicknames:
            continue
        for template, handler, params in _DEVICE_COMMANDS:
            commands.append(
                Command(_with_device(template, nicknames), handler, dict(params), entry_id)
            )

    if shared:
        for template, _handler, _params in _DEVICE_COMMANDS:
            commands.append(
                Command(_with_device(template, shared), HANDLER_AMBIGUOUS_DEVICE)
            )

    for template, handler, params in _GENERIC_COMMANDS:
        commands.append(Command(template, handler, dict(params)))

    return commands


def templates(commands: Sequence[Command]) -> list[str]:
    """The sentence list to hand to ``register_trigger``."""
    return [command.template for command in commands]


def by_template(commands: Sequence[Command]) -> dict[str, Command]:
    """Index for routing a match back to its command by template text."""
    index: dict[str, Command] = {}
    for command in commands:
        if command.template in index:
            raise ValueError(f"duplicate template: {command.template}")
        index[command.template] = command
    return index


def handler_arguments(command: Command, slots: Mapping[str, object]) -> dict[str, object]:
    """Keyword arguments for the handler: static params plus matched slots.

    Slot values arrive as text; the volume becomes an int in 0..100.
    Raises ValueError when a required slot is missing or unusable.
    """
    kwargs: dict[str, object] = dict(command.params)
    for slot in command.slots:
        if slot not in slots:
            raise ValueError(f"slot {slot!r} missing from match")
        value = slots[slot]
        text = value.strip() if isinstance(value, str) else str(value)
        if slot == SLOT_VOLUME:
            try:
                level = int(text)
            except ValueError as err:
                raise ValueError(f"volume {text!r} is not a number") from err
            if not 0 <= level <= 100:
                raise ValueError(f"volume {level} is out of range")
            kwargs[SLOT_TO_KWARG[slot]] = level
        else:
            if not text:
                raise ValueError(f"slot {slot!r} is empty")
            kwargs[SLOT_TO_KWARG[slot]] = text
    return kwargs
