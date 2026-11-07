"""Remote button events from the agent, turned into volume service calls.

Framework-free: the integration feeds it button events and calls the
service it returns. Holding a key makes the kernel repeat it about 30
times a second; each repeat would be one volume step on the receiver, so
repeats are thinned to one per REPEAT_INTERVAL.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REPEAT_INTERVAL = 0.15  # seconds between volume steps while a key is held

VOLUME_SERVICES = {
    "volume_up": "volume_up",
    "volume_down": "volume_down",
    "volume_mute": "volume_mute",
}

ACTIONS = ("press", "repeat", "release")


def parse_event(data: object) -> tuple[str, str] | None:
    """The (button, action) of a remote_button event's data, if well formed."""
    if not isinstance(data, dict):
        return None
    button = data.get("button")
    action = data.get("action")
    if not isinstance(button, str) or not button or action not in ACTIONS:
        return None
    return button, action


@dataclass
class VolumeGate:
    """Decides which button events become a volume service call."""

    interval: float = REPEAT_INTERVAL
    _last: dict[str, float] = field(default_factory=dict)

    def service_for(self, button: str, action: str, now: float) -> str | None:
        """The media_player service to call now, or None to do nothing.

        A press always acts. A repeat acts once the interval has passed
        since the last step for that button. Mute acts on press only, so
        holding it does not flicker. Release never acts.
        """
        service = VOLUME_SERVICES.get(button)
        if service is None or action == "release":
            return None
        if action == "repeat":
            if service == "volume_mute":
                return None
            if now - self._last.get(button, float("-inf")) < self.interval:
                return None
        self._last[button] = now
        return service
