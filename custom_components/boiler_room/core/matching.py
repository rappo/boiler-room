"""Pure matching logic: game/app fuzzy matching and alias parsing.

No Home Assistant imports here on purpose, so this module is unit-testable
without an HA install (see tests/).
"""

from __future__ import annotations

import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Default game aliases: common abbreviations that voice assistants might hear.
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

# Minimum similarity for the edit-distance fallback. Below this the query is
# treated as not matching anything rather than launching a random game.
MIN_GAME_SIMILARITY = 0.75


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
    4. All query words present in the name
    5. Edit distance (handles STT errors like 'crap' vs 'crab')
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    all_aliases = {**DEFAULT_ALIASES, **(aliases or {})}

    if query_lower in all_aliases:
        alias_target = all_aliases[query_lower].lower()
        for game in games:
            if game.get("name", "").lower() == alias_target:
                return game

    for game in games:
        if game.get("name", "").lower() == query_lower:
            return game

    substring_matches = [
        game for game in games if query_lower in game.get("name", "").lower()
    ]
    if substring_matches:
        return min(substring_matches, key=lambda g: len(g.get("name", "")))

    query_words = query_lower.split()
    for game in games:
        name_lower = game.get("name", "").lower()
        if all(word in name_lower for word in query_words):
            return game

    best_match = None
    best_ratio = 0.0
    for game in games:
        ratio = similarity_ratio(query_lower, game.get("name", "").lower())
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = game

    if best_match and best_ratio >= MIN_GAME_SIMILARITY:
        _LOGGER.info(
            "Edit-distance matched '%s' -> '%s' (%.0f%%)",
            query, best_match.get("name"), best_ratio * 100,
        )
        return best_match

    return None


def similarity_ratio(a: str, b: str) -> float:
    """Similarity between two strings from Levenshtein distance, 0.0 to 1.0."""
    if a == b:
        return 1.0
    len_a, len_b = len(a), len(b)
    if not len_a or not len_b:
        return 0.0

    max_len = max(len_a, len_b)
    if abs(len_a - len_b) / max_len > 0.5:
        return 0.0

    row = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        prev = row[0]
        row[0] = i
        for j in range(1, len_b + 1):
            temp = row[j]
            if a[i - 1] == b[j - 1]:
                row[j] = prev
            else:
                row[j] = 1 + min(prev, row[j], row[j - 1])
            prev = temp

    return 1.0 - (row[len_b] / max_len)


def fuzzy_match_app(
    query: str,
    apps: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Match an app name against installed Flatpak apps (exact, then substring)."""
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    for app in apps:
        if app.get("name", "").lower() == query_lower:
            return app

    matches = [a for a in apps if query_lower in a.get("name", "").lower()]
    if matches:
        return min(matches, key=lambda a: len(a.get("name", "")))

    return None


_ALIAS_SEPARATORS = re.compile(r"[,\n]")


def parse_app_aliases(raw: str) -> dict[str, str]:
    """Parse the app-alias option text into {spoken name: flatpak id}.

    Accepts "name=id" pairs separated by commas or newlines (the options
    dialog promises both). Keys are lowercased; blank or malformed pairs
    are skipped.
    """
    aliases: dict[str, str] = {}
    for pair in _ALIAS_SEPARATORS.split(raw or ""):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        key, val = key.strip().lower(), val.strip()
        if key and val:
            aliases[key] = val
    return aliases
