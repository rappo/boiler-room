import unittest

from core.wol import magic_packet, normalize_mac


class WolTest(unittest.TestCase):
    def test_normalize_accepts_common_separators(self):
        for mac in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff", " aabbccddeeff "):
            self.assertEqual(normalize_mac(mac), "aabbccddeeff")

    def test_normalize_rejects_garbage(self):
        for mac in ("", "aa:bb:cc", "zz:bb:cc:dd:ee:ff", "aabbccddeeff00"):
            with self.assertRaises(ValueError):
                normalize_mac(mac)

    def test_packet_layout(self):
        packet = magic_packet("01:23:45:67:89:ab")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:], bytes.fromhex("0123456789ab") * 16)


if __name__ == "__main__":
    unittest.main()
