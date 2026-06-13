# Sound2Mean

Учебный Django-проект для поиска песен, чтения текста с переводом и сохранения слов в персональные карточки.

Приложение объединяет несколько сценариев:

- поиск песни по названию, исполнителю или фрагменту текста;
- просмотр текста песни;
- построчный перевод текста;
- сохранение слов и фраз в персональные карточки;
- вход через Telegram;
- Telegram-бот для авторизации и учебных сценариев.

## Что умеет проект

### Поиск песен

Поиск работает через LRCLib. Пользователь может искать:

- по названию трека;
- по схеме `artist - title`;
- по части строки из песни;
- по свободному описанию, если включён AI query planner.

Поиск ранжирует кандидатов, кэширует результаты и старается вернуть лучший ответ в пределах заданного latency budget.

### Просмотр текста и перевода

Для найденной песни можно открыть страницу с текстом. Если настроен переводчик, приложение показывает английские строки и русский перевод рядом.

Поддерживаются два режима:

- `mock` — безопасный локальный режим без внешнего API;
- `openai` — перевод через OpenAI API.

### Карточки слов

На странице песни можно сохранять слова и фразы в персональные карточки. Для карточки сохраняются:

- слово или фраза;
- перевод;
- контекст;
- песня и исполнитель.

Карточки можно листать, переключать режим колоды и включать shuffle.

### Telegram-авторизация

Пользователь может зайти через Telegram:

1. открыть бота;
2. отправить `/start`;
3. указать username на сайте;
4. получить одноразовый код;
5. войти на сайт.

## Стек

- Python 3.12+
- Django 6
- SQLite для локальной разработки
- LRCLib как провайдер текстов песен
- OpenAI API для перевода и AI-планирования поисковых запросов
- Docker / Docker Compose
- Poetry для управления зависимостями

## Структура проекта

- `core/` — основное Django-приложение
- `core/services/` — бизнес-логика, интеграции и сервисы
- `core/templates/` — HTML-шаблоны
- `core/static/` — CSS и статические файлы
- `sound2mean_project/` — настройки Django-проекта
- `docker-compose.yml` — локальный запуск через Docker
- `pyproject.toml` — зависимости и конфигурация проекта

## Локальный запуск через Poetry

### 1. Установить зависимости

```bash
poetry lock
poetry install --with dev
```

### 2. Создать `.env`

Можно взять за основу `.env.example`.

Минимальный локальный вариант:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_PROXY=

TRANSLATION_PROVIDER=mock
TRANSLATION_TARGET_LANGUAGE=ru
TRANSLATION_TIMEOUT=20
TRANSLATION_MODEL=gpt-4o-mini
TRANSLATION_API_KEY=

AI_SEARCH_ENABLED=0
OPENAI_API_KEY=
OPENAI_SEARCH_MODEL=gpt-4o-mini
AI_SEARCH_TIMEOUT=4

LYRICS_SEARCH_BUDGET_SECONDS=8
LRCLIB_SEARCH_CONNECT_TIMEOUT=2
LRCLIB_SEARCH_READ_TIMEOUT=5
LRCLIB_GET_READ_TIMEOUT=8
LYRICS_SEARCH_MAX_ATTEMPTS=4
LYRICS_SEARCH_ENABLE_DEEP_FALLBACK=0
```

### 3. Применить миграции

```bash
poetry run python manage.py migrate
```

### 4. Запустить сервер

```bash
poetry run python manage.py runserver
```

После запуска приложение будет доступно на:

```text
http://127.0.0.1:8000
```

### 5. При необходимости запустить Telegram-бота

```bash
poetry run python manage.py run_telegram_bot
```

## Локальный запуск через Docker

В проекте есть `docker-compose.yml` с сервисами:

- `web` — Django-приложение;
- `bot` — Telegram-бот;

### Запуск

```bash
docker compose up --build
```

Или в фоне:

```bash
docker compose up --build -d
```

После запуска:

- сайт будет доступен на `http://127.0.0.1:8000`;
- миграции применятся автоматически;
- бот запустится отдельным сервисом.

### Остановка

```bash
docker compose down
```

### Логи

```bash
docker compose logs -f
```

## Тесты

Запуск через Poetry:

```bash
poetry run pytest core -v
```

Или через Django test runner:

```bash
poetry run python manage.py test
```

## Настройки окружения

### Поиск текстов

- `LYRICS_SEARCH_BUDGET_SECONDS` — общий budget на поиск
- `LRCLIB_SEARCH_CONNECT_TIMEOUT` — connect timeout для `/search`
- `LRCLIB_SEARCH_READ_TIMEOUT` — read timeout для `/search`
- `LRCLIB_GET_READ_TIMEOUT` — read timeout для `/get`
- `LYRICS_SEARCH_MAX_ATTEMPTS` — максимальное число non-AI search attempts
- `LYRICS_SEARCH_ENABLE_DEEP_FALLBACK` — включает более глубокий fallback

### AI-поиск

- `AI_SEARCH_ENABLED` — включает AI planner
- `OPENAI_API_KEY` — ключ OpenAI
- `OPENAI_SEARCH_MODEL` — модель для AI planner
- `AI_SEARCH_TIMEOUT` — timeout AI planner

### Перевод

- `TRANSLATION_PROVIDER` — `mock` или `openai`
- `TRANSLATION_TARGET_LANGUAGE` — целевой язык
- `TRANSLATION_TIMEOUT` — timeout перевода
- `TRANSLATION_MODEL` — модель перевода
- `TRANSLATION_API_KEY` — ключ для перевода

### Telegram

- `TELEGRAM_BOT_TOKEN` — токен бота
- `TELEGRAM_BOT_USERNAME` — username бота
- `TELEGRAM_PROXY` — proxy для Telegram/OpenAI запросов при необходимости

## Полезные команды

Установить зависимости:

```bash
poetry install --with dev
```

Применить миграции:

```bash
poetry run python manage.py migrate
```

Запустить сервер:

```bash
poetry run python manage.py runserver
```

Запустить тесты:

```bash
poetry run pytest core -v
```

Поднять Docker-окружение:

```bash
docker compose up --build
```
