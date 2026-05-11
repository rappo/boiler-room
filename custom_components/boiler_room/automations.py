"""Voice automation templates and auto-creation for Boiler Room.

Provides pre-built HA automation configs that wire conversation triggers
to Boiler Room services. Can be created programmatically via the
'Create Voice Automations' button or copied from the README.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ─── Automation IDs (stable, used to detect duplicates) ───

ID_SYSTEM = "boiler_room_system_controls"
ID_GAMES = "boiler_room_games_and_apps"
ID_JELLYFIN = "boiler_room_jellyfin_media"


def get_automation_templates() -> list[dict[str, Any]]:
    """Return the three voice automation configs."""
    return [_system_controls(), _games_and_apps(), _jellyfin_media()]


def _system_controls() -> dict[str, Any]:
    return {
        "id": ID_SYSTEM,
        "alias": "Boiler Room: System Controls",
        "description": "Voice commands for SteamOS device power and volume control.",
        "mode": "single",
        "triggers": [
            {
                "trigger": "conversation",
                "command": [
                    "(Wake up|Turn on|Power on) the (deck|steam machine|gaming pc)",
                ],
                "id": "wake",
            },
            {
                "trigger": "conversation",
                "command": [
                    "(Suspend|Sleep) the (deck|steam machine|gaming pc)",
                    "Put the (deck|steam machine|gaming pc) to sleep",
                ],
                "id": "suspend",
            },
            {
                "trigger": "conversation",
                "command": [
                    "(Turn off|Shut down|Shutdown|Power off) the (deck|steam machine|gaming pc)",
                ],
                "id": "shutdown",
            },
            {
                "trigger": "conversation",
                "command": [
                    "(Reboot|Restart) the (deck|steam machine|gaming pc)",
                ],
                "id": "reboot",
            },
            {
                "trigger": "conversation",
                "command": [
                    "(Set|Change) (the|) (deck|steam machine|gaming pc) volume to {volume}",
                    "Volume {volume} (on|) (the|) (deck|steam machine|gaming pc)",
                ],
                "id": "volume",
            },
        ],
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [{"condition": "trigger", "id": "wake"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "suspend"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "shutdown"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "reboot"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "volume"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                ]
            }
        ],
    }


def _games_and_apps() -> dict[str, Any]:
    return {
        "id": ID_GAMES,
        "alias": "Boiler Room: Games & Apps",
        "description": "Voice commands for launching Steam games and apps on your SteamOS device.",
        "mode": "single",
        "triggers": [
            {
                "trigger": "conversation",
                "command": [
                    "(Launch|Play|Start|Open|Run|Boot up|Fire up) {game_name}",
                    "Put on {game_name}",
                    "(Launch|Play|Start|Open|Run) {game_name} on the (deck|steam machine|tv|living room|gaming pc)",
                ],
                "id": "launch_game",
            },
            {
                "trigger": "conversation",
                "command": [
                    "Open {app_name} on the (deck|steam machine|tv|living room|gaming pc)",
                    "(Launch|Start) the {app_name} app",
                ],
                "id": "launch_app",
            },
        ],
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [{"condition": "trigger", "id": "launch_game"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "launch_app"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                ]
            }
        ],
    }


def _jellyfin_media() -> dict[str, Any]:
    return {
        "id": ID_JELLYFIN,
        "alias": "Boiler Room: Jellyfin Media",
        "description": "Voice commands for Jellyfin media playback, browsing, and YouTube.",
        "mode": "single",
        "triggers": [
            # ─── Jellyfin Play ───
            {
                "trigger": "conversation",
                "command": ["(Play|Watch|Listen to|Put on) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"],
                "id": "jellyfin_play",
            },
            {
                "trigger": "conversation",
                "command": ["(Play|Watch|Put on) the movie {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"],
                "id": "jellyfin_play_movie",
            },
            {
                "trigger": "conversation",
                "command": ["(Play|Watch|Put on) the (show|series|tv show) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"],
                "id": "jellyfin_play_series",
            },
            {
                "trigger": "conversation",
                "command": ["(Play|Listen to|Put on) the album {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"],
                "id": "jellyfin_play_album",
            },
            {
                "trigger": "conversation",
                "command": ["(Play|Listen to|Put on) the song {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"],
                "id": "jellyfin_play_song",
            },
            # ─── Jellyfin Browse ───
            {
                "trigger": "conversation",
                "command": [
                    "(Show me|Browse|Look up) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)",
                    "(Show|Browse|Find|Look up|Go to) the movie {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)",
                    "(Show|Browse|Find|Look up|Go to) the (show|series|tv show) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)",
                    "(Show|Browse|Find|Look up|Go to) the (album|artist|band) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)",
                ],
                "id": "jellyfin_browse",
            },
            # ─── Jellyfin Playback Control ───
            {
                "trigger": "conversation",
                "command": ["(Pause|Resume|Unpause) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"],
                "id": "jellyfin_pause",
            },
            {
                "trigger": "conversation",
                "command": ["(Stop) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"],
                "id": "jellyfin_stop",
            },
            {
                "trigger": "conversation",
                "command": ["(Rewind|Go back|Skip back) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"],
                "id": "jellyfin_rewind",
            },
            {
                "trigger": "conversation",
                "command": ["(Fast forward|Skip forward|Skip ahead) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"],
                "id": "jellyfin_ff",
            },
            # ─── YouTube ───
            {
                "trigger": "conversation",
                "command": [
                    "Search YouTube for {query}",
                    "(Open|Play|Watch) {query} on YouTube",
                ],
                "id": "youtube",
            },
        ],
        "actions": [
            {
                "choose": [
                    # ─── Jellyfin Play ───
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_play"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_play_movie"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_play_series"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_play_album"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_play_song"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    # ─── Jellyfin Browse ───
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_browse"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    # ─── Jellyfin Playback Control ───
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_pause"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_stop"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_rewind"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "jellyfin_ff"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                    # ─── YouTube ───
                    {
                        "conditions": [{"condition": "trigger", "id": "youtube"}],
                        "sequence": [
                            {"set_conversation_response": "{{ result.speech | default('Command sent.') }}"},
                        ],
                    },
                ]
            }
        ],
    }


async def async_create_voice_automations(hass: HomeAssistant) -> int:
    """Create voice automations in automations.yaml. Returns count of automations added."""
    automations_path = Path(hass.config.path("automations.yaml"))

    # Load existing automations
    existing: list[dict[str, Any]] = []
    if automations_path.exists():
        try:
            raw = await hass.async_add_executor_job(automations_path.read_text)
            parsed = yaml.safe_load(raw)
            if isinstance(parsed, list):
                existing = parsed
        except Exception:
            _LOGGER.warning("Could not read automations.yaml, starting fresh")

    # Check which of ours already exist
    existing_ids = {a.get("id", "") for a in existing if isinstance(a, dict)}
    templates = get_automation_templates()

    added = 0
    for template in templates:
        if template["id"] not in existing_ids:
            existing.append(template)
            added += 1
            _LOGGER.info("Adding automation: %s", template["alias"])

    if added > 0:
        # Write back
        content = yaml.dump(existing, default_flow_style=False, allow_unicode=True, sort_keys=False)
        await hass.async_add_executor_job(automations_path.write_text, content)

        # Reload automations so they appear immediately
        await hass.services.async_call("automation", "reload")
        _LOGGER.info("Created %d Boiler Room voice automations", added)
    else:
        _LOGGER.info("All Boiler Room voice automations already exist")

    return added
