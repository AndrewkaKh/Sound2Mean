from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect, render
import requests

from .models import TelegramUser, VocabularyWord
from .services.flashcards import (
    DECK_ALL,
    DECK_FAVORITES,
    advance_to_next,
    can_advance,
    get_current_word_id,
    get_deck_mode,
    get_deck_word_ids,
    get_user_word_ids,
    is_shuffle_enabled,
    reset_queue,
    set_deck_mode,
    toggle_shuffle,
)
from .services.lyrics_service import consume_last_provider_error, get_song, parse_artist_title_query, search_candidates
from .services.search_history import get_recent_queries_for_user, save_user_query
from .services.login_code import verify_code
from .services.telegram_bot import TelegramBotError
from .services.telegram_users import find_by_username, send_login_code

SONGS = [
    {
        "id": 1,
        "title": "Morning Light",
        "artist": "John Doe",
        "genre": "Pop",
        "lyrics_en": [
            "I wake up in the morning",
            "And the sun is shining bright",
            "I put my headphones on",
            "Let the music start my day",
        ],
        "lyrics_ru": [
            "Я просыпаюсь утром",
            "И солнце ярко светит",
            "Я надеваю наушники",
            "Пусть музыка запускает мой день",
        ],
    },
    {
        "id": 2,
        "title": "City Nights",
        "artist": "Anna Smith",
        "genre": "Indie",
        "lyrics_en": [
            "City lights are fading slowly",
            "People run but feel alone",
            "I just walk and hear the rhythm",
            "Of a song inside my phone",
        ],
        "lyrics_ru": [
            "Огни города медленно гаснут",
            "Люди бегут, но чувствуют себя одинокими",
            "Я просто иду и слышу ритм",
            "Песни, звучащей в моём телефоне",
        ],
    },
    {
        "id": 3,
        "title": "Ocean of Words",
        "artist": "The Dreamers",
        "genre": "Rock",
        "lyrics_en": [
            "In the ocean of words I am swimming",
            "Trying not to forget what they mean",
            "Every chorus is part of my story",
            "Every line is a place I have been",
        ],
        "lyrics_ru": [
            "В океане слов я плыву",
            "Стараясь не забыть, что они значат",
            "Каждый припев — часть моей истории",
            "Каждая строка — место, где я уже был",
        ],
    },
]


def index(request):
    telegram_user = _get_current_telegram_user(request)
    last_queries = get_recent_queries_for_user(telegram_user) if telegram_user else []
    context = {
        "last_queries": last_queries,
    }
    return render(request, "core/index.html", context)


def _save_telegram_session(request, payload: dict) -> None:
    request.session["tg_user"] = payload
    request.session.pop("tg_username", None)
    request.session.modified = True


def _get_current_telegram_user(request) -> TelegramUser | None:
    payload = request.session.get("tg_user") or {}
    telegram_id = payload.get("id")
    if not telegram_id:
        return None

    try:
        return TelegramUser.objects.filter(telegram_id=telegram_id).first()
    except DatabaseError:
        return None


def login_view(request):
    if request.session.get("tg_user"):
        return redirect("index")

    username_value = ""
    code_sent = bool(request.session.get("login_code_pending"))

    if request.method == "POST":
        action = request.POST.get("action", "")
        username_value = request.POST.get("username", "")
        code = request.POST.get("code", "").strip()

        if not settings.TELEGRAM_BOT_TOKEN:
            messages.error(request, "Задайте TELEGRAM_BOT_TOKEN в .env")
        elif action == "send_code":
            user = find_by_username(username_value)
            if not user:
                messages.error(request, "Сначала откройте бота и отправьте /start")
            else:
                try:
                    send_login_code(user)
                    request.session["login_code_pending"] = True
                    code_sent = True
                    messages.success(request, "Код отправлен в Telegram.")
                except TelegramBotError as exc:
                    messages.error(request, str(exc))
        elif action == "login":
            user = find_by_username(username_value)
            if not user:
                messages.error(request, "Пользователь не найден. Сначала /start в боте.")
            elif not verify_code(user.telegram_id, code):
                messages.error(request, "Неверный или просроченный код.")
            else:
                _save_telegram_session(
                    request,
                    {
                        "id": user.telegram_id,
                        "username": user.username,
                        "display_name": user.display_name,
                    },
                )
                request.session.pop("login_code_pending", None)
                messages.success(request, f"Добро пожаловать, {user.display_name}!")
                return redirect("index")
        else:
            messages.error(request, "Неизвестное действие.")

    return render(
        request,
        "core/login.html",
        {"username_value": username_value, "code_sent": code_sent},
    )


