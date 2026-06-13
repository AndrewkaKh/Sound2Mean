import logging
import json
from functools import wraps

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import TelegramUser, VocabularyWord
from .services.lyrics_service import consume_last_provider_error, get_song, resolve_lyrics, search_candidates
from .services.providers.lrclib import LRCLibError
from .services.playlists import build_playlists_payload, toggle_word_in_playlist
from .services.translation_service import TranslationServiceError, translate_lines_to_russian

logger = logging.getLogger(__name__)


def _provider_error(code: str, message: str, status: int, details: str | None = None):
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if details and getattr(settings, "DEBUG", False):
        payload["error"]["details"] = details
    return JsonResponse(payload, status=status)


def lrclib_guard(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except LRCLibError as exc:
            logger.exception("LRCLIB provider error")
            return _provider_error(exc.code, exc.message, exc.status, details=exc.details)
        except requests.exceptions.Timeout as exc:
            logger.exception("LRCLIB timeout")
            return _provider_error("provider_timeout", "LRCLIB timeout", 504, details=str(exc))
        except requests.exceptions.HTTPError as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            body = ""
            if response is not None:
                try:
                    body = (response.text or "")[:300]
                except Exception:
                    body = ""

            logger.exception("LRCLIB HTTP error")
            if status_code == 429:
                return _provider_error(
                    "provider_rate_limited",
                    "LRCLIB rate limited (HTTP 429)",
                    429,
                    details=body,
                )

            return _provider_error(
                "provider_http_error",
                f"LRCLIB HTTP {status_code}",
                502,
                details=body,
            )
        except requests.exceptions.RequestException as exc:
            logger.exception("LRCLIB request exception")
            return _provider_error(
                "provider_unavailable",
                "LRCLIB request failed",
                502,
                details=f"{type(exc).__name__}: {exc}",
            )

    return wrapper


def _bad_request(message: str, code: str = "bad_request"):
    return JsonResponse({"ok": False, "error": {"code": code, "message": message}}, status=400)


def _get_current_telegram_user(request) -> TelegramUser | None:
    payload = request.session.get("tg_user") or {}
    telegram_id = payload.get("id")
    if not telegram_id:
        return None

    try:
        return TelegramUser.objects.filter(telegram_id=telegram_id).first()
    except DatabaseError:
        return None


def _unauthorized(message: str = "Authentication required"):
    return JsonResponse({"ok": False, "error": {"code": "unauthorized", "message": message}}, status=401)


def _parse_json_body(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _suggest_translation(word: str) -> str:
    if not word:
        return ""
    try:
        translated = translate_lines_to_russian([word])
    except TranslationServiceError:
        return ""
    except Exception:
        logger.exception("Unexpected translation preview error for word '%s'", word)
        return ""
    return translated[0].strip() if translated else ""


def _song_metadata(
    song_id_value: str,
    *,
    fallback_title: str = "",
    fallback_artist: str = "",
) -> dict:
    empty = {
        "song_source": "",
        "song_external_id": "",
        "song_title": fallback_title,
        "song_artist": fallback_artist,
    }
    if not song_id_value:
        return empty

    try:
        song_id = int(song_id_value)
    except ValueError:
        return {
            "song_source": "lrclib",
            "song_external_id": song_id_value,
            "song_title": fallback_title,
            "song_artist": fallback_artist,
        }

    cached = cache.get(f"s2m:song:{song_id}")
    if cached:
        return {
            "song_source": cached.get("source") or "lrclib",
            "song_external_id": str(cached.get("id") or song_id),
            "song_title": cached.get("title") or fallback_title,
            "song_artist": cached.get("artist") or fallback_artist,
        }

    try:
        song = get_song(song_id) or {}
    except Exception:
        logger.exception("Failed to load song metadata for card (song_id=%s)", song_id)
        song = {}

    if not song:
        return {
            "song_source": "lrclib",
            "song_external_id": str(song_id),
            "song_title": fallback_title,
            "song_artist": fallback_artist,
        }

    return {
        "song_source": song.get("source") or "lrclib",
        "song_external_id": str(song.get("id") or song_id),
        "song_title": song.get("title") or fallback_title,
        "song_artist": song.get("artist") or fallback_artist,
    }


def _serialize_card(card: VocabularyWord) -> dict:
    return {
        "id": card.id,
        "word": card.word_en,
        "translation": card.word_ru,
        "context": card.context,
        "song": card.song_title,
        "song_artist": card.song_artist,
        "is_favorite": card.is_favorite,
    }


@require_GET
@lrclib_guard
def lyrics_search(request):
    q = (request.GET.get("q") or "").strip()
    track_name = (request.GET.get("track_name") or "").strip()
    artist = (request.GET.get("artist") or request.GET.get("artist_name") or "").strip()
    limit = int(request.GET.get("limit") or 10)
    use_ai = (request.GET.get("ai") or "").strip() == "1"

    if not q and not track_name:
        return _bad_request("Need 'q' or 'track_name'")

    data = search_candidates(
        q=q or None,
        artist=artist or None,
        track_name=track_name or None,
        limit=limit,
        allow_ai=use_ai,
    )
    provider_error = consume_last_provider_error()
    if provider_error is not None:
        return _provider_error(
            provider_error.code,
            "Сервис поиска текстов временно недоступен. Попробуйте позже.",
            503,
            details=provider_error.details,
        )

    return JsonResponse({"ok": True, "data": data})


@require_GET
@lrclib_guard
def lyrics_get(request):
    track_id = (request.GET.get("id") or request.GET.get("track_id") or "").strip()
    if not track_id:
        return _bad_request("Parameter 'id' is required")

    try:
        track_id_int = int(track_id)
    except ValueError:
        return _bad_request("'id' must be int")

    song = get_song(track_id_int)
    return JsonResponse({"ok": True, "data": song})


@require_GET
@lrclib_guard
def lyrics_resolve(request):
    q = (request.GET.get("q") or "").strip()
    track_name = (request.GET.get("track_name") or "").strip()
    artist = (request.GET.get("artist") or request.GET.get("artist_name") or "").strip()
    limit = int(request.GET.get("limit") or 10)

    if not q and not track_name:
        return _bad_request("Need 'q' or 'track_name'")

    data = resolve_lyrics(q=q or None, artist=artist or None, track_name=track_name or None, limit=limit)
    return JsonResponse({"ok": True, "data": data})


@require_POST
def cards_create(request):
    user = _get_current_telegram_user(request)
    if not user:
        return _unauthorized("Войдите через Telegram, чтобы сохранять карточки.")

    payload = _parse_json_body(request)
    if payload is None:
        return _bad_request("Invalid JSON body", code="invalid_json")

    word = (payload.get("word") or "").strip()
    translation = (payload.get("translation") or "").strip()
    context = (payload.get("context") or "").strip()
    song_id = str(payload.get("song_id") or "").strip()
    preview = bool(payload.get("preview"))

    if not word:
        return _bad_request("Field 'word' is required", code="missing_word")

    suggested_translation = translation or _suggest_translation(word)
    if preview:
        return JsonResponse(
            {
                "ok": True,
                "preview": True,
                "word": word,
                "translation": suggested_translation,
                "context": context,
            }
        )

    metadata = _song_metadata(
        song_id,
        fallback_title=(payload.get("song_title") or "").strip(),
        fallback_artist=(payload.get("song_artist") or "").strip(),
    )
    card = VocabularyWord.objects.filter(user=user, word_en__iexact=word).first()
    if card is None:
        card = VocabularyWord(user=user, word_en=word)
    else:
        card.word_en = word

    card.word_ru = suggested_translation
    card.context = context
    card.song_source = metadata["song_source"]
    card.song_external_id = metadata["song_external_id"]
    card.song_title = metadata["song_title"]
    card.song_artist = metadata["song_artist"]
    try:
        card.save()
    except IntegrityError:
        card = VocabularyWord.objects.get(user=user, word_en__iexact=word)
        card.word_ru = suggested_translation
        card.context = context
        card.song_source = metadata["song_source"]
        card.song_external_id = metadata["song_external_id"]
        card.song_title = metadata["song_title"]
        card.song_artist = metadata["song_artist"]
        card.save()

    request.session["flashcard_current_id"] = card.id
    request.session.modified = True
    return JsonResponse({"ok": True, "card": _serialize_card(card)})


@require_GET
def playlists_list(request):
    user = _get_current_telegram_user(request)
    if not user:
        return _unauthorized()

    word_id_raw = (request.GET.get("word_id") or "").strip()
    word_id = int(word_id_raw) if word_id_raw.isdigit() else None
    if word_id is not None and not VocabularyWord.objects.filter(pk=word_id, user=user).exists():
        return _bad_request("Word not found")

    return JsonResponse({"ok": True, "playlists": build_playlists_payload(user, word_id=word_id)})


@require_POST
def playlist_toggle_word(request):
    user = _get_current_telegram_user(request)
    if not user:
        return _unauthorized()

    payload = _parse_json_body(request)
    if payload is None:
        return _bad_request("Invalid JSON body", code="invalid_json")

    playlist_id_raw = payload.get("playlist_id")
    word_id_raw = payload.get("word_id")
    if not isinstance(playlist_id_raw, int) or not isinstance(word_id_raw, int):
        return _bad_request("playlist_id and word_id must be integers")

    contains = toggle_word_in_playlist(user, playlist_id_raw, word_id_raw)
    if contains is None:
        return _bad_request("Playlist or word not found")

    return JsonResponse({"ok": True, "contains": contains, "playlists": build_playlists_payload(user, word_id=word_id_raw)})
