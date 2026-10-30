import unittest

from core.matching import (
    fuzzy_match_app,
    fuzzy_match_game,
    parse_app_aliases,
    similarity_ratio,
)

GAMES = [
    {"appid": "1086940", "name": "Baldur's Gate 3"},
    {"appid": "1091500", "name": "Cyberpunk 2077"},
    {"appid": "2379780", "name": "Balatro"},
    {"appid": "413150", "name": "Stardew Valley"},
    {"appid": "1145360", "name": "Hades"},
    {"appid": "1145350", "name": "Hades II"},
]


def names(games):
    return [g["name"] for g in games]


class FuzzyMatchGameTest(unittest.TestCase):
    def test_alias_beats_everything(self):
        self.assertEqual(fuzzy_match_game("bg3", GAMES)["name"], "Baldur's Gate 3")

    def test_user_alias_overrides_default(self):
        got = fuzzy_match_game("bg3", GAMES, {"bg3": "Balatro"})
        self.assertEqual(got["name"], "Balatro")

    def test_exact_is_case_insensitive(self):
        self.assertEqual(fuzzy_match_game("BALATRO", GAMES)["appid"], "2379780")

    def test_substring_prefers_shortest_name(self):
        # "hades" is a substring of both Hades and Hades II
        self.assertEqual(fuzzy_match_game("hades", GAMES)["name"], "Hades")

    def test_all_words_present(self):
        self.assertEqual(fuzzy_match_game("valley stardew", GAMES)["name"], "Stardew Valley")

    def test_edit_distance_catches_stt_typo(self):
        self.assertEqual(fuzzy_match_game("balatroo", GAMES)["name"], "Balatro")

    def test_far_off_query_matches_nothing(self):
        self.assertIsNone(fuzzy_match_game("minecraft", GAMES))

    def test_empty_query(self):
        self.assertIsNone(fuzzy_match_game("   ", GAMES))


class SimilarityRatioTest(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(similarity_ratio("abc", "abc"), 1.0)

    def test_empty(self):
        self.assertEqual(similarity_ratio("", "abc"), 0.0)

    def test_one_edit(self):
        self.assertAlmostEqual(similarity_ratio("crab", "crap"), 0.75)

    def test_length_gate(self):
        # More than 50% length difference short-circuits to 0
        self.assertEqual(similarity_ratio("ab", "abcdefgh"), 0.0)


class FuzzyMatchAppTest(unittest.TestCase):
    APPS = [
        {"id": "org.mozilla.firefox", "name": "Firefox"},
        {"id": "org.jellyfin.JellyfinDesktop", "name": "Jellyfin Desktop"},
        {"id": "com.github.iwalton3.jellyfin-media-player", "name": "Jellyfin Media Player"},
    ]

    def test_exact(self):
        self.assertEqual(fuzzy_match_app("firefox", self.APPS)["id"], "org.mozilla.firefox")

    def test_substring_shortest(self):
        self.assertEqual(fuzzy_match_app("jellyfin", self.APPS)["name"], "Jellyfin Desktop")

    def test_none(self):
        self.assertIsNone(fuzzy_match_app("chrome", self.APPS))


class ParseAppAliasesTest(unittest.TestCase):
    def test_comma_separated(self):
        got = parse_app_aliases("youtube=rocks.shy.VacuumTube, browser=org.mozilla.firefox")
        self.assertEqual(got, {"youtube": "rocks.shy.VacuumTube", "browser": "org.mozilla.firefox"})

    def test_newline_separated_as_the_dialog_promises(self):
        got = parse_app_aliases("YouTube=rocks.shy.VacuumTube\nBrowser = org.mozilla.firefox\n")
        self.assertEqual(got, {"youtube": "rocks.shy.VacuumTube", "browser": "org.mozilla.firefox"})

    def test_garbage_is_skipped(self):
        self.assertEqual(parse_app_aliases("nonsense, =x, y=, ok=a.b.c"), {"ok": "a.b.c"})

    def test_empty(self):
        self.assertEqual(parse_app_aliases(""), {})
        self.assertEqual(parse_app_aliases(None), {})


if __name__ == "__main__":
    unittest.main()
