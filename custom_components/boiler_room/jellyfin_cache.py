"""Jellyfin media cache with phonetic matching for voice commands.

STT engines normalize unusual spellings to real words — "deadmau5" becomes
"dead mouse", "Gorillaz" becomes "gorillas", "Noize" becomes "noise".  This
module caches the Jellyfin library (artists, albums, etc.) and matches voice
queries phonetically against the real catalog, so the correct item is found
regardless of how the STT engine transcribes it.

Cache refreshes incrementally — after the initial full fetch, only items
added or modified since the last sync are pulled (using Jellyfin's
MinDateLastSaved filter).
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Minimum similarity ratio to consider a phonetic match.
# 0.70 catches deadmau5↔dead mouse; raise to reduce false positives.
MIN_MATCH_RATIO = 0.70

# Common leet-speak / stylized substitutions.
# Applied during normalization so "deadmau5" becomes "deadmaus"
# (phonetically close to "deadmouse").
_LEET_MAP = str.maketrans({"5": "s", "3": "e", "0": "o", "1": "i", "4": "a"})


def _normalize(text: str) -> str:
    """Normalize text for phonetic comparison.

    - Decomposes unicode and strips accent marks (ö → o, é → e)
    - Lowercases
    - Expands common leet-speak digits (5→s, 3→e, 0→o, 1→i, 4→a)
    - Strips remaining non-alpha characters
    - Collapses whitespace
    """
    # Decompose unicode and strip combining marks (accents)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    # Expand leet-speak before stripping digits
    text = text.translate(_LEET_MAP)
    # Strip anything non-alpha/space
    text = re.sub(r"[^a-z\s]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_joined(text: str) -> str:
    """Normalize and remove all spaces (catches word-boundary differences)."""
    return _normalize(text).replace(" ", "")


class CachedItem:
    """A cached Jellyfin library item with pre-computed phonetic keys."""

    __slots__ = ("id", "name", "type", "normalized", "joined")

    def __init__(self, item_id: str, name: str, item_type: str) -> None:
        self.id = item_id
        self.name = name
        self.type = item_type
        self.normalized = _normalize(name)
        self.joined = _normalize_joined(name)

    def __repr__(self) -> str:
        return f"CachedItem({self.type}: {self.name!r})"


class JellyfinMediaCache:
    """Cache of Jellyfin library items for phonetic voice matching.

    Maintains a local cache of artist/album/movie/series names from
    Jellyfin, enabling phonetic matching against STT output that may
    mangle unusual spellings.
    """

    def __init__(
        self,
        jf_url: str,
        jf_key: str,
        cache_types: list[str] | None = None,
        refresh_minutes: int = 30,
    ) -> None:
        self.jf_url = jf_url.rstrip("/")
        self.jf_key = jf_key
        self.cache_types = cache_types or ["MusicArtist", "MusicAlbum"]
        self.refresh_minutes = refresh_minutes

        self._items: dict[str, CachedItem] = {}  # keyed by Jellyfin item ID
        self._last_synced: datetime | None = None
        self._refresh_task: asyncio.Task | None = None
        self._running = False

    @property
    def item_count(self) -> int:
        """Number of items currently cached."""
        return len(self._items)

    @property
    def last_synced(self) -> datetime | None:
        """Timestamp of the last successful sync."""
        return self._last_synced

    # ─── Lifecycle ───

    async def start(self) -> None:
        """Start the cache — full initial fetch, then periodic incremental refresh."""
        if self._running:
            return
        self._running = True
        await self._fetch(full=True)
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        """Stop periodic refresh and clean up."""
        self._running = False
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

    async def _refresh_loop(self) -> None:
        """Periodically fetch new/modified items."""
        while self._running:
            await asyncio.sleep(self.refresh_minutes * 60)
            if not self._running:
                break
            try:
                await self._fetch(full=False)
            except Exception:
                _LOGGER.exception("Jellyfin cache incremental refresh failed")

    # ─── Fetch ───

    async def _fetch(self, full: bool = False) -> None:
        """Fetch items from Jellyfin.

        If full=True, clears the cache and fetches everything.
        Otherwise, only fetches items modified since the last sync.
        """
        include_types = ",".join(self.cache_types)
        params: dict[str, str] = {
            "IncludeItemTypes": include_types,
            "Recursive": "true",
            "Fields": "DateLastSaved",
            "Limit": "10000",
        }

        if not full and self._last_synced:
            params["MinDateLastSaved"] = self._last_synced.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        fetch_time = datetime.now(timezone.utc)
        headers = {"Authorization": f'MediaBrowser Token="{self.jf_key}"'}
        url = f"{self.jf_url}/Items"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning(
                            "Jellyfin cache fetch failed: HTTP %s", resp.status
                        )
                        return
                    data = await resp.json()
        except asyncio.TimeoutError:
            _LOGGER.warning("Jellyfin cache fetch timed out")
            return
        except Exception:
            _LOGGER.exception("Jellyfin cache fetch error")
            return

        items = data.get("Items", [])

        if full:
            self._items.clear()

        added = 0
        for item in items:
            item_id = item.get("Id", "")
            name = item.get("Name", "")
            item_type = item.get("Type", "")
            if item_id and name:
                self._items[item_id] = CachedItem(item_id, name, item_type)
                added += 1

        self._last_synced = fetch_time

        mode = "full" if full else "incremental"
        _LOGGER.info(
            "Jellyfin cache %s sync: %d items fetched, %d total cached",
            mode,
            added,
            len(self._items),
        )

    # ─── Matching ───

    def match(
        self,
        query: str,
        item_types: list[str] | None = None,
        threshold: float = MIN_MATCH_RATIO,
    ) -> CachedItem | None:
        """Find the best phonetic match for a voice query.

        Compares the query against all cached items using both
        spaced and joined normalization to handle word-boundary
        differences (e.g., "dead mouse" vs "deadmau5").

        Args:
            query: The STT-transcribed search text.
            item_types: Optional filter to specific Jellyfin item types.
            threshold: Minimum similarity ratio (0.0–1.0).

        Returns:
            The best matching CachedItem, or None if nothing meets the threshold.
        """
        if not self._items:
            return None

        query_norm = _normalize(query)
        query_joined = _normalize_joined(query)

        best_item: CachedItem | None = None
        best_ratio = threshold

        for item in self._items.values():
            if item_types and item.type not in item_types:
                continue

            # Compare both with-spaces and joined versions, take the best
            ratio = max(
                SequenceMatcher(None, query_norm, item.normalized).ratio(),
                SequenceMatcher(None, query_joined, item.joined).ratio(),
            )

            if ratio > best_ratio:
                best_ratio = ratio
                best_item = item

        if best_item:
            _LOGGER.debug(
                "Phonetic match: '%s' → '%s' (%.0f%% confidence)",
                query,
                best_item.name,
                best_ratio * 100,
            )

        return best_item

    def match_or_query(
        self,
        query: str,
        item_types: list[str] | None = None,
    ) -> tuple[str, str | None]:
        """Try phonetic match, return (search_term, item_id_or_none).

        If a strong match is found, returns the real name from the library
        and its Jellyfin ID. Otherwise returns the original query and None.
        This lets callers use the ID directly for playback (skipping search)
        or fall back to a regular Jellyfin search with the raw query.
        """
        matched = self.match(query, item_types)
        if matched:
            return matched.name, matched.id
        return query, None
