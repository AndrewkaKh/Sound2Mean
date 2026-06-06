import logging
from functools import wraps

import requests
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .services.lyrics_service import consume_last_provider_error, get_song, resolve_lyrics, search_candidates
from .services.providers.lrclib import LRCLibError

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


@require_GET
@lrclib_guard
def lyrics_search(request):
    q = (request.GET.get("q") or "").strip()
    track_name = (request.GET.get("track_name") or "").strip()
    artist = (request.GET.get("artist") or request.GET.get("artist_name") or "").strip()
    limit = int(request.GET.get("limit") or 10)

    if not q and not track_name:
        return _bad_request("Need 'q' or 'track_name'")

    data = search_candidates(q=q or None, artist=artist or None, track_name=track_name or None, limit=limit)
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