def logout_view(request):
    request.session.pop("tg_user", None)
    request.session.pop("tg_username", None)
    request.session.pop("login_code_pending", None)
    request.session.pop("flashcard_queue", None)
    request.session.pop("flashcard_current_id", None)
    request.session.modified = True
    messages.info(request, "Вы вышли из аккаунта.")
    return redirect("index")


def _get_telegram_user(request) -> TelegramUser | None:
    tg = request.session.get("tg_user")
    if not tg:
        return None
    return TelegramUser.objects.filter(telegram_id=tg.get("id")).first()


def flashcards(request):
    if not request.session.get("tg_user"):
        if request.method == "POST":
            return redirect("login")
        return render(request, "core/flashcards.html", {"authorized": False})

    user = _get_telegram_user(request)
    if not user:
        if request.method == "POST":
            return redirect("login")
        return render(request, "core/flashcards.html", {"authorized": False})

    deck_mode = get_deck_mode(request)

    if request.method == "GET" and request.GET.get("deck") in (DECK_ALL, DECK_FAVORITES):
        set_deck_mode(request, request.GET["deck"])
        deck_mode = get_deck_mode(request)

    if request.method == "POST":
        action = request.POST.get("action", "")
        card_id = request.POST.get("card_id", "").strip()

        if action == "set_deck":
            mode = request.POST.get("deck", DECK_ALL)
            set_deck_mode(request, mode)
            deck_mode = get_deck_mode(request)
        elif action == "toggle_shuffle":
            toggle_shuffle(request)
        elif action == "add_word":
            word_en = (request.POST.get("word_en") or "").strip()
            word_ru = (request.POST.get("word_ru") or "").strip()
            if not word_en or not word_ru:
                messages.error(request, "Заполните слово и перевод.")
            else:
                _, created = VocabularyWord.objects.get_or_create(
                    user=user,
                    word_en=word_en,
                    defaults={"word_ru": word_ru},
                )
                if created:
                    reset_queue(request)
        elif action == "next":
            word_ids = get_deck_word_ids(user, deck_mode)
            if can_advance(word_ids):
                advance_to_next(request, word_ids)
        elif action == "delete" and card_id.isdigit():
            deleted, _ = VocabularyWord.objects.filter(
                pk=int(card_id),
                user=user,
            ).delete()
            if deleted:
                reset_queue(request)
                word_ids = get_deck_word_ids(user, deck_mode)
                if word_ids:
                    advance_to_next(request, word_ids)
        elif action == "toggle_favorite" and card_id.isdigit():
            word = VocabularyWord.objects.filter(pk=int(card_id), user=user).first()
            if word:
                word.is_favorite = not word.is_favorite
                word.save(update_fields=["is_favorite"])
                if not word.is_favorite and deck_mode == DECK_FAVORITES:
                    reset_queue(request)
                    word_ids = get_deck_word_ids(user, deck_mode)
                    if word_ids:
                        advance_to_next(request, word_ids)

        deck_mode = get_deck_mode(request)

    word_ids = get_deck_word_ids(user, deck_mode)
    current_id = get_current_word_id(request, word_ids)
    card = VocabularyWord.objects.filter(pk=current_id, user=user).first() if current_id else None
    total_count = len(get_user_word_ids(user))
    favorites_count = len(get_user_word_ids(user, favorites_only=True))
    shuffle_enabled = is_shuffle_enabled(request)

    return render(
        request,
        "core/flashcards.html",
        {
            "authorized": True,
            "card": card,
            "deck_mode": deck_mode,
            "deck_all": DECK_ALL,
            "deck_favorites": DECK_FAVORITES,
            "words_count": total_count,
            "favorites_count": favorites_count,
            "shuffle_enabled": shuffle_enabled,
            "can_next": can_advance(word_ids),
        },
    )


