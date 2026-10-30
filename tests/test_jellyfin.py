import unittest

from yarl import URL

from core.jellyfin import (
    BROWSE_TYPES_DEFAULT,
    SEARCH_TYPES_DEFAULT,
    auth_headers,
    pick_session,
    play_params,
    search_params,
    view_params,
)


class ParamBuildersTest(unittest.TestCase):
    def test_search_defaults(self):
        self.assertEqual(
            search_params("fargo"),
            {"searchTerm": "fargo", "Limit": "5", "Recursive": "true",
             "IncludeItemTypes": SEARCH_TYPES_DEFAULT},
        )

    def test_search_type_override(self):
        self.assertEqual(search_params("fargo", "Movie", 1)["IncludeItemTypes"], "Movie")
        self.assertEqual(search_params("x", BROWSE_TYPES_DEFAULT)["IncludeItemTypes"], BROWSE_TYPES_DEFAULT)

    def test_query_with_reserved_characters_survives_encoding(self):
        # The old code interpolated the query into the URL string, so
        # "Tom & Jerry" became two query parameters. aiohttp encodes params.
        url = URL("http://jf/Items").with_query(search_params("Tom & Jerry #1?"))
        self.assertEqual(url.query["searchTerm"], "Tom & Jerry #1?")
        self.assertIn("%26", str(url))
        self.assertNotIn("& Jerry", str(url))

    def test_view_params(self):
        item = {"Id": "abc", "Type": "Series", "Name": "Taskmaster & Friends"}
        self.assertEqual(view_params(item), {"itemType": "Series", "itemId": "abc", "itemName": "Taskmaster & Friends"})

    def test_play_params(self):
        self.assertEqual(play_params("abc"), {"ItemIds": "abc", "PlayCommand": "PlayNow"})

    def test_auth_header(self):
        self.assertEqual(auth_headers("k3y"), {"Authorization": 'MediaBrowser Token="k3y"'})


class PickSessionTest(unittest.TestCase):
    def test_prefers_jellyfin_client_over_other_controllable(self):
        sessions = [
            {"Id": "phone", "Client": "Jellyfin Android", "Capabilities": {"SupportsMediaControl": True}},
            {"Id": "web", "Client": "Jellyfin Web", "Capabilities": {"SupportsMediaControl": False}},
            {"Id": "deck", "Client": "Jellyfin Media Player", "Capabilities": {"SupportsMediaControl": True}},
        ]
        # First controllable Jellyfin client wins (documented limitation:
        # the phone can win; filtering by device is a follow-up).
        self.assertEqual(pick_session(sessions), "phone")

    def test_falls_back_to_any_controllable(self):
        sessions = [
            {"Id": "a", "Client": "Kodi", "Capabilities": {"SupportsMediaControl": True}},
        ]
        self.assertEqual(pick_session(sessions), "a")

    def test_none_when_nothing_controllable(self):
        self.assertIsNone(pick_session([{"Id": "a", "Client": "x", "Capabilities": {}}]))
        self.assertIsNone(pick_session([]))


if __name__ == "__main__":
    unittest.main()
