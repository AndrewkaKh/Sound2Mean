# core/api_views.py (фрагмент)
import logging
import requests
from functools import wraps
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .services.lyrics_service import search_candidates, get_song, resolve_lyrics

logger = logging.getLogger(__name__)


def _provider_error(code: str, message: str, status: int, details: str | None = None):
    payload = {"ok": False, "error": {"code": code, "message": message}}
    # details показываем только в DEBUG
    if details and getattr(settings, "DEBUG", False):
        payload["error"]["details"] = details
    return JsonResponse(payload, status=status)


def lrclib_guard(view_func):
    """
    Оборачивает view, которая ходит в LRCLIB через requests.
    Возвращает JSON вместо Django debug страницы при сетевых/HTTP ошибках.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)

        except requests.exceptions.Timeout as e:
            logger.exception("LRCLIB timeout")
            return _provider_error(
                "provider_timeout",
                "LRCLIB timeout",
                504,
                details=str(e),
            )

        except requests.exceptions.HTTPError as e:
            resp = getattr(e, "response", None)
            status_code = getattr(resp, "status_code", None)
            body = ""
            if resp is not None:
                try:
                    body = (resp.text or "")[:300]
                except Exception:
                    body = ""

            logger.exception("LRCLIB HTTP error")

            # полезно отдельно пробросить rate limit
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

        except requests.exceptions.RequestException as e:
            logger.exception("LRCLIB request exception")
            return _provider_error(
                "provider_unavailable",
                "LRCLIB request failed",
                502,
                details=f"{type(e).__name__}: {e}",
            )

    return wrapper

def _bad_request(message: str, code: str = "bad_request"):
    return JsonResponse({"ok": False, "error": {"code": code, "message": message}}, status=400)


def _provider_error(code: str, message: str, status: int):
    return JsonResponse({"ok": False, "error": {"code": code, "message": message}}, status=status)


@require_GET
@lrclib_guard
def lyrics_search(request):
    q = (request.GET.get("q") or "").strip()
    track_name = (request.GET.get("track_name") or "").strip()
    artist = (request.GET.get("artist") or request.GET.get("artist_name") or "").strip()
    limit = int(request.GET.get("limit") or 10)

    if not q and not track_name:
        return JsonResponse({"ok": False, "error": {"code": "bad_request", "message": "Need 'q' or 'track_name'"}}, status=400)

    data = search_candidates(q=q or None, artist=artist or None, track_name=track_name or None, limit=limit)
    return JsonResponse({"ok": True, "data": data})


@require_GET
@lrclib_guard
def lyrics_get(request):
    track_id = (request.GET.get("id") or request.GET.get("track_id") or "").strip()
    if not track_id:
        return JsonResponse({"ok": False, "error": {"code": "bad_request", "message": "Parameter 'id' is required"}}, status=400)

    try:
        track_id_int = int(track_id)
    except ValueError:
        return JsonResponse({"ok": False, "error": {"code": "bad_request", "message": "'id' must be int"}}, status=400)

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
        return JsonResponse({"ok": False, "error": {"code": "bad_request", "message": "Need 'q' or 'track_name'"}}, status=400)

    data = resolve_lyrics(q=q or None, artist=artist or None, track_name=track_name or None, limit=limit)
    return JsonResponse({"ok": True, "data": data})