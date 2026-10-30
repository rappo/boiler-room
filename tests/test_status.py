import unittest

from core.status import summarize_recent, summarize_status

STATUS_PLAYING = {
    "power_state": "on",
    "state": "playing",
    "current_app": "Balatro",
    "current_app_type": "game",
    "gaming_mode": True,
    "version": "0.6.0",
}
SENSORS = {
    "cpu_temp": 61.4,
    "gpu_temp": 55.0,
    "ambient_temp": 0,
    "volume": 40,
    "battery_level": 80,
    "battery_charging": True,
    "disk": {"used_gb": 1},
}


class SummarizeStatusTest(unittest.TestCase):
    def test_running_a_game_with_every_sensor(self):
        speech, data = summarize_status("deck", STATUS_PLAYING, SENSORS)
        self.assertEqual(
            speech,
            "deck is on and running the game Balatro. CPU 61°C, GPU 55°C. "
            "Volume 40 percent. Battery 80 percent, charging.",
        )
        self.assertEqual(data["device"], "deck")
        self.assertEqual(data["current_app"], "Balatro")
        self.assertEqual(data["battery_level"], 80)
        self.assertNotIn("version", data)
        self.assertNotIn("disk", data)

    def test_idle_without_a_battery(self):
        speech, data = summarize_status(
            "deck", {"power_state": "on", "state": "idle"}, {"cpu_temp": 50.0, "battery_level": -1}
        )
        self.assertEqual(speech, "deck is on and idle. CPU 50°C.")
        self.assertNotIn("battery_level", data)
        self.assertNotIn("battery_charging", data)

    def test_persisted_power_state_only(self):
        speech, data = summarize_status("deck", {"power_state": "sleep"}, None)
        self.assertEqual(speech, "deck is in sleep state.")
        self.assertEqual(data, {"device": "deck", "power_state": "sleep"})

    def test_never_reached(self):
        speech, data = summarize_status("deck", None, None)
        self.assertEqual(speech, "deck has not been reached yet.")
        self.assertEqual(data, {"device": "deck"})

    def test_zero_temperature_is_not_a_reading(self):
        speech, _ = summarize_status("deck", {"power_state": "on"}, {"cpu_temp": 0, "gpu_temp": 0})
        self.assertEqual(speech, "deck is on and idle.")


class SummarizeRecentTest(unittest.TestCase):
    ITEMS = (
        {"name": "Balatro", "id": "2379780", "type": "game", "timestamp": 1761800000},
        {"name": "Firefox", "id": "org.mozilla.firefox", "type": "app", "timestamp": 1761790000},
    )

    def test_lists_newest_first_with_types(self):
        speech, data = summarize_recent("deck", self.ITEMS)
        self.assertEqual(speech, "Recently launched on deck: Balatro (game), Firefox (app).")
        self.assertEqual(data["device"], "deck")
        self.assertEqual([item["id"] for item in data["recent"]], ["2379780", "org.mozilla.firefox"])

    def test_limit(self):
        items = [{"name": f"g{i}", "id": str(i), "type": "game"} for i in range(20)]
        _, data = summarize_recent("deck", items, limit=3)
        self.assertEqual(len(data["recent"]), 3)

    def test_empty(self):
        speech, data = summarize_recent("deck", [])
        self.assertEqual(speech, "Nothing has been launched on deck yet.")
        self.assertEqual(data["recent"], [])


if __name__ == "__main__":
    unittest.main()
