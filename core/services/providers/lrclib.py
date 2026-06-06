from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class LRCLibError(requests.exceptions.RequestException):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status: int = 503,
        details: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def _raise_lrclib_error(exc: requests.exceptions.RequestException) -> None:
    if isinstance(exc, requests.exceptions.Timeout):
        raise LRCLibError(
            code="provider_timeout",
            message="LRCLIB timeout",
            status=504,
            details=str(exc),
        ) from exc

    if isinstance(exc, requests.exceptions.ConnectionError):
        raise LRCLibError(
            code="provider_unavailable",
            message="LRCLIB connection failed",
            status=503,
            details=str(exc),
        ) from exc

    if isinstance(exc, requests.exceptions.HTTPError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None) or 502
        body = ""
        if response is not None:
            try:
                body = (response.text or "")[:300]
            except Exception:
                body = ""

        code = "provider_http_error"
        status = 502
        message = f"LRCLIB HTTP {status_code}"
        if status_code == 429:
            code = "provider_rate_limited"
            status = 429
            message = "LRCLIB rate limited (HTTP 429)"

        raise LRCLibError(
            code=code,
            message=message,
            status=status,
            details=body or str(exc),
        ) from exc

    raise LRCLibError(
        code="provider_unavailable",
        message="LRCLIB request failed",
        status=503,
        details=str(exc),
    ) from exc


class LrcLibClient:
    BASE_URL = "https://lrclib.net/api"

    def __init__(
        self,
        timeout: Tuple[float, float] = (3.0, 15.0),
        user_agent: str = "Sound2Mean/0.1",
    ):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Connection": "close",
            }
        )

        retry = Retry(
            total=3,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)

    def search(
        self,
        *,
        query: Optional[str] = None,
        track_name: Optional[str] = None,
        artist_name: Optional[str] = None,
        album_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if query:
            params["query"] = query
        if track_name:
            params["track_name"] = track_name
        if artist_name:
            params["artist_name"] = artist_name
        if album_name:
            params["album_name"] = album_name

        try:
            response = self.session.get(f"{self.BASE_URL}/search", params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            _raise_lrclib_error(exc)
        except requests.exceptions.ConnectionError as exc:
            _raise_lrclib_error(exc)
        except requests.exceptions.HTTPError as exc:
            _raise_lrclib_error(exc)
        except requests.exceptions.RequestException as exc:
            _raise_lrclib_error(exc)

        data = response.json()
        return data if isinstance(data, list) else []

    def get(self, track_id: int) -> Optional[Dict[str, Any]]:
        try:
            response = self.session.get(f"{self.BASE_URL}/get", params={"id": track_id}, timeout=self.timeout)
            if response.status_code == 404:
                return None
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            _raise_lrclib_error(exc)
        except requests.exceptions.ConnectionError as exc:
            _raise_lrclib_error(exc)
        except requests.exceptions.HTTPError as exc:
            _raise_lrclib_error(exc)
        except requests.exceptions.RequestException as exc:
            _raise_lrclib_error(exc)

        data = response.json()
        return data if isinstance(data, dict) else None
