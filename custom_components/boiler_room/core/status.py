"""Spoken summaries of a device's status and recent launches, as pure functions.

The agent reports ``/status`` (power state, what runs) and ``/system/sensors``
(temperatures, volume, battery) as flat JSON. The read-only intents turn
them into one sentence for Assist and a flat dict for an LLM tool result.
Nothing here imports Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Keys copied from the agent's /status and /system/sensors into the data dict.
_STATUS_KEYS = ("power_state", "state", "current_app", "current_app_type", "gaming_mode")
_SENSOR_KEYS = ("cpu_temp", "gpu_temp", "ambient_temp", "volume", "battery_level", "battery_charging")

_TYPE_LABELS = {"game": "the game", "app": "the app", "shortcut": "the shortcut"}

RECENT_LIMIT = 10


def _temperature(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return f"{round(value)}°C"


def summarize_status(
    device_name: str, status: Mapping[str, Any] | None, sensors: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """One sentence about a device plus the facts it was built from.

    ``status`` may hold only a persisted ``power_state`` (the device has not
    been reached since Home Assistant started) or nothing at all.
    """
    status = status or {}
    sensors = sensors or {}
    data: dict[str, Any] = {"device": device_name}
    data.update({key: status[key] for key in _STATUS_KEYS if key in status})
    data.update({key: sensors[key] for key in _SENSOR_KEYS if key in sensors})
    if data.get("battery_level", 0) < 0:
        # The agent reports -1 for a device without a battery.
        data.pop("battery_level", None)
        data.pop("battery_charging", None)

    power_state = status.get("power_state")
    if not power_state:
        return f"{device_name} has not been reached yet.", data

    parts: list[str] = []
    if power_state != "on":
        parts.append(f"{device_name} is in {power_state} state.")
        return " ".join(parts), data

    current_app = status.get("current_app")
    if current_app:
        label = _TYPE_LABELS.get(status.get("current_app_type", ""), "")
        running = f"{label} {current_app}".strip()
        parts.append(f"{device_name} is on and running {running}.")
    else:
        parts.append(f"{device_name} is on and idle.")

    temps = [
        f"{label} {text}"
        for label, text in (
            ("CPU", _temperature(sensors.get("cpu_temp"))),
            ("GPU", _temperature(sensors.get("gpu_temp"))),
        )
        if text
    ]
    if temps:
        parts.append(", ".join(temps) + ".")

    if isinstance(sensors.get("volume"), int):
        parts.append(f"Volume {sensors['volume']} percent.")

    if "battery_level" in data:
        charging = ", charging" if data.get("battery_charging") else ""
        parts.append(f"Battery {data['battery_level']} percent{charging}.")

    return " ".join(parts), data


def summarize_recent(
    device_name: str, items: Sequence[Mapping[str, Any]], limit: int = RECENT_LIMIT
) -> tuple[str, dict[str, Any]]:
    """The most recent launches on a device, newest first."""
    recent = [
        {key: item[key] for key in ("name", "id", "type", "timestamp") if key in item}
        for item in items[:limit]
    ]
    data = {"device": device_name, "recent": recent}
    if not recent:
        return f"Nothing has been launched on {device_name} yet.", data
    names = ", ".join(f"{item.get('name', '?')} ({item['type']})" if item.get("type") else item.get("name", "?") for item in recent)
    return f"Recently launched on {device_name}: {names}.", data