def search(request):
    query = (request.GET.get("q") or "").strip()
    artist = (request.GET.get("artist") or "").strip()
    track_name = (request.GET.get("track_name") or "").strip()
    parsed_query = parse_artist_title_query(query) if query else None

    if not artist and not track_name and parsed_query:
        artist = parsed_query["artist"]
        track_name = parsed_query["track_name"]

    results = search_candidates(
        q=query or None,
        artist=artist or None,
        track_name=track_name or None,
        limit=5,
    )
    provider_error = consume_last_provider_error()
    if provider_error is not None:
        messages.error(request, "Сервис поиска текстов временно недоступен. Попробуйте позже.")

    for song in results:
        song_id = song.get("id")
        if not song_id:
            continue
        cache.set(
            f"s2m:song:{song_id}",
            {
                "id": song_id,
                "title": song.get("title"),
                "artist": song.get("artist"),
                "album": song.get("album"),
                "duration": song.get("duration"),
                "plainLyrics": song.get("_plainLyrics") or "",
                "syncedLyrics": song.get("_syncedLyrics") or "",
            },
            60 * 30,
        )

    telegram_user = _get_current_telegram_user(request)
    if telegram_user:
        save_user_query(telegram_user, query)
    else:
        last_queries = request.session.get("last_queries", [])
        normalized_query = " ".join(query.lower().split())
        normalized_history = {" ".join(item.lower().split()): item for item in last_queries}
        if normalized_query:
            if normalized_query in normalized_history:
                last_queries = [item for item in last_queries if " ".join(item.lower().split()) != normalized_query]
            last_queries.insert(0, " ".join(query.split()))
            request.session["last_queries"] = last_queries[:5]

    return render(
        request,
        "core/search_results.html",
        {
            "query": query,
            "results": results,
            "parsed_artist": parsed_query["artist"] if parsed_query else "",
            "parsed_track_name": parsed_query["track_name"] if parsed_query else "",
        },
    )


def song_detail(request, song_id: int):
    cached = cache.get(f"s2m:song:{song_id}")
    if cached and (cached.get("plainLyrics") or cached.get("syncedLyrics")):
        lyrics_en = (cached.get("plainLyrics") or cached.get("syncedLyrics") or "").splitlines()
        lyrics_ru = [""] * len(lyrics_en)
        lines = list(zip(lyrics_en, lyrics_ru))
        return render(
            request,
            "core/song_detail.html",
            {
                "song": cached,
                "lines": lines,
                "provider_error": None,
            },
        )

    try:
        song = get_song(song_id)
    except requests.exceptions.RequestException as exc:
        return render(
            request,
            "core/song_detail.html",
            {
                "song": {"title": "Провайдер недоступен", "artist": "", "album": "", "duration": None},
                "lines": [],
                "provider_error": f"{type(exc).__name__}: {exc}",
            },
        )

    if not song:
        raise Http404("Song not found")

    lyrics_en = (song.get("plainLyrics") or song.get("syncedLyrics") or "").splitlines()
    lyrics_ru = [""] * len(lyrics_en)
    lines = list(zip(lyrics_en, lyrics_ru))
    return render(
        request,
        "core/song_detail.html",
        {
            "song": song,
            "lines": lines,
            "provider_error": None,
        },
    )
