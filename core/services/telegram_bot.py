import logging
from typing import Any, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TelegramBotError(Exception):
    pass


def _api_url(method: str) -> str:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise TelegramBotError("TELEGRAM_BOT_TOKEN is not configured")
    return f"https://api.telegram.org/bot{token}/{method}"


def _normalize_proxy(proxy: str) -> str:
    proxy = proxy.strip()
    if proxy.startswith("socks5://"):
        return "socks5h://" + proxy[len("socks5://") :]
    if proxy.startswith("https://127.0.0.1:") or proxy.startswith("https://host.docker.internal:"):
        return "http://" + proxy[len("https://") :]
    return proxy


def _request_kwargs() -> dict:
    proxy = getattr(settings, "TELEGRAM_PROXY", "") or ""
    if not proxy:
        return {}
    proxy = _normalize_proxy(proxy)
    return {"proxies": {"http": proxy, "https": proxy}}


def send_message(chat_id: int, text: str) -> None:
    try:
        r = requests.post(
            _api_url("sendMessage"),
            json={"chat_id": chat_id, "text": text},
            timeout=30,
            **_request_kwargs(),
        )
        data = r.json()
    except requests.RequestException as e:
        logger.exception("Telegram sendMessage failed")
        raise TelegramBotError("Не удалось отправить сообщение в Telegram") from e

    if not data.get("ok"):
        description = data.get("description", "unknown error")
        logger.warning("Telegram API error: %s", description)
        raise TelegramBotError(description)


def get_updates(offset: Optional[int] = None, timeout: int = 30) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset

    try:
        r = requests.get(
            _api_url("getUpdates"),
            params=params,
            timeout=timeout + 10,
            **_request_kwargs(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        logger.exception("Telegram getUpdates failed")
        raise TelegramBotError("getUpdates failed") from e

    if not data.get("ok"):
        raise TelegramBotError(data.get("description", "getUpdates failed"))
    return data.get("result") or []
