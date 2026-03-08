from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
import requests

from .services.lyrics_service import get_song, search_candidates
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
    """Главная страница с поиском и недавними запросами."""
    last_queries = request.session.get("last_queries", [])
    context = {
        "last_queries": last_queries,
    }
    return render(request, "core/index.html", context)


def _save_telegram_session(request, payload: dict) -> None:
    request.session["tg_user"] = payload
    request.session.pop("tg_username", None)
    request.session.modified = True


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
                except TelegramBotError as e:
                    messages.error(request, str(e))
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
    request.session.modified = True
    messages.info(request, "Вы вышли из аккаунта.")
    return redirect("index")


def search(request):
    query = (request.GET.get("q") or "").strip()

    # optional: если есть отдельные поля (можешь добавить позже на фронте)
    artist = (request.GET.get("artist") or "").strip()
    track_name = (request.GET.get("track_name") or "").strip()

    # если у тебя один инпут, удобно поддержать формат: "Queen - We Will Rock You"
    if not artist and not track_name and " - " in query:
        left, right = query.split(" - ", 1)
        artist = left.strip()
        track_name = right.strip()

    results = search_candidates(
        q=query or None,
        artist=artist or None,
        track_name=track_name or None,
        limit=5,
    )
    
    for s in results:
        sid = s.get("id")
        if not sid:
            continue
        cache.set(
            f"s2m:song:{sid}",
            {
                "id": sid,
                "title": s.get("title"),
                "artist": s.get("artist"),
                "album": s.get("album"),
                "duration": s.get("duration"),
                "plainLyrics": s.get("_plainLyrics") or "",
                "syncedLyrics": s.get("_syncedLyrics") or "",
            },
            60 * 30,  # 30 минут
        )
    
    # сохраняем историю (как раньше)
    last_queries = request.session.get("last_queries", [])
    if query and query not in last_queries:
        last_queries.insert(0, query)
        request.session["last_queries"] = last_queries[:5]

    return render(request, "core/search_results.html", {
        "query": query,
        "results": results,
    })


def song_detail(request, song_id: int):
    # 1) Сначала пробуем из кэша (после поиска)
    cached = cache.get(f"s2m:song:{song_id}")
    if cached and (cached.get("plainLyrics") or cached.get("syncedLyrics")):
        lyrics_en = (cached.get("plainLyrics") or cached.get("syncedLyrics") or "").splitlines()
        # Перевода пока нет — заполним пустыми строками, чтобы layout был 1:1
        lyrics_ru = [""] * len(lyrics_en)
        lines = list(zip(lyrics_en, lyrics_ru))
        return render(request, "core/song_detail.html", {
            "song": cached,
            "lines": lines,  # как у вас было раньше
            "provider_error": None,
        })

    # 2) Если кэша нет (пользователь открыл прямую ссылку) — fallback на LRCLIB /get
    try:
        song = get_song(song_id)
    except requests.exceptions.RequestException as e:
        # ВАЖНО: не ломаем страницу, но и формат не меняем
        # Покажем ошибку и пустые колонки
        return render(request, "core/song_detail.html", {
            "song": {"title": "Провайдер недоступен", "artist": "", "album": "", "duration": None},
            "lines": [],
            "provider_error": f"{type(e).__name__}: {e}",
        })

    if not song:
        raise Http404("Song not found")

    lyrics_en = (song.get("plainLyrics") or song.get("syncedLyrics") or "").splitlines()
    lyrics_ru = [""] * len(lyrics_en)
    lines = list(zip(lyrics_en, lyrics_ru))
    return render(request, "core/song_detail.html", {
        "song": song,
        "lines": lines,
        "provider_error": None,
    })
