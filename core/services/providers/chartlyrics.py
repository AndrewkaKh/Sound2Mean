# core/services/providers/chartlyrics.py
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

import requests
from lxml import etree as LET

BASE_URL = "http://api.chartlyrics.com/apiv1.asmx/"
NAMESPACE = "{http://api.chartlyrics.com/}"


@dataclass(frozen=True)
class ChartLyricsCandidate:
    track_id: int
    lyric_id: int
    lyric_checksum: str
    artist: str
    song: str
    song_rank: int
    song_url: Optional[str]
    artist_url: Optional[str]


class ChartLyricsClient:
    """
    GET endpoints:
      - SearchLyricText?lyricText=...
      - GetLyric?lyricId=...&lyricCheckSum=...
    """
    def __init__(self, timeout_seconds: float = 4.0, user_agent: str = "Sound2Mean/0.1"):
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def _get_bytes(self, op: str, params: Dict[str, Any]) -> bytes:
        url = f"{BASE_URL}{op}"
        r = self.session.get(url, params=params, timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.content

    @staticmethod
    def _root(content: bytes) -> LET._Element:
        parser = LET.XMLParser(recover=True)
        return LET.fromstring(content, parser=parser)

    @staticmethod
    def _findall_anyns(root: LET._Element, tag: str) -> List[LET._Element]:
        """
        Пытаемся найти и с namespace, и без namespace (на всякий).
        """
        out = root.findall(f".//{NAMESPACE}{tag}")
        if out:
            return out
        return root.findall(f".//{tag}")

    @staticmethod
    def _text(el: LET._Element, child: str) -> str:
        """
        Берём текст у дочернего тега, пробуем и с ns, и без ns.
        """
        n = el.find(f"{NAMESPACE}{child}")
        if n is None:
            n = el.find(child)
        return (n.text or "").strip() if n is not None else ""

    def search_by_text(self, fragment: str) -> List[ChartLyricsCandidate]:
        fragment = (fragment or "").strip()
        if not fragment:
            return []

        try:
            content = self._get_bytes("SearchLyricText", {"lyricText": fragment})
            root = self._root(content)
        except Exception:
            return []

        results: List[ChartLyricsCandidate] = []
        for el in self._findall_anyns(root, "SearchLyricResult"):
            try:
                results.append(
                    ChartLyricsCandidate(
                        track_id=int(self._text(el, "TrackId") or 0),
                        lyric_id=int(self._text(el, "LyricId") or 0),
                        lyric_checksum=self._text(el, "LyricChecksum"),
                        artist=self._text(el, "Artist"),
                        song=self._text(el, "Song"),
                        song_rank=int(self._text(el, "SongRank") or 0),
                        song_url=self._text(el, "SongUrl") or None,
                        artist_url=self._text(el, "ArtistUrl") or None,
                    )
                )
            except Exception:
                continue

        return results

    def get_lyric(self, lyric_id: int, checksum: str) -> Optional[dict]:
        try:
            content = self._get_bytes("GetLyric", {"lyricId": lyric_id, "lyricCheckSum": checksum})
            root = self._root(content)
        except Exception:
            return None

        def rt(name: str) -> str:
            # пробуем найти поле в любом месте
            node = root.find(f".//{NAMESPACE}{name}") or root.find(f".//{name}")
            return (node.text or "").strip() if node is not None else ""

        return {
            "source": "chartlyrics",
            "track_id": int(rt("TrackId") or 0),
            "lyric_id": int(rt("LyricId") or 0),
            "checksum": rt("LyricChecksum"),
            "title": rt("LyricSong"),
            "artist": rt("LyricArtist"),
            "lyrics": rt("Lyric"),
            "url": rt("LyricUrl") or None,
            "rank": int(rt("LyricRank") or 0),
        }