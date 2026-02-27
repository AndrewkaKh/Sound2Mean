# core/services/providers/lrclib.py
from typing import Any, Dict, List, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry



class LrcLibClient:
    BASE_URL = "https://lrclib.net/api"

    def __init__(
        self,
        timeout: Tuple[float, float] = (3.0, 15.0),  # (connect, read)
        user_agent: str = "Sound2Mean/0.1",
    ):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Connection": "close",   # важно при EOF
        })

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

        r = self.session.get(f"{self.BASE_URL}/search", params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def get(self, track_id: int) -> Optional[Dict[str, Any]]:
        r = self.session.get(f"{self.BASE_URL}/get", params={"id": track_id}, timeout=self.timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else None