import unittest

from core.sentences import (
    DEFAULT_NICKNAMES,
    HANDLER_AMBIGUOUS_DEVICE,
    HANDLER_JELLYFIN_BROWSE,
    HANDLER_JELLYFIN_CONTROL,
    HANDLER_JELLYFIN_PLAY,
    HANDLER_LAUNCH_APP,
    HANDLER_LAUNCH_GAME,
    HANDLER_POWER,
    HANDLER_SET_VOLUME,
    HANDLER_WAKE,
    HANDLER_YOUTUBE_SEARCH,
    HANDLERS,
    SLOT_TO_KWARG,
    Command,
    build_commands,
    by_template,
    clean_nickname,
    default_nicknames,
    handler_arguments,
    match_device,
    nicknames_text,
    parse_nicknames,
    split_shared_nicknames,
    templates,
)

try:
    from hassil.expression import Group, ListReference
    from hassil.intents import Intents, WildcardSlotList
    from hassil.recognize import recognize_all
except ImportError:  # pragma: no cover - CI installs hassil
    recognize_all = None


ONE = {"entry_a": ["steamdeck", "deck", "steam machine", "gaming pc"]}
TWO = {
    "entry_a": ["steamdeck", "deck", "steam machine", "gaming pc"],
    "entry_b": ["living room pc", "deck", "steam machine", "gaming pc"],
}


class NicknameTest(unittest.TestCase):
    def test_default_set_is_stable(self):
        self.assertEqual(DEFAULT_NICKNAMES, ("deck", "steam machine", "gaming pc"))

    def test_default_nicknames_start_with_the_device_name(self):
        self.assertEqual(
            default_nicknames("SteamDeck"),
            ["steamdeck", "deck", "steam machine", "gaming pc"],
        )

    def test_default_nicknames_dedupe_a_device_called_deck(self):
        self.assertEqual(default_nicknames("Deck"), ["deck", "steam machine", "gaming pc"])

    def test_default_nicknames_without_a_name(self):
        self.assertEqual(default_nicknames(None), list(DEFAULT_NICKNAMES))

    def test_parse_accepts_commas_and_newlines(self):
        got = parse_nicknames("Deck, Living Room PC\n tv ,, deck")
        self.assertEqual(got, ["deck", "living room pc", "tv"])

    def test_parse_strips_template_syntax(self):
        self.assertEqual(parse_nicknames("deck (living room) | {x}"), ["deck living room x"])
        self.assertEqual(clean_nickname("  Big   TV "), "big tv")

    def test_parse_empty(self):
        self.assertEqual(parse_nicknames(""), [])
        self.assertEqual(parse_nicknames(None), [])

    def test_text_round_trips(self):
        nicks = default_nicknames("steamdeck")
        self.assertEqual(parse_nicknames(nicknames_text(nicks)), nicks)


class SharedNicknameTest(unittest.TestCase):
    def test_single_device_shares_nothing(self):
        unique, shared = split_shared_nicknames(ONE)
        self.assertEqual(unique, ONE)
        self.assertEqual(shared, [])

    def test_generic_nicknames_become_shared_with_two_devices(self):
        unique, shared = split_shared_nicknames(TWO)
        self.assertEqual(unique, {"entry_a": ["steamdeck"], "entry_b": ["living room pc"]})
        self.assertEqual(shared, ["deck", "steam machine", "gaming pc"])


class MatchDeviceTest(unittest.TestCase):
    NAMES = {
        "entry_a": ["steamdeck", "deck", "Steam Deck"],
        "entry_b": ["living room pc", "gaming pc"],
    }

    def test_exact_case_insensitive(self):
        self.assertEqual(match_device("Living Room PC", self.NAMES), "entry_b")

    def test_substring(self):
        self.assertEqual(match_device("living room", self.NAMES), "entry_b")

    def test_ambiguous_substring_is_none(self):
        self.assertIsNone(match_device("pc", {"a": ["gaming pc"], "b": ["living room pc"]}))

    def test_unknown_and_empty(self):
        self.assertIsNone(match_device("toaster", self.NAMES))
        self.assertIsNone(match_device("", self.NAMES))
        self.assertIsNone(match_device(None, self.NAMES))


