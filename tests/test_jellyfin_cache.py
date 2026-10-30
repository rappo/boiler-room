import unittest

from core.jellyfin_cache import JellyfinMediaCache, _normalize, _normalize_joined


def make_cache(items):
    cache = JellyfinMediaCache(session=None, jf_url="http://jf/", jf_key="k")
    cache.ingest(items, replace=True)
    return cache


LIBRARY = [
    {"Id": "1", "Name": "deadmau5", "Type": "MusicArtist"},
    {"Id": "2", "Name": "Gorillaz", "Type": "MusicArtist"},
    {"Id": "3", "Name": "Mötley Crüe", "Type": "MusicArtist"},
    {"Id": "4", "Name": "Nine Inch Noize", "Type": "MusicArtist"},
    {"Id": "5", "Name": "Abbey Road", "Type": "MusicAlbum"},
    {"Id": "", "Name": "no id", "Type": "MusicAlbum"},
    {"Id": "6", "Name": "", "Type": "MusicAlbum"},
]


class NormalizeTest(unittest.TestCase):
    def test_accents_and_case(self):
        self.assertEqual(_normalize("Mötley Crüe"), "motley crue")

    def test_leet(self):
        self.assertEqual(_normalize("deadmau5"), "deadmaus")

    def test_joined(self):
        self.assertEqual(_normalize_joined("Dead Mouse"), "deadmouse")


class CacheMatchTest(unittest.TestCase):
    def setUp(self):
        self.cache = make_cache(LIBRARY)

    def test_ingest_skips_items_without_id_or_name(self):
        self.assertEqual(self.cache.item_count, 5)

    def test_stt_mangled_names_resolve(self):
        for heard, want in (
            ("dead mouse", "deadmau5"),
            ("gorillas", "Gorillaz"),
            ("motley crew", "Mötley Crüe"),
            ("nine inch noise", "Nine Inch Noize"),
        ):
            with self.subTest(heard=heard):
                self.assertEqual(self.cache.match_or_query(heard)[0], want)

    def test_unknown_query_passes_through(self):
        self.assertEqual(self.cache.match_or_query("xylophone concerto"), ("xylophone concerto", None))

    def test_type_filter(self):
        self.assertIsNone(self.cache.match("abbey road", item_types=["MusicArtist"]))
        self.assertEqual(self.cache.match("abbey road", item_types=["MusicAlbum"]).id, "5")

    def test_replace_vs_append(self):
        self.cache.ingest([{"Id": "9", "Name": "New", "Type": "MusicAlbum"}])
        self.assertEqual(self.cache.item_count, 6)
        self.cache.ingest([{"Id": "9", "Name": "New", "Type": "MusicAlbum"}], replace=True)
        self.assertEqual(self.cache.item_count, 1)


if __name__ == "__main__":
    unittest.main()
