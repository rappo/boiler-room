"""Intent handlers for Boiler Room voice commands."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# Default game aliases — common abbreviations that voice assistants might hear
DEFAULT_ALIASES: dict[str, str] = {
    "bg3": "Baldur's Gate 3",
    "baldurs gate": "Baldur's Gate 3",
    "cyberpunk": "Cyberpunk 2077",
    "rdr2": "Red Dead Redemption 2",
    "red dead": "Red Dead Redemption 2",
    "gta": "Grand Theft Auto V",
    "gta5": "Grand Theft Auto V",
    "elden ring": "ELDEN RING",
    "skyrim": "The Elder Scrolls V: Skyrim",
    "witcher": "The Witcher 3: Wild Hunt",
    "botw": "The Legend of Zelda: Breath of the Wild",
    "totk": "The Legend of Zelda: Tears of the Kingdom",
    "ff7": "FINAL FANTASY VII REMAKE",
    "ds3": "DARK SOULS III",
    "hollow knight": "Hollow Knight",
    "stardew": "Stardew Valley",
    "terraria": "Terraria",
    "valheim": "Valheim",
    "satisfactory": "Satisfactory",
    "factorio": "Factorio",
    "rimworld": "RimWorld",
    "civ": "Sid Meier's Civilization VI",
    "civ6": "Sid Meier's Civilization VI",
    "portal": "Portal 2",
    "half life": "Half-Life 2",
    "dota": "Dota 2",
    "cs": "Counter-Strike 2",
    "csgo": "Counter-Strike 2",
    "apex": "Apex Legends",
}


def fuzzy_match_game(
    query: str,
    games: list[dict[str, Any]],
    aliases: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Find the best matching game for a voice query.

    Match priority:
    1. Exact alias match
    2. Exact name match (case-insensitive)
    3. Substring match (prefer shorter names = more specific)
    4. Word-boundary matching
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    # Merge default aliases with user-configured aliases
    all_aliases = {**DEFAULT_ALIASES}
    if aliases:
        all_aliases.update(aliases)

    # 1. Check aliases first
    if query_lower in all_aliases:
        alias_target = all_aliases[query_lower].lower()
        for game in games:
            if game.get("name", "").lower() == alias_target:
                return game

    # 2. Exact name match
    for game in games:
        if game.get("name", "").lower() == query_lower:
            return game

    # 3. Substring match
    substring_matches = []
    for game in games:
        name = game.get("name", "").lower()
        if query_lower in name:
            substring_matches.append(game)

    if len(substring_matches) == 1:
        return substring_matches[0]
    if len(substring_matches) > 1:
        # Return shortest name (most specific)
        return min(substring_matches, key=lambda g: len(g.get("name", "")))

    # 4. Word-boundary matching — check if all query words appear in the name
    query_words = query_lower.split()
    for game in games:
        name_lower = game.get("name", "").lower()
        if all(word in name_lower for word in query_words):
            return game

    return None


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register intent handlers for Boiler Room voice commands."""
    intent.async_register(hass, BoilerRoomLaunchGameIntent())
    intent.async_register(hass, BoilerRoomOpenAppIntent())
    intent.async_register(hass, BoilerRoomSystemControlIntent())
    _LOGGER.info("Boiler Room voice command intents registered")


class BoilerRoomLaunchGameIntent(intent.IntentHandler):
    """Handle the BoilerRoomLaunchGame intent.

    Searches games first, then falls back to apps (Flatpaks).
    This way 'launch Jellyfin' and 'launch Balatro' both work.
    """

    intent_type = "BoilerRoomLaunchGame"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        game_name = intent_obj.slots.get("game_name", {}).get("value", "")

        if not game_name:
            response = intent_obj.create_response()
            response.async_set_speech("I didn't catch the game name. What would you like to play?")
            return response

        # Find the first available Boiler Room device
        api, games, apps, aliases = _get_device_context(hass)
        if not api:
            response = intent_obj.create_response()
            response.async_set_speech("No SteamOS device is connected.")
            return response

        # 1. Try matching against Steam games
        game = fuzzy_match_game(game_name, games, aliases)
        if game:
            result = await api.launch(appid=game["appid"])
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Launching {game['name']}.")
            else:
                response.async_set_speech(
                    f"Failed to launch {game['name']}: {result.get('message', 'unknown error')}"
                )
            return response

        # 2. Try matching against Flatpak apps
        app = _fuzzy_match_app(game_name, apps)
        if app:
            result = await api.launch(appid=app["id"], launch_type="app")
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Opening {app['name']}.")
            else:
                response.async_set_speech(
                    f"Failed to open {app['name']}: {result.get('message', 'unknown error')}"
                )
            return response

        # Nothing found
        response = intent_obj.create_response()
        response.async_set_speech(
            f"I couldn't find a game or app matching '{game_name}'. "
            f"You have {len(games)} games and {len(apps)} apps installed."
        )
        return response


