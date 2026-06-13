from __future__ import annotations

import hashlib
import json
import logging
from typing import List

from django.conf import settings
import requests

from .http_proxy import get_proxy_request_kwargs

logger = logging.getLogger(__name__)
SUPPORTED_TRANSLATION_PROVIDERS = {"mock", "openai"}
OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"


class TranslationServiceError(Exception):
    pass


def split_lyrics_lines(text: str) -> List[str]:
    if text is None:
        return []
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n")


def normalize_translated_lines(lines: List[str], expected_length: int) -> List[str]:
    normalized = list(lines[:expected_length])
    if len(normalized) < expected_length:
        normalized.extend([""] * (expected_length - len(normalized)))
    return normalized


def hash_original_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def build_aligned_lines(english_lines: List[str], russian_lines: List[str]) -> List[dict]:
    normalized_ru = normalize_translated_lines(russian_lines, len(english_lines))
    return [
        {
            "index": index,
            "en": en_line,
            "ru": normalized_ru[index],
        }
        for index, en_line in enumerate(english_lines)
    ]


def _translate_with_mock(lines: List[str]) -> List[str]:
    return [f"Перевод: {line}" if line else "" for line in lines]


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned


def _extract_openai_output_text(payload: dict) -> str:
    direct_output = payload.get("output_text")
    if isinstance(direct_output, str) and direct_output.strip():
        return direct_output.strip()

    text_parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") != "output_text":
                continue
            text = content.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)

    return "\n".join(text_parts).strip()


def _parse_openai_translation_payload(text: str, expected_length: int) -> List[str]:
    cleaned = _strip_code_fences(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise TranslationServiceError("OpenAI вернул неожиданный формат перевода") from exc

    if isinstance(payload, dict):
        payload = payload.get("translations")

    if not isinstance(payload, list):
        raise TranslationServiceError("OpenAI вернул неожиданный формат перевода")

    translated_lines = [item if isinstance(item, str) else "" for item in payload]
    return normalize_translated_lines(translated_lines, expected_length)


def _raise_openai_error(response: requests.Response) -> None:
    request_id = response.headers.get("x-request-id", "n/a")
    message = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "")

    logger.warning(
        "OpenAI translation request failed: status=%s request_id=%s message=%s",
        response.status_code,
        request_id,
        message or "no error message",
    )

    if response.status_code in {401, 403}:
        if "not supported" in message.lower() or "country" in message.lower():
            raise TranslationServiceError(
                "OpenAI недоступен из вашего региона. Укажите TELEGRAM_PROXY в .env "
                "(тот же прокси, что для Telegram)."
            )
        raise TranslationServiceError("OpenAI API key отклонён. Проверьте TRANSLATION_API_KEY")
    if response.status_code == 429:
        raise TranslationServiceError("OpenAI временно ограничил запросы. Попробуйте позже")

    raise TranslationServiceError("Не удалось получить перевод от OpenAI")


def _translate_with_openai(lines: List[str], api_key: str) -> List[str]:
    target_language = (getattr(settings, "TRANSLATION_TARGET_LANGUAGE", "ru") or "ru").strip()
    model = (getattr(settings, "TRANSLATION_MODEL", "") or "").strip() or "gpt-4o-mini"
    timeout = int(getattr(settings, "TRANSLATION_TIMEOUT", 20) or 20)

    request_payload = {
        "model": model,
        "instructions": (
            "Translate English song lyrics into the target language from the input payload. "
            "Return only valid JSON. "
            "Use either a JSON array of strings or an object with the key 'translations'. "
            "Preserve line order exactly. "
            "Preserve empty lines as empty strings. "
            "Do not add comments, markdown, or explanations."
        ),
        "input": json.dumps(
            {
                "target_language": target_language,
                "lines": lines,
            },
            ensure_ascii=False,
        ),
    }

    try:
        response = requests.post(
            OPENAI_RESPONSES_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=timeout,
            **get_proxy_request_kwargs(),
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("OpenAI translation request failed before response: %s", exc)
        raise TranslationServiceError("Не удалось связаться с OpenAI для перевода") from exc

    if response.status_code >= 400:
        _raise_openai_error(response)

    try:
        payload = response.json()
    except ValueError as exc:
        raise TranslationServiceError("OpenAI вернул некорректный ответ") from exc

    output_text = _extract_openai_output_text(payload)
    if not output_text:
        logger.warning(
            "OpenAI translation response did not contain output_text. request_id=%s",
            response.headers.get("x-request-id", "n/a"),
        )
        raise TranslationServiceError("OpenAI не вернул текст перевода")

    return _parse_openai_translation_payload(output_text, len(lines))


def translate_lines_to_russian(lines: List[str]) -> List[str]:
    provider = (getattr(settings, "TRANSLATION_PROVIDER", "") or "").strip().lower()
    api_key = (getattr(settings, "TRANSLATION_API_KEY", "") or "").strip()
    if not lines:
        logger.info("Translation skipped: no lines to translate")
        return []

    if not provider:
        logger.warning("Translation disabled: TRANSLATION_PROVIDER is empty")
        raise TranslationServiceError("Перевод пока не настроен")

    if provider == "mock":
        logger.info("Translation provider selected: mock")
        return normalize_translated_lines(_translate_with_mock(lines), len(lines))

    if provider == "openai":
        if not api_key:
            logger.warning("Translation disabled: provider 'openai' requires TRANSLATION_API_KEY")
            raise TranslationServiceError("Переводчик не настроен: заполните TRANSLATION_API_KEY")
        logger.info("Translation provider selected: openai")
        return _translate_with_openai(lines, api_key)

    if not api_key:
        logger.warning(
            "Translation disabled: provider '%s' requires TRANSLATION_API_KEY",
            provider,
        )
        raise TranslationServiceError("Переводчик не настроен: заполните TRANSLATION_API_KEY")

    logger.warning(
        "Translation provider '%s' is not supported yet. Supported providers: %s",
        provider,
        ", ".join(sorted(SUPPORTED_TRANSLATION_PROVIDERS)),
    )
    raise TranslationServiceError("Переводчик пока не поддерживается этим проектом")
