from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .services.lyrics_service import normalize_search_text, parse_artist_title_query, search_candidates


def _lrclib_item(
    *,
    track_id: int,
    title: str,
    artist: str,
    album: str = "",
    plain_lyrics: str = "",
    synced_lyrics: str = "",
) -> dict:
    return {
        "id": track_id,
        "trackName": title,
        "artistName": artist,
        "albumName": album,
        "duration": 355,
        "instrumental": False,
        "plainLyrics": plain_lyrics,
        "syncedLyrics": synced_lyrics,
    }


class LyricsSearchServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_normalize_search_text_handles_spacing_dash_and_parentheses(self):
        self.assertEqual(
            normalize_search_text('  Shape   of You \u2014 "Live"  '),
            "shape of you - live",
        )
        self.assertEqual(
            normalize_search_text("Song Title (Remastered 2011)", strip_parenthetical=True),
            "song title",
        )

    def test_parse_artist_title_query_supports_dash_variants(self):
        self.assertEqual(
            parse_artist_title_query("Queen \u2014 Bohemian Rhapsody"),
            {"artist": "Queen", "track_name": "Bohemian Rhapsody"},
        )
        self.assertIsNone(parse_artist_title_query("AC-DC Thunderstruck"))

    @patch("core.services.lyrics_service._lrclib.search")
    def test_fuzzy_ranking_prefers_relevant_song(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(
                track_id=1,
                title="Bohemian Rhapsody",
                artist="Queen",
                plain_lyrics="Is this the real life? Is this just fantasy?",
            ),
            _lrclib_item(
                track_id=2,
                title="Random Song",
                artist="Another Artist",
                plain_lyrics="Completely unrelated words here",
            ),
        ]

        results = search_candidates(q="bohem rapsody", artist=None, limit=2)

        self.assertEqual(results[0]["title"], "Bohemian Rhapsody")
        self.assertGreater(results[0]["score"], results[1]["score"])

    @patch("core.services.lyrics_service._lrclib.search")
    def test_deduplication_uses_normalized_artist_and_title(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(track_id=10, title="Numb (Remastered)", artist="Linkin Park"),
            _lrclib_item(
                track_id=11,
                title="Numb",
                artist="  linkin   park ",
                plain_lyrics="I've become so numb, I can't feel you there",
            ),
        ]

        results = search_candidates(q="linkin park numb", artist=None, limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], 11)
        self.assertTrue(results[0]["has_plain"])

    @patch("core.services.lyrics_service._lrclib.search")
    def test_fallback_search_tries_multiple_variants_after_empty_first_result(self, mock_search):
        calls = {"count": 0}

        def fake_search(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return []
            if calls["count"] == 2:
                return [
                    _lrclib_item(
                        track_id=21,
                        title="Shape of You",
                        artist="Ed Sheeran",
                        plain_lyrics="I'm in love with the shape of you",
                    )
                ]
            return []

        mock_search.side_effect = fake_search

        results = search_candidates(q="Shape of Yu (Live)", artist=None, limit=1)

        self.assertEqual(results[0]["title"], "Shape of You")
        self.assertGreaterEqual(mock_search.call_count, 2)
        self.assertEqual(mock_search.call_args_list[0].kwargs["query"], "Shape of Yu (Live)")
        self.assertNotEqual(
            mock_search.call_args_list[1].kwargs["query"],
            mock_search.call_args_list[0].kwargs["query"],
        )

    @patch("core.services.lyrics_service._lrclib.search")
    def test_artist_title_query_prioritizes_artist_match_for_queen_bohem(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(track_id=31, title="Bohem", artist="Dipnot"),
            _lrclib_item(track_id=32, title="Bohém", artist="Nerieš"),
            _lrclib_item(track_id=33, title="Bohemian Rhapsody", artist="Queen"),
        ]

        results = search_candidates(q="queen - bohem", artist=None, limit=5)

        self.assertEqual(results[0]["title"], "Bohemian Rhapsody")
        self.assertEqual(results[0]["artist"], "Queen")
        self.assertTrue(all(result["artist"] == "Queen" for result in results))

    @patch("core.services.lyrics_service._lrclib.search")
    def test_artist_title_query_prefers_ed_sheeran_shape(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(track_id=41, title="Shape of You", artist="Ed Sheeran"),
            _lrclib_item(track_id=42, title="Shape", artist="Sugababes"),
            _lrclib_item(track_id=43, title="Shape of My Heart", artist="Sting"),
        ]

        results = search_candidates(q="ed sheeran - shape", artist=None, limit=5)

        self.assertEqual(results[0]["title"], "Shape of You")
        self.assertEqual(results[0]["artist"], "Ed Sheeran")
        self.assertTrue(all(result["artist"] == "Ed Sheeran" for result in results))

    @patch("core.services.lyrics_service._lrclib.search")
    def test_artist_title_query_keeps_green_day_above_title_match_other_artist(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(
                track_id=51,
                title="Boulevard of Broken Dreams",
                artist="Green Day",
                plain_lyrics="I walk a lonely road, the only one that I have ever known",
            ),
            _lrclib_item(
                track_id=52,
                title="Lonely Road",
                artist="Some Other Artist",
                plain_lyrics="A lonely road with no direction home",
            ),
        ]

        results = search_candidates(q="green day - lonely road", artist=None, limit=5)

        self.assertEqual(results[0]["artist"], "Green Day")
        self.assertEqual(results[0]["title"], "Boulevard of Broken Dreams")
        self.assertTrue(all(result["artist"] == "Green Day" for result in results))

    @patch("core.services.lyrics_service._lrclib.search")
    def test_query_without_artist_remains_broad(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(track_id=61, title="Bohem", artist="Dipnot"),
            _lrclib_item(track_id=62, title="Bohemian Rhapsody", artist="Queen"),
        ]

        results = search_candidates(q="bohem", artist=None, limit=5)

        self.assertEqual(len(results), 2)
        self.assertEqual({result["artist"] for result in results}, {"Dipnot", "Queen"})


class SearchViewTests(TestCase):
    @patch("core.views.search_candidates")
    def test_search_page_shows_recognized_artist_title_and_empty_hint(self, mock_search_candidates):
        mock_search_candidates.return_value = []

        response = self.client.get(reverse("search"), {"q": "Queen - Bohem"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Распознано как:")
        self.assertContains(response, "Queen")
        self.assertContains(response, "Bohem")
        self.assertContains(
            response,
            "Ничего не найдено. Попробуйте указать исполнителя или часть строки из песни.",
        )
