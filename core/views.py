from django.shortcuts import render, redirect
from django.http import Http404

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


def login_view(request):
    """
    Псевдо-логин через Telegram:
    пользователь вводит username и код.
    Для КТ1 считаем, что код всегда 1234.
    """
    error = None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        code = request.POST.get("code", "").strip()

        if not username or not code:
            error = "Заполните оба поля."
        elif code != "1234":
            error = "Неверный код (для теста используйте 1234)."
        else:
            request.session["tg_username"] = username
            return redirect("index")

    return render(request, "core/login.html", {"error": error})


def logout_view(request):
    """Выход — просто очищаем username из сессии."""
    request.session.pop("tg_username", None)
    return redirect("index")


def search(request):
    """
    Результаты поиска по локальному списку SONGS.
    Ищем по названию или исполнителю.
    """
    query = request.GET.get("q", "").strip()
    results = []

    if query:
        q_lower = query.lower()
        for song in SONGS:
            if q_lower in song["title"].lower() or q_lower in song["artist"].lower():
                results.append(song)

        last_queries = request.session.get("last_queries", [])
        if query not in last_queries:
            last_queries.insert(0, query)
            last_queries = last_queries[:5]
            request.session["last_queries"] = last_queries

    context = {
        "query": query,
        "results": results,
    }
    return render(request, "core/search_results.html", context)


def song_detail(request, song_id: int):
    """
    Страница песни: слева английский текст, справа русский перевод.
    """
    song = next((s for s in SONGS if s["id"] == song_id), None)
    if not song:
        raise Http404("Song not found")

    lines = list(zip(song["lyrics_en"], song["lyrics_ru"]))

    context = {
        "song": song,
        "lines": lines,
    }
    return render(request, "core/song_detail.html", context)
