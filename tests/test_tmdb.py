import unittest
from unittest.mock import patch

from bot.helper.tmdb import FALLBACK_POSTER, fetch_metadata


class FetchMetadataTests(unittest.TestCase):
    def test_episode_caption_returns_direct_tmdb_and_episode_metadata(self):
        with patch("bot.helper.tmdb._request", return_value={}):
            metadata = fetch_metadata("262838/2/1")

        self.assertEqual(
            metadata,
            {
                "tmdb_id": 262838,
                "tmdb_type": "tv",
                "season": 2,
                "episode": 1,
                "poster_url": FALLBACK_POSTER,
            },
        )

    def test_non_episode_caption_has_empty_episode_fields_without_tmdb_key(self):
        with patch("bot.helper.tmdb.TMDB_API_KEY", ""):
            metadata = fetch_metadata("A normal file name")

        self.assertIsNone(metadata["season"])
        self.assertIsNone(metadata["episode"])


if __name__ == "__main__":
    unittest.main()