class BuildCommandsTest(unittest.TestCase):
    def test_no_devices_no_sentences(self):
        self.assertEqual(build_commands({}), [])

    def test_every_handler_is_known_and_templates_are_unique(self):
        commands = build_commands(TWO)
        for command in commands:
            self.assertIn(command.handler, HANDLERS)
        by_template(commands)  # raises on duplicates
        self.assertEqual(len(templates(commands)), len(commands))

    def test_slots_match_handler_keywords(self):
        for command in build_commands(ONE):
            for slot in command.slots:
                self.assertIn(slot, SLOT_TO_KWARG, command.template)

    def test_single_device_gets_its_nicknames_inlined(self):
        commands = build_commands(ONE)
        device = [c for c in commands if c.entry_id == "entry_a"]
        self.assertTrue(device)
        for command in device:
            self.assertIn("(steamdeck|deck|steam machine|gaming pc)", command.template)
        self.assertFalse([c for c in commands if c.handler == HANDLER_AMBIGUOUS_DEVICE])

    def test_two_devices_route_by_unique_nickname_and_ask_on_shared(self):
        commands = build_commands(TWO)
        a = {c.template for c in commands if c.entry_id == "entry_a"}
        b = {c.template for c in commands if c.entry_id == "entry_b"}
        self.assertIn("(Suspend|Sleep) [the] (steamdeck)", a)
        self.assertIn("(Suspend|Sleep) [the] (living room pc)", b)
        ambiguous = [c for c in commands if c.handler == HANDLER_AMBIGUOUS_DEVICE]
        self.assertIn(
            "(Suspend|Sleep) [the] (deck|steam machine|gaming pc)",
            [c.template for c in ambiguous],
        )
        for command in ambiguous:
            self.assertIsNone(command.entry_id)

    def test_generic_and_anchored_sentences_have_no_entry(self):
        commands = build_commands(ONE)
        generic = [c for c in commands if c.template == "Put on {game_name}"]
        self.assertEqual(len(generic), 1)
        self.assertIsNone(generic[0].entry_id)
        jellyfin = [c for c in commands if c.handler == HANDLER_JELLYFIN_PLAY]
        self.assertTrue(jellyfin)
        self.assertTrue(all(c.entry_id is None for c in jellyfin))

    def test_anchored_before_device_before_generic(self):
        commands = build_commands(ONE)
        first_device = next(i for i, c in enumerate(commands) if c.entry_id is not None)
        last_anchor = max(
            i for i, c in enumerate(commands)
            if c.handler in {HANDLER_JELLYFIN_PLAY, HANDLER_JELLYFIN_BROWSE,
                             HANDLER_JELLYFIN_CONTROL, HANDLER_YOUTUBE_SEARCH}
        )
        first_generic = commands.index(
            next(c for c in commands if c.template == "Put on {game_name}")
        )
        self.assertLess(last_anchor, first_device)
        self.assertLess(first_device, first_generic)


class HandlerArgumentsTest(unittest.TestCase):
    def test_static_params_plus_slots(self):
        command = Command("x {query}", HANDLER_JELLYFIN_PLAY, {"media_type": "Movie"})
        self.assertEqual(
            handler_arguments(command, {"query": " Fargo "}),
            {"media_type": "Movie", "query": "Fargo"},
        )

    def test_volume_becomes_int(self):
        command = Command("volume {volume}", HANDLER_SET_VOLUME)
        self.assertEqual(handler_arguments(command, {"volume": "50"}), {"level": 50})

    def test_bad_volume_raises(self):
        command = Command("volume {volume}", HANDLER_SET_VOLUME)
        with self.assertRaises(ValueError):
            handler_arguments(command, {"volume": "loud"})
        with self.assertRaises(ValueError):
            handler_arguments(command, {"volume": "150"})

    def test_missing_or_empty_slot_raises(self):
        command = Command("play {game_name}", HANDLER_LAUNCH_GAME)
        with self.assertRaises(ValueError):
            handler_arguments(command, {})
        with self.assertRaises(ValueError):
            handler_arguments(command, {"game_name": "  "})


