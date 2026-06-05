import json
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import SearchHistory, SongTranslation, TelegramUser
from .services.ai_search_service import build_ai_search_queries
from .services.lyrics_service import normalize_search_text, parse_artist_title_query, search_candidates
from .services.search_history import normalize_history_query
from .services.translation_service import (
    TranslationServiceError,
    build_aligned_lines,
    hash_original_text,
    normalize_translated_lines,
    split_lyrics_lines,
    translate_lines_to_russian,
)


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


def _song_payload(song_id: int = 101, plain_lyrics: str = "I walk a lonely road\n\nThe only one that I have ever known") -> dict:
    return {
        "source": "lrclib",
        "id": song_id,
        "title": "Boulevard of Broken Dreams",
        "artist": "Green Day",
        "album": "American Idiot",
        "duration": 321,
        "instrumental": False,
        "plainLyrics": plain_lyrics,
        "syncedLyrics": "",
    }


class TranslationServiceTests(TestCase):
    def test_split_lyrics_lines_preserves_empty_lines(self):
        self.assertEqual(
            split_lyrics_lines("Line one\n\nLine two"),
            ["Line one", "", "Line two"],
        )

    @override_settings(TRANSLATION_PROVIDER="mock")
    def test_translate_lines_to_russian_returns_same_number_of_lines(self):
        source_lines = ["Line one", "", "Line two"]

        translated = translate_lines_to_russian(source_lines)

        self.assertEqual(len(translated), len(source_lines))
        self.assertEqual(translated[1], "")

    def test_normalize_translated_lines_matches_expected_length(self):
        self.assertEqual(normalize_translated_lines(["a"], 3), ["a", "", ""])

    @override_settings(TRANSLATION_PROVIDER="")
    def test_translate_lines_to_russian_raises_soft_error_when_provider_missing(self):
        with self.assertRaisesMessage(TranslationServiceError, "Перевод пока не настроен"):
            translate_lines_to_russian(["Line one"])

    @override_settings(TRANSLATION_PROVIDER="deepl", TRANSLATION_API_KEY="")
    def test_translate_lines_to_russian_requires_api_key_for_real_provider(self):
        with self.assertRaisesMessage(
            TranslationServiceError,
            "Переводчик не настроен: заполните TRANSLATION_API_KEY",
        ):
            translate_lines_to_russian(["Line one"])

    @override_settings(
        TRANSLATION_PROVIDER="openai",
        TRANSLATION_API_KEY="test-key",
        TRANSLATION_MODEL="gpt-4o-mini",
    )
    @patch("core.services.translation_service.requests.post")
    def test_translate_lines_to_russian_uses_openai_provider(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"x-request-id": "req_123"}
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '["Строка один", "", "Строка два"]',
                        }
                    ],
                }
            ]
        }
        mock_post.return_value = mock_response

        translated = translate_lines_to_russian(["Line one", "", "Line two"])

        self.assertEqual(translated, ["Строка один", "", "Строка два"])
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "gpt-4o-mini")
        self.assertIn("Return only valid JSON", mock_post.call_args.kwargs["json"]["instructions"])

    @override_settings(
        TRANSLATION_PROVIDER="openai",
        TRANSLATION_API_KEY="bad-key",
        TRANSLATION_MODEL="gpt-4o-mini",
    )
    @patch("core.services.translation_service.requests.post")
    def test_translate_lines_to_russian_reports_openai_auth_error(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.headers = {"x-request-id": "req_401"}
        mock_response.json.return_value = {"error": {"message": "Invalid API key"}}
        mock_post.return_value = mock_response

        with self.assertRaisesMessage(
            TranslationServiceError,
            "OpenAI API key отклонён. Проверьте TRANSLATION_API_KEY",
        ):
            translate_lines_to_russian(["Line one"])


class AISearchServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(AI_SEARCH_ENABLED=False, OPENAI_API_KEY="test-key")
    @patch("core.services.ai_search_service.requests.post")
    def test_ai_search_service_skips_openai_when_disabled(self, mock_post):
        plan = build_ai_search_queries("queen богемская рапсодия")

        self.assertEqual(plan["queries"], [])
        mock_post.assert_not_called()

    @override_settings(AI_SEARCH_ENABLED=True, OPENAI_API_KEY="test-key", OPENAI_SEARCH_MODEL="gpt-4o-mini")
    @patch("core.services.ai_search_service.requests.post")
    def test_ai_search_service_uses_cache(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "queries": ["Queen Bohemian Rhapsody", "Mama just killed a man"],
                                    "detected_artist": "Queen",
                                    "detected_title": "Bohemian Rhapsody",
                                    "confidence": 0.86,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            ]
        }
        mock_post.return_value = mock_response

        first = build_ai_search_queries("мама just killed a man queen")
        second = build_ai_search_queries("мама just killed a man queen")

        self.assertEqual(first["detected_artist"], "Queen")
        self.assertEqual(second["detected_title"], "Bohemian Rhapsody")
        self.assertEqual(mock_post.call_count, 1)


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

    def test_normalize_history_query_collapses_spaces_and_case(self):
        self.assertEqual(normalize_history_query("  Beatles   Help "), "beatles help")

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
            _lrclib_item(track_id=32, title="Bohem", artist="Neries"),
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

    @patch("core.services.providers.lrclib.requests.Session.get")
    def test_connection_error_does_not_break_search_candidates(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Failed to resolve 'lrclib.net'")

        results = search_candidates(q="beatles help", artist=None, limit=5)

        self.assertEqual(results, [])

    @override_settings(AI_SEARCH_ENABLED=False, OPENAI_API_KEY="test-key")
    @patch("core.services.lyrics_service.build_ai_search_queries")
    @patch("core.services.lyrics_service._lrclib.search")
    def test_ai_disabled_openai_not_called(self, mock_search, mock_ai_plan):
        mock_search.return_value = []

        search_candidates(q="песня где поется i walk a lonely road", artist=None, limit=5, allow_ai=True)

        mock_ai_plan.assert_not_called()

    @override_settings(AI_SEARCH_ENABLED=True, OPENAI_API_KEY="test-key")
    @patch("core.services.lyrics_service.build_ai_search_queries")
    @patch("core.services.lyrics_service._lrclib.search")
    def test_ai_enabled_good_result_skips_openai(self, mock_search, mock_ai_plan):
        mock_search.return_value = [
            _lrclib_item(
                track_id=91,
                title="Help!",
                artist="The Beatles",
                plain_lyrics="Help, I need somebody",
            )
        ]

        results = search_candidates(q="beatles help", artist=None, limit=5, allow_ai=True)

        self.assertEqual(results[0]["title"], "Help!")
        mock_ai_plan.assert_not_called()

    @override_settings(AI_SEARCH_ENABLED=True, OPENAI_API_KEY="test-key")
    @patch("core.services.lyrics_service.build_ai_search_queries")
    @patch("core.services.lyrics_service._lrclib.search")
    def test_ai_enabled_empty_results_calls_openai_and_queries_lrclib(self, mock_search, mock_ai_plan):
        def fake_search(**kwargs):
            query = kwargs.get("query")
            if query == "Mama just killed a man":
                return [
                    _lrclib_item(
                        track_id=92,
                        title="Bohemian Rhapsody",
                        artist="Queen",
                        plain_lyrics="Mama, just killed a man",
                    )
                ]
            return []

        mock_search.side_effect = fake_search
        mock_ai_plan.return_value = {
            "queries": ["Mama just killed a man", "Queen Bohemian Rhapsody"],
            "detected_artist": "Queen",
            "detected_title": "Bohemian Rhapsody",
            "confidence": 0.86,
        }

        results = search_candidates(q="мама just killed a man queen", artist=None, limit=5, allow_ai=True)

        self.assertEqual(results[0]["artist"], "Queen")
        mock_ai_plan.assert_called_once()
        searched_queries = [call.kwargs.get("query") for call in mock_search.call_args_list if call.kwargs.get("query")]
        self.assertIn("Mama just killed a man", searched_queries)
        self.assertIn("Queen Bohemian Rhapsody", searched_queries)

    @override_settings(AI_SEARCH_ENABLED=True, OPENAI_API_KEY="test-key")
    @patch("core.services.lyrics_service.build_ai_search_queries")
    @patch("core.services.lyrics_service._lrclib.search")
    def test_ai_results_are_merged_and_deduped(self, mock_search, mock_ai_plan):
        def fake_search(**kwargs):
            query = kwargs.get("query")
            if query == "apple bottom jeans":
                return [_lrclib_item(track_id=93, title="Low", artist="Flo Rida", plain_lyrics="Apple Bottom jeans")]
            if query == "low flo rida":
                return [_lrclib_item(track_id=93, title="Low", artist="Flo Rida", plain_lyrics="Apple Bottom jeans")]
            return []

        mock_search.side_effect = fake_search
        mock_ai_plan.return_value = {
            "queries": ["apple bottom jeans", "low flo rida"],
            "detected_artist": "Flo Rida",
            "detected_title": "Low",
            "confidence": 0.71,
        }

        results = search_candidates(q="там что-то про apple bottom jeans", artist=None, limit=5, allow_ai=True)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Low")

    @override_settings(AI_SEARCH_ENABLED=True, OPENAI_API_KEY="test-key")
    @patch("core.services.lyrics_service.build_ai_search_queries", side_effect=RuntimeError("planner failed"))
    @patch("core.services.lyrics_service._lrclib.search")
    def test_ai_exception_does_not_break_search(self, mock_search, mock_ai_plan):
        mock_search.return_value = []

        results = search_candidates(q="queen богемская рапсодия", artist=None, limit=5, allow_ai=True)

        self.assertEqual(results, [])
        mock_ai_plan.assert_called_once()

    @override_settings(AI_SEARCH_ENABLED=True, OPENAI_API_KEY="test-key")
    @patch("core.services.lyrics_service.build_ai_search_queries")
    @patch("core.services.lyrics_service._lrclib.search")
    def test_ai_plan_cache_prevents_repeat_openai_calls_for_same_query(self, mock_search, mock_ai_plan):
        def fake_search(**kwargs):
            if kwargs.get("query") == "i walk a lonely road":
                return [
                    _lrclib_item(
                        track_id=94,
                        title="Boulevard of Broken Dreams",
                        artist="Green Day",
                        plain_lyrics="I walk a lonely road",
                    )
                ]
            return []

        mock_search.side_effect = fake_search
        mock_ai_plan.return_value = {
            "queries": ["i walk a lonely road"],
            "detected_artist": "",
            "detected_title": "",
            "confidence": 0.22,
        }

        search_candidates(q="песня где поется i walk a lonely road", artist=None, limit=5, allow_ai=True)
        search_candidates(q="песня где поется i walk a lonely road", artist=None, limit=5, allow_ai=True)

        mock_ai_plan.assert_called_once()


class BaseTelegramAuthTestCase(TestCase):
    def create_telegram_user(self, telegram_id: int, username: str) -> TelegramUser:
        return TelegramUser.objects.create(telegram_id=telegram_id, username=username)

    def login_telegram_user(self, user: TelegramUser) -> None:
        session = self.client.session
        session["tg_user"] = {
            "id": user.telegram_id,
            "username": user.username,
            "display_name": user.display_name,
        }
        session.save()


class SearchHistoryTests(BaseTelegramAuthTestCase):
    @patch("core.views.search_candidates")
    def test_authenticated_user_gets_search_history_record(self, mock_search_candidates):
        mock_search_candidates.return_value = []
        user = self.create_telegram_user(1, "alice")
        self.login_telegram_user(user)

        self.client.get(reverse("search"), {"q": "beatles help"})

        history = SearchHistory.objects.get(user=user)
        self.assertEqual(history.query, "beatles help")
        self.assertEqual(history.normalized_query, "beatles help")

    @patch("core.views.search_candidates")
    def test_anonymous_user_does_not_create_database_history(self, mock_search_candidates):
        mock_search_candidates.return_value = []

        self.client.get(reverse("search"), {"q": "beatles help"})

        self.assertEqual(SearchHistory.objects.count(), 0)
        self.assertEqual(self.client.session.get("last_queries"), ["beatles help"])

    @patch("core.views.search_candidates")
    def test_repeated_query_with_different_case_does_not_create_duplicate(self, mock_search_candidates):
        mock_search_candidates.return_value = []
        user = self.create_telegram_user(2, "bob")
        self.login_telegram_user(user)

        self.client.get(reverse("search"), {"q": "Beatles Help"})
        self.client.get(reverse("search"), {"q": "  beatles   help "})

        history = SearchHistory.objects.filter(user=user)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().query, "beatles help")

    @patch("core.views.search_candidates")
    def test_user_history_keeps_only_five_latest_unique_queries(self, mock_search_candidates):
        mock_search_candidates.return_value = []
        user = self.create_telegram_user(3, "carol")
        self.login_telegram_user(user)

        for query in ["one", "two", "three", "four", "five", "six"]:
            self.client.get(reverse("search"), {"q": query})

        history = list(SearchHistory.objects.filter(user=user).order_by("-created_at", "-id").values_list("query", flat=True))
        self.assertEqual(history, ["six", "five", "four", "three", "two"])

    @patch("core.views.search_candidates")
    def test_history_of_user_a_is_not_visible_to_user_b(self, mock_search_candidates):
        mock_search_candidates.return_value = []
        user_a = self.create_telegram_user(4, "dave")
        user_b = self.create_telegram_user(5, "erin")

        self.login_telegram_user(user_a)
        self.client.get(reverse("search"), {"q": "beatles help"})

        self.client = self.client_class()
        self.login_telegram_user(user_b)
        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "beatles help")

    @patch("core.views.search_candidates")
    def test_index_shows_recent_queries_for_current_user(self, mock_search_candidates):
        mock_search_candidates.return_value = []
        user = self.create_telegram_user(6, "frank")
        self.login_telegram_user(user)

        self.client.get(reverse("search"), {"q": "beatles help"})
        self.client.get(reverse("search"), {"q": "queen bohemian"})
        response = self.client.get(reverse("index"))

        self.assertContains(response, "Последние запросы:")
        self.assertContains(response, "beatles help")
        self.assertContains(response, "queen bohemian")
        self.assertContains(response, reverse("search") + "?q=beatles%20help")

    @patch("core.views.search_candidates")
    def test_anonymous_index_does_not_show_recent_queries_block(self, mock_search_candidates):
        mock_search_candidates.return_value = []

        session = self.client.session
        session["last_queries"] = ["beatles help"]
        session.save()

        response = self.client.get(reverse("index"))

        self.assertNotContains(response, "Последние запросы:")
        self.assertNotContains(response, "beatles help")

    @patch("core.views.search_candidates")
    def test_legacy_session_history_for_anonymous_user_still_works(self, mock_search_candidates):
        mock_search_candidates.return_value = []

        self.client.get(reverse("search"), {"q": "Beatles Help"})
        self.client.get(reverse("search"), {"q": "  beatles   help "})

        self.assertEqual(self.client.session.get("last_queries"), ["beatles help"])


class SongDetailTranslationTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(TRANSLATION_PROVIDER="", TRANSLATION_API_KEY="")
    @patch("core.views.get_song")
    def test_song_detail_returns_200_when_translation_is_not_configured(self, mock_get_song):
        mock_get_song.return_value = _song_payload()

        response = self.client.get(reverse("song_detail", args=[101]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Перевод пока не настроен")
        self.assertContains(response, "I walk a lonely road")
        self.assertContains(response, "The only one that I have ever known")
        self.assertContains(response, 'class="lyrics-table"')
        self.assertContains(response, 'class="lyrics-table-header"')
        self.assertContains(response, 'class="lyrics-line-pair"', count=3)
        self.assertContains(response, 'data-line-index="0"')
        self.assertContains(response, 'class="lyrics-table-cell lyrics-line-ru">—</div>', count=3)

    @override_settings(TRANSLATION_PROVIDER="", TRANSLATION_API_KEY="")
    @patch("core.views.get_song")
    def test_song_detail_shows_english_text_on_translation_error(self, mock_get_song):
        mock_get_song.return_value = _song_payload()

        response = self.client.get(reverse("song_detail", args=[101]))

        self.assertContains(response, "I walk a lonely road")
        self.assertContains(response, "The only one that I have ever known")

    @override_settings(TRANSLATION_PROVIDER="mock", TRANSLATION_API_KEY="")
    @patch("core.views.get_song")
    def test_song_detail_shows_russian_translation_when_mock_provider_is_enabled(self, mock_get_song):
        mock_get_song.return_value = _song_payload()

        response = self.client.get(reverse("song_detail", args=[101]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Перевод: I walk a lonely road")
        self.assertContains(response, "Перевод: The only one that I have ever known")
        self.assertContains(response, "I walk a lonely road")
        self.assertContains(response, 'data-line-index="0"')
        self.assertContains(response, 'class="lyrics-table-header"')

    @override_settings(TRANSLATION_PROVIDER="mock", TRANSLATION_API_KEY="")
    @patch("core.views.get_song")
    def test_song_detail_renders_english_and_russian_inside_same_line_pair(self, mock_get_song):
        mock_get_song.return_value = _song_payload(song_id=102, plain_lyrics="Line one\nLine two")

        response = self.client.get(reverse("song_detail", args=[102]))
        html = response.content.decode("utf-8")

        self.assertIn(
            '<div class="lyrics-line-pair" data-line-index="0">\n'
            '              <div class="lyrics-table-cell lyrics-line-en">Line one</div>\n'
            '              <div class="lyrics-table-cell lyrics-line-ru">Перевод: Line one</div>\n'
            '            </div>',
            html,
        )

    @patch("core.views.translate_lines_to_russian")
    @patch("core.views.get_song")
    def test_translation_is_saved_in_song_translation(self, mock_get_song, mock_translate):
        plain_lyrics = "I walk a lonely road\nThe only one that I have ever known"
        mock_get_song.return_value = _song_payload(plain_lyrics=plain_lyrics)
        mock_translate.return_value = ["Я иду по одинокой дороге", "Единственная, которую я когда-либо знал"]

        self.client.get(reverse("song_detail", args=[101]))

        translation = SongTranslation.objects.get(source="lrclib", external_id="101", language="ru")
        self.assertEqual(translation.original_hash, hash_original_text(plain_lyrics))
        self.assertEqual(
            translation.aligned_lines,
            build_aligned_lines(
                split_lyrics_lines(plain_lyrics),
                ["Я иду по одинокой дороге", "Единственная, которую я когда-либо знал"],
            ),
        )

    @patch("core.views.translate_lines_to_russian")
    @patch("core.views.get_song")
    def test_repeated_song_detail_uses_cached_translation(self, mock_get_song, mock_translate):
        plain_lyrics = "I walk a lonely road\nThe only one that I have ever known"
        mock_get_song.return_value = _song_payload(plain_lyrics=plain_lyrics)
        mock_translate.return_value = ["Я иду по одинокой дороге", "Единственная, которую я когда-либо знал"]

        self.client.get(reverse("song_detail", args=[101]))
        self.client.get(reverse("song_detail", args=[101]))

        self.assertEqual(mock_translate.call_count, 1)

    @patch("core.views.translate_lines_to_russian")
    @patch("core.views.get_song")
    def test_changed_lyrics_use_new_original_hash_and_new_translation(self, mock_get_song, mock_translate):
        old_lyrics = "Old line"
        new_lyrics = "New line"
        SongTranslation.objects.create(
            source="lrclib",
            external_id="101",
            language="ru",
            original_hash=hash_original_text(old_lyrics),
            translated_text="Старая строка",
            aligned_lines=[{"index": 0, "en": "Old line", "ru": "Старая строка"}],
            provider="mock",
        )
        mock_get_song.return_value = _song_payload(plain_lyrics=new_lyrics)
        mock_translate.return_value = ["Новая строка"]

        response = self.client.get(reverse("song_detail", args=[101]))

        self.assertContains(response, "Новая строка")
        self.assertEqual(
            SongTranslation.objects.filter(source="lrclib", external_id="101", language="ru").count(),
            2,
        )

    @patch("core.views.translate_lines_to_russian")
    @patch("core.views.get_song")
    def test_aligned_lines_contain_index_en_and_ru(self, mock_get_song, mock_translate):
        mock_get_song.return_value = _song_payload(plain_lyrics="Line one\nLine two")
        mock_translate.return_value = ["Строка один", "Строка два"]

        self.client.get(reverse("song_detail", args=[101]))

        translation = SongTranslation.objects.get(source="lrclib", external_id="101", language="ru")
        self.assertEqual(
            translation.aligned_lines,
            [
                {"index": 0, "en": "Line one", "ru": "Строка один"},
                {"index": 1, "en": "Line two", "ru": "Строка два"},
            ],
        )


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

    @patch("core.services.providers.lrclib.requests.Session.get")
    def test_search_page_handles_provider_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Failed to resolve 'lrclib.net'")

        response = self.client.get(reverse("search"), {"q": "beatles help"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сервис поиска текстов временно недоступен. Попробуйте позже.")

    @patch("core.services.lyrics_service._lrclib.search")
    def test_search_page_successful_search_still_works(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(track_id=71, title="Help!", artist="The Beatles", plain_lyrics="Help, I need somebody")
        ]

        response = self.client.get(reverse("search"), {"q": "beatles help"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Help!")
        self.assertContains(response, "The Beatles")


class SearchApiTests(TestCase):
    @patch("core.api_views.search_candidates")
    def test_api_search_without_ai_flag_does_not_enable_ai_search(self, mock_search_candidates):
        mock_search_candidates.return_value = []

        response = self.client.get(reverse("api_lyrics_search"), {"q": "beatles help"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mock_search_candidates.call_args.kwargs["allow_ai"])

    @patch("core.api_views.search_candidates")
    def test_api_search_with_ai_flag_enables_ai_search(self, mock_search_candidates):
        mock_search_candidates.return_value = []

        response = self.client.get(reverse("api_lyrics_search"), {"q": "песня где поется i walk a lonely road", "ai": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_search_candidates.call_args.kwargs["allow_ai"])

    @patch("core.services.providers.lrclib.requests.Session.get")
    def test_api_search_returns_controlled_503_on_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Failed to resolve 'lrclib.net'")

        response = self.client.get(reverse("api_lyrics_search"), {"q": "beatles help"})

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "provider_unavailable")
        self.assertEqual(
            payload["error"]["message"],
            "Сервис поиска текстов временно недоступен. Попробуйте позже.",
        )

    @patch("core.services.lyrics_service._lrclib.search")
    def test_api_search_successful_search_still_works(self, mock_search):
        mock_search.return_value = [
            _lrclib_item(track_id=81, title="Help!", artist="The Beatles", plain_lyrics="Help me if you can")
        ]

        response = self.client.get(reverse("api_lyrics_search"), {"q": "beatles help"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"][0]["title"], "Help!")
        self.assertEqual(payload["data"][0]["artist"], "The Beatles")
