import unittest

from core.remote import REPEAT_INTERVAL, VolumeGate, parse_event


class ParseEventTest(unittest.TestCase):
    def test_well_formed(self):
        self.assertEqual(parse_event({"button": "volume_up", "action": "press"}), ("volume_up", "press"))

    def test_rejects_malformed(self):
        for data in (None, [], {}, {"button": "volume_up"}, {"button": "", "action": "press"},
                     {"button": "volume_up", "action": "hold"}, {"button": 3, "action": "press"}):
            self.assertIsNone(parse_event(data), data)


class VolumeGateTest(unittest.TestCase):
    def test_press_always_acts(self):
        gate = VolumeGate()
        self.assertEqual(gate.service_for("volume_up", "press", 0.0), "volume_up")
        self.assertEqual(gate.service_for("volume_up", "press", 0.01), "volume_up")
        self.assertEqual(gate.service_for("volume_down", "press", 0.02), "volume_down")

    def test_release_and_unknown_buttons_do_nothing(self):
        gate = VolumeGate()
        self.assertIsNone(gate.service_for("volume_up", "release", 0.0))
        self.assertIsNone(gate.service_for("ok", "press", 0.0))

    def test_held_key_steps_once_per_interval(self):
        """30 repeats a second for one second come out as about 1/interval steps."""
        gate = VolumeGate()
        steps = [gate.service_for("volume_up", "press", 0.0)]
        t = 0.25  # kernel repeat delay
        while t < 1.25:
            steps.append(gate.service_for("volume_up", "repeat", t))
            t += 1 / 30
        acted = [s for s in steps if s]
        self.assertEqual(acted[0], "volume_up")
        self.assertAlmostEqual(len(acted), 1 + 1 / REPEAT_INTERVAL, delta=1.5)

    def test_buttons_are_throttled_separately(self):
        gate = VolumeGate()
        gate.service_for("volume_up", "press", 0.0)
        self.assertEqual(gate.service_for("volume_down", "repeat", 0.05), "volume_down")

    def test_mute_acts_on_press_only(self):
        gate = VolumeGate()
        self.assertEqual(gate.service_for("volume_mute", "press", 0.0), "volume_mute")
        self.assertIsNone(gate.service_for("volume_mute", "repeat", 5.0))


if __name__ == "__main__":
    unittest.main()