class BoilerRoomOpenAppIntent(intent.IntentHandler):
    """Handle the BoilerRoomOpenApp intent.

    Searches apps first, then falls back to games.
    """

    intent_type = "BoilerRoomOpenApp"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        app_name = intent_obj.slots.get("app_name", {}).get("value", "")

        if not app_name:
            response = intent_obj.create_response()
            response.async_set_speech("Which app would you like to open?")
            return response

        api, games, apps, _ = _get_device_context(hass)
        if not api:
            response = intent_obj.create_response()
            response.async_set_speech("No SteamOS device is connected.")
            return response

        # 1. Try matching against Flatpak apps first
        app = _fuzzy_match_app(app_name, apps)
        if app:
            result = await api.launch(appid=app["id"], launch_type="app")
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Opening {app['name']}.")
            else:
                response.async_set_speech(
                    f"Failed to open {app['name']}: {result.get('message', 'unknown error')}"
                )
            return response

        # 2. Fall back to games
        game = fuzzy_match_game(app_name, games)
        if game:
            result = await api.launch(appid=game["appid"])
            response = intent_obj.create_response()
            if result.get("status") == "launching":
                response.async_set_speech(f"Launching {game['name']}.")
            else:
                response.async_set_speech(
                    f"Failed to launch {game['name']}: {result.get('message', 'unknown error')}"
                )
            return response

        # Nothing found
        response = intent_obj.create_response()
        response.async_set_speech(f"Couldn't find an app or game named {app_name}.")
        return response


class BoilerRoomSystemControlIntent(intent.IntentHandler):
    """Handle the BoilerRoomSystemControl intent."""

    intent_type = "BoilerRoomSystemControl"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        action = intent_obj.slots.get("action", {}).get("value", "").lower()
        volume = intent_obj.slots.get("volume", {}).get("value")

        api, _, _, _ = _get_device_context(hass)
        if not api:
            response = intent_obj.create_response()
            response.async_set_speech("No SteamOS device is connected.")
            return response

        response = intent_obj.create_response()

        if volume is not None:
            try:
                vol = int(volume)
                await api.set_volume(vol)
                response.async_set_speech(f"Volume set to {vol} percent.")
            except (ValueError, TypeError):
                response.async_set_speech("I didn't understand the volume level.")
        elif action in ("suspend", "sleep", "off", "turn off"):
            await api.power_action("suspend")
            response.async_set_speech("Suspending the SteamOS device.")
        elif action in ("shutdown", "shut down", "power off"):
            await api.power_action("shutdown")
            response.async_set_speech("Shutting down the SteamOS device.")
        elif action in ("reboot", "restart"):
            await api.power_action("reboot")
            response.async_set_speech("Rebooting the SteamOS device.")
        else:
            response.async_set_speech(f"I don't know the command '{action}'.")

        return response


def _fuzzy_match_app(
    query: str,
    apps: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Fuzzy match an app name against installed Flatpak apps."""
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    # Exact match
    for app in apps:
        if app.get("name", "").lower() == query_lower:
            return app

    # Substring match
    matches = [a for a in apps if query_lower in a.get("name", "").lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return min(matches, key=lambda a: len(a.get("name", "")))

    return None


def _get_device_context(
    hass: HomeAssistant,
) -> tuple[Any, list[dict], list[dict], dict[str, str] | None]:
    """Get the API client, game list, app list, and aliases from the first available device."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        api = entry_data.get("api")
        coordinator = entry_data.get("coordinator")
        if api and coordinator and coordinator.data:
            games = coordinator.data.get("games", [])
            apps = coordinator.data.get("apps", [])
            # Get user-configured aliases from options
            aliases = entry_data.get("aliases")
            return api, games, apps, aliases
    return None, [], [], None
