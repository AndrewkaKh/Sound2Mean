from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from django.conf import settings
from django.core.cache import cache
import requests

logger = logging.getLogger(__name__)

AI_SEARCH_PLAN_TTL_SECONDS = 60 * 60 * 24
OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
_SPACE_RE = re.compile(r"\s+")


def _empty_plan() -> dict[str, Any]:
    return {
        "queries": [],
        "detected_artist": "",
        "detected_title": "",
        "confidence": 0.0,
    }


def _normalize_query(value: str) -> str:
    return _SPACE_RE.sub(" ", (value or "").strip().lower())


def _cache_key(user_query: str, limit: int) -> str:
    normalized = _normalize_query(user_query)
    digest = hashlib.sha256(f"{normalized}|{limit}".encode("utf-8", errors="ignore")).hexdigest()
    return f"s2m:ai_search_plan:{digest}"


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned


def _extract_output_text(payload: dict[str, Any]) -> str:
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


def _sanitize_plan(raw_plan: Any, user_query: str, limit: int) -> dict[str, Any]:
    plan = _empty_plan()
    if not isinstance(raw_plan, dict):
        return plan

    raw_queries = raw_plan.get("queries")
    if isinstance(raw_queries, list):
        seen: set[str] = set()
        queries: list[str] = []
        for item in raw_queries:
            if not isinstance(item, str):
                continue
            query = _SPACE_RE.sub(" ", item.strip())
            if len(query) < 2:
                continue
            key = query.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append(query)
            if len(queries) >= limit:
                break
        plan["queries"] = queries

    detected_artist = raw_plan.get("detected_artist")
    if isinstance(detected_artist, str):
        plan["detected_artist"] = _SPACE_RE.sub(" ", detected_artist.strip())

    detected_title = raw_plan.get("detected_title")
    if isinstance(detected_title, str):
        plan["detected_title"] = _SPACE_RE.sub(" ", detected_title.strip())

    confidence = raw_plan.get("confidence")
    if isinstance(confidence, (int, float)):
        plan["confidence"] = max(0.0, min(float(confidence), 1.0))

    if not plan["queries"] and user_query.strip():
        plan["queries"] = [_SPACE_RE.sub(" ", user_query.strip())]

    return plan


def _parse_plan(text: str, user_query: str, limit: int) -> dict[str, Any]:
    cleaned = _strip_code_fences(text)
    try:
        raw_plan = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("AI search planner returned invalid JSON") from exc
    return _sanitize_plan(raw_plan, user_query, limit)


def build_ai_search_queries(user_query: str, limit: int = 5) -> dict[str, Any]:
    query = (user_query or "").strip()
    limit = max(1, min(int(limit), 5))
    if not query:
        return _empty_plan()

    if not getattr(settings, "AI_SEARCH_ENABLED", False):
        logger.info("AI search skipped: disabled in settings")
        return _empty_plan()

    api_key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        logger.warning("AI search skipped: OPENAI_API_KEY is empty")
        return _empty_plan()

    cache_key = _cache_key(query, limit)
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info("AI search cache hit for query '%s'", query)
        return cached

    model = (getattr(settings, "OPENAI_SEARCH_MODEL", "") or "").strip() or "gpt-4o-mini"
    timeout = int(getattr(settings, "AI_SEARCH_TIMEOUT", 10) or 10)
    request_payload = {
        "model": model,
        "instructions": (
            "You are a query planner for a lyrics search provider. "
            "The user may provide an artist, a title, a lyric fragment, a Russian rendering of a title, "
            "or a natural-language description of a song. "
            "Return only valid JSON with the keys queries, detected_artist, detected_title, confidence. "
            "Generate up to 5 short search queries for a lyrics provider. "
            "Do not explain anything. "
            "Do not invent obscure facts. "
            "If uncertain, keep the queries close to the original input."
        ),
        "input": json.dumps(
            {
                "user_query": query,
                "limit": limit,
                "response_schema": {
                    "queries": ["string"],
                    "detected_artist": "string",
                    "detected_title": "string",
                    "confidence": 0.0,
                },
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
        )
        response.raise_for_status()
        payload = response.json()
        output_text = _extract_output_text(payload)
        plan = _parse_plan(output_text, query, limit)
    except requests.exceptions.RequestException as exc:
        logger.warning("AI search failed for query '%s': %s", query, exc)
        return _empty_plan()
    except ValueError as exc:
        logger.warning("AI search returned invalid payload for query '%s': %s", query, exc)
        return _empty_plan()

    cache.set(cache_key, plan, AI_SEARCH_PLAN_TTL_SECONDS)
    logger.info("AI search built %s planned queries for '%s': %s", len(plan["queries"]), query, plan["queries"])
    return plan
