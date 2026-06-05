# 🎵 Sound2Mean

**Понимай музыку. Учи язык. Живи смыслами.**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![Django](https://img.shields.io/badge/Django-4.2-green.svg)](https://djangoproject.com)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://core.telegram.org/bots/api)

Весь смысл любимых зарубежных песен — в одном клике. Больше не нужно переключаться между плеером и переводчиком.

## 👥 Для кого этот проект?

- 🎧 **Меломаны**, которые хотят понимать смысл песен
- 📚 **Изучающие языки** через музыку
- 💡 **Люди, ценящие время** и удобство
- 🚀 **Стартаперы**, интересующиеся EdTech

## ✨ Возможности

- 🔍 **Поиск песен** по названию или тексту
- 📖 **Текст + перевод** параллельным просмотром  
- 🧠 **Умный анализ** устойчивых выражений через LLM
- 📝 **Транскрипция** сложных слов
- 💾 **Сохранение** слов и фраз в личный словарь
- 🔄 **Повторение** через Telegram-бота
- 🎯 **Персонализация** процесса обучения

## 🌟 Что делает нас уникальными?

| Мы | Другие сервисы |
|---|----------------|
| Поиск + перевод + обучение в одном месте | Разрозненные инструменты |
| AI-анализ устойчивых выражений | Простой машинный перевод |
| Персонализация через Telegram | Без персонализации |
| Фокус на микро-обучении | Объемные курсы |

## 🛠 Технологии, которые мы используем

**Backend:** Python, Django, PostgreSQL  
**Frontend:** React, TypeScript, Tailwind CSS  
**AI:** OpenAI GPT, машинный перевод  
**Mobile:** Telegram Bot API  
**Infrastructure:** Docker, Nginx

## AI Search Planning

The main song source remains LRCLIB.

If `AI_SEARCH_ENABLED=1`, the regular HTML search can use OpenAI only as a query planner for weak or natural-language queries. OpenAI does not replace LRCLIB and does not return songs directly. It only builds several improved search queries, and those queries are then sent to LRCLIB.

Environment variables:

- `AI_SEARCH_ENABLED=0`
- `OPENAI_API_KEY=`
- `OPENAI_SEARCH_MODEL=gpt-4o-mini`
- `AI_SEARCH_TIMEOUT=10`

## 📅 Ближайшие планы

**Октябрь 2025 - Январь 2026:** Базовый функционал  
**Январь - Март 2026:** AI-фичи и Telegram бот  
**Март - Апрель 2026:** Бета-тестирование

---

*"Музыка — это язык, который понимают все. Мы просто помогаем понять слова."*
## Translation Setup

The project reads translation settings from the root `.env` file on startup.

Supported providers:

- `TRANSLATION_PROVIDER=mock` for a visible local fallback without external API calls
- `TRANSLATION_PROVIDER=openai` for real translation through the OpenAI Responses API

Example `.env` for OpenAI:

```env
TRANSLATION_PROVIDER=openai
TRANSLATION_TARGET_LANGUAGE=ru
TRANSLATION_TIMEOUT=20
TRANSLATION_MODEL=gpt-4o-mini
TRANSLATION_API_KEY=your_openai_api_key
```

Example `.env` for a safe local stub:

```env
TRANSLATION_PROVIDER=mock
TRANSLATION_TARGET_LANGUAGE=ru
TRANSLATION_TIMEOUT=20
TRANSLATION_MODEL=gpt-4o-mini
TRANSLATION_API_KEY=
```

If `TRANSLATION_PROVIDER` is empty, the page still works:
English lyrics are shown, and the UI displays a soft message that translation is not configured.

Variables used by the translation feature:

- `TRANSLATION_PROVIDER`
- `TRANSLATION_TARGET_LANGUAGE`
- `TRANSLATION_TIMEOUT`
- `TRANSLATION_MODEL`
- `TRANSLATION_API_KEY`