@unittest.skipUnless(recognize_all, "hassil not installed")
class HassilMatchingTest(unittest.TestCase):
    """Match real sentences the way HA's default agent does.

    Mirrors ``DefaultAgent._rebuild_trigger_intents`` (HA 2026.10): one
    intent per trigger, every ``{slot}`` a wildcard, and the first match in
    template order wins.
    """

    @classmethod
    def setUpClass(cls):
        cls.commands = build_commands(TWO)
        cls.index = by_template(cls.commands)
        cls.intents = cls._intents_for(templates(cls.commands))

    @staticmethod
    def _intents_for(sentences):
        intents = Intents.from_dict(
            {"language": "en", "intents": {"BoilerRoom": {"data": [{"sentences": sentences}]}}}
        )
        names = set()

        def collect(expr):
            if isinstance(expr, ListReference):
                names.add(expr.list_name)
            elif isinstance(expr, Group):
                for item in expr.items:
                    collect(item)

        for intent in intents.intents.values():
            for data in intent.data:
                for sentence in data.sentences:
                    collect(sentence.expression)
        for name in names:
            intents.slot_lists[name] = WildcardSlotList(name)
        return intents

    def first_match(self, text):
        for result in recognize_all(text, self.intents):
            command = self.index[result.intent_sentence.text]
            slots = {k: v.value for k, v in result.entities.items()}
            return command, handler_arguments(command, slots)
        return None, None

    def assertRoutes(self, text, handler, entry_id, **kwargs):
        command, args = self.first_match(text)
        self.assertIsNotNone(command, f"no match for {text!r}")
        self.assertEqual((command.handler, command.entry_id), (handler, entry_id), text)
        self.assertEqual(args, kwargs, text)

    def test_every_template_parses(self):
        self._intents_for(templates(self.commands))

    def test_device_sentences_route_to_their_entry(self):
        self.assertRoutes("Suspend the steamdeck", HANDLER_POWER, "entry_a", action="suspend")
        self.assertRoutes("put the living room pc to sleep", HANDLER_POWER, "entry_b", action="suspend")
        self.assertRoutes("Wake up steamdeck", HANDLER_WAKE, "entry_a")
        self.assertRoutes("Reboot the living room PC", HANDLER_POWER, "entry_b", action="reboot")
        self.assertRoutes("Set the steamdeck volume to 50", HANDLER_SET_VOLUME, "entry_a", level=50)
        self.assertRoutes("Volume 20 on the living room pc", HANDLER_SET_VOLUME, "entry_b", level=20)
        self.assertRoutes("Play Balatro on the steamdeck", HANDLER_LAUNCH_GAME, "entry_a", name="Balatro")
        self.assertRoutes("Open the Firefox app on the living room pc", HANDLER_LAUNCH_APP, "entry_b", name="Firefox")

    def test_game_titles_containing_on_the(self):
        self.assertRoutes(
            "Play Attack on Titan on the steamdeck", HANDLER_LAUNCH_GAME, "entry_a", name="Attack on Titan"
        )

    def test_shared_nickname_asks_which_device(self):
        self.assertRoutes("Suspend the deck", HANDLER_AMBIGUOUS_DEVICE, None)
        self.assertRoutes("Play Balatro on the steam machine", HANDLER_AMBIGUOUS_DEVICE, None, name="Balatro")

    def test_jellyfin_beats_the_generic_launcher(self):
        self.assertRoutes("Play Robocop on Jellyfin", HANDLER_JELLYFIN_PLAY, None, query="Robocop")
        self.assertRoutes("Play the movie Fargo on Jellyfin", HANDLER_JELLYFIN_PLAY, None, query="Fargo", media_type="Movie")
        self.assertRoutes("Listen to the album Abbey Road in jelly fin", HANDLER_JELLYFIN_PLAY, None, query="Abbey Road", media_type="MusicAlbum")
        self.assertRoutes("Show me Taskmaster on Jellyfin", HANDLER_JELLYFIN_BROWSE, None, query="Taskmaster")
        self.assertRoutes("Look up the show Breaking Bad on Jellyfin", HANDLER_JELLYFIN_BROWSE, None, query="Breaking Bad", media_type="Series")

    def test_playback_controls(self):
        self.assertRoutes("Pause Jellyfin", HANDLER_JELLYFIN_CONTROL, None, action="pause")
        self.assertRoutes("Resume playback", HANDLER_JELLYFIN_CONTROL, None, action="unpause")
        self.assertRoutes("Stop the stream", HANDLER_JELLYFIN_CONTROL, None, action="stop")
        self.assertRoutes("Skip ahead Jellyfin", HANDLER_JELLYFIN_CONTROL, None, action="fastforward")

    def test_youtube(self):
        self.assertRoutes("Search YouTube for cat videos", HANDLER_YOUTUBE_SEARCH, None, query="cat videos")
        self.assertRoutes("Play lo-fi beats on YouTube", HANDLER_YOUTUBE_SEARCH, None, query="lo-fi beats")

    def test_generic_launcher_is_the_fallback(self):
        self.assertRoutes("Launch Elden Ring", HANDLER_LAUNCH_GAME, None, name="Elden Ring")
        self.assertRoutes("Put on Stardew Valley", HANDLER_LAUNCH_GAME, None, name="Stardew Valley")
        self.assertRoutes("Start the Jellyfin app", HANDLER_LAUNCH_APP, None, name="Jellyfin")
        self.assertRoutes("Set volume to 30", HANDLER_SET_VOLUME, None, level=30)

    def test_unrelated_sentence_does_not_match(self):
        self.assertEqual(self.first_match("Turn on the kitchen lights"), (None, None))
        self.assertEqual(self.first_match("What time is it"), (None, None))


if __name__ == "__main__":
    unittest.main()
