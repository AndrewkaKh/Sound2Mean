from __future__ import annotations

import hashlib
import re
from typing import Optional, List, Dict, Any, Tuple

from django.core.cache import cache
from .providers.lrclib import LrcLibClient

_lrclib = LrcLibClient(timeout=(3.0, 15.0), user_agent="Sound2Mean/0.1")

SEARCH_TTL_SECONDS = 60 * 30            
SEARCH_LYRICS_TTL_SECONDS = 60 * 30 
GET_TTL_SECONDS = 60 * 60 * 24 * 7

_WORD_RE = re.compile(r"[a-zA-Z']+")


def _norm(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _cache_key(prefix: str, *parts: str) -> str:
    raw = "|".join([prefix, *parts])
    h = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
    return f"s2m:{prefix}:{h}"


def _search_cache_keys(q: Optional[str], artist: Optional[str], track_name: Optional[str], limit: int) -> Tuple[str, str]:
    qn = _norm(q or "").lower()
    an = _norm(artist or "").lower()
    tn = _norm(track_name or "").lower()
    # один ключ для кандидатов, второй — для lyrics-map по тем же параметрам
    base = _cache_key("lrclib_search", qn, an, tn, str(limit))
    return base + ":cands", base + ":lyrics"


def _make_preview(plain: str, synced: str, max_len: int = 180) -> str:
    text = plain or synced or ""
    if not text:
        return ""
    # для synced вырежем таймкоды вида [00:12.34]
    text = re.sub(r"\[\d{2}:\d{2}\.\d{2}\]\s*", "", text)
    text = text.replace("\r", "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return (text[: max_len - 1] + "…") if len(text) > max_len else text


def _text_match_score(fragment: str, lyrics: str) -> float:
    """
    Простой скоринг: точное вхождение + покрытие по словам.
    """
    f = _norm(fragment).lower()
    l = (lyrics or "").lower()
    score = 0.0

    if f and f in l:
        score += 5.0

    tokens = [t for t in _WORD_RE.findall(f) if len(t) >= 3][:12]
    if tokens:
        hit = sum(1 for t in tokens if t in l)
        score += (hit / len(tokens)) * 3.0

    return score


def _simplify_candidate(it: Dict[str, Any], score: float) -> Dict[str, Any]:
    plain = it.get("plainLyrics") or ""
    synced = it.get("syncedLyrics") or ""
    return {
        "source": "lrclib",
        "id": it.get("id"),
        "title": it.get("trackName") or it.get("name"),
        "artist": it.get("artistName"),
        "album": it.get("albumName") or "",
        "duration": it.get("duration"),
        "instrumental": it.get("instrumental"),
        "has_plain": bool(plain),
        "has_synced": bool(synced),
        "preview": _make_preview(plain, synced),
        "score": round(float(score), 3),

        # ДОБАВИТЬ:
        "_plainLyrics": plain,
        "_syncedLyrics": synced,
    }


def _lrclib_search_raw(q: Optional[str], artist: Optional[str], track_name: Optional[str]) -> List[Dict[str, Any]]:
    """
    LRCLIB поиски:
    - track_name + artist_name (надежнее)
    - query (+ artist_name) (на случай свободного запроса)
    """
    q = _norm(q or "")
    artist = _norm(artist or "")
    track_name = _norm(track_name or "")

    if track_name:
        return _lrclib.search(track_name=track_name, artist_name=artist or None)
    if q:
        return _lrclib.search(query=q, artist_name=artist or None)
    return []


def search_candidates(
    *,
    q: Optional[str],
    artist: Optional[str],
    track_name: Optional[str] = None,
    limit: int = 10,
    cache_lyrics_top: int = 5,
) -> List[Dict[str, Any]]:
    """
    Возвращает кандидатов для карточек (без full lyrics),
    но кладет в кэш небольшую map id->(plain/synced) для /resolve.
    """
    limit = max(1, min(int(limit), 25))
    cands_key, lyrmap_key = _search_cache_keys(q, artist, track_name, limit)

    cached = cache.get(cands_key)
    if cached is not None:
        return cached

    raw = _lrclib_search_raw(q, artist, track_name)

    items: List[Tuple[float, Dict[str, Any]]] = []
    qn = _norm(q or "")
    an = _norm(artist or "").lower()

    for it in raw:
        tid = it.get("id")
        title = it.get("trackName") or it.get("name") or ""
        art = it.get("artistName") or ""
        if not tid or not title or not art:
            continue

        score = 0.0
        if an and an == art.lower():
            score += 2.0

        plain = it.get("plainLyrics") or ""
        synced = it.get("syncedLyrics") or ""
        if qn and (plain or synced):
            score += _text_match_score(qn, plain or synced)

        items.append((score, it))

    items.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    top = []
    for score, it in items:
        title = (it.get("trackName") or it.get("name") or "").strip().lower()
        artist_name = (it.get("artistName") or "").strip().lower()
        key = (title, artist_name)
        if not title or not artist_name:
            continue
        if key in seen:
            continue
        seen.add(key)
        top.append((score, it))
        if len(top) >= limit:
            break

    out = [_simplify_candidate(it, score) for score, it in top]

    # lyrics-map (только для первых cache_lyrics_top, чтобы не хранить слишком много)
    lyr_map: Dict[int, Dict[str, str]] = {}
    for score, it in top[: max(1, min(cache_lyrics_top, limit))]:
        tid = it.get("id")
        if not tid:
            continue
        lyr_map[int(tid)] = {
            "plainLyrics": it.get("plainLyrics") or "",
            "syncedLyrics": it.get("syncedLyrics") or "",
        }

    if out:
        cache.set(cands_key, out, SEARCH_TTL_SECONDS)
        cache.set(lyrmap_key, lyr_map, SEARCH_LYRICS_TTL_SECONDS)

    return out


def get_song(track_id: int) -> Optional[Dict[str, Any]]:
    """
    Полная песня для /get (title/artist + lyrics).
    """
    key = _cache_key("lrclib_get", str(track_id))
    cached = cache.get(key)
    if cached is not None:
        return cached

    data = _lrclib.get(track_id)
    if not data:
        return None

    song = {
        "source": "lrclib",
        "id": data.get("id"),
        "title": data.get("trackName") or data.get("name"),
        "artist": data.get("artistName"),
        "album": data.get("albumName") or "",
        "duration": data.get("duration"),
        "instrumental": data.get("instrumental"),
        "plainLyrics": data.get("plainLyrics"),
        "syncedLyrics": data.get("syncedLyrics"),
    }

    cache.set(key, song, GET_TTL_SECONDS)
    return song


def resolve_lyrics(
    *,
    q: Optional[str],
    artist: Optional[str],
    track_name: Optional[str] = None,
    limit: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Идеальный формат: { candidate: <card>, lyrics: {plainLyrics, syncedLyrics} }
    Без дубля title/artist/id внутри lyrics.
    """
    limit = max(1, min(int(limit), 25))
    # сначала получим кандидатов
    cands = search_candidates(q=q, artist=artist, track_name=track_name, limit=limit)
    if not cands:
        return None

    best = cands[0]
    track_id = best.get("id")
    if not track_id:
        return {"candidate": best, "lyrics": {"plainLyrics": "", "syncedLyrics": ""}}

    # пробуем взять lyrics из кэша search->lyrics-map
    _, lyrmap_key = _search_cache_keys(q, artist, track_name, limit)
    lyr_map = cache.get(lyrmap_key) or {}
    cached_lyrics = lyr_map.get(int(track_id))

    if cached_lyrics and (cached_lyrics.get("plainLyrics") or cached_lyrics.get("syncedLyrics")):
        return {"candidate": best, "lyrics": cached_lyrics}

    # иначе добираем /get
    song = get_song(int(track_id))
    if not song:
        return {"candidate": best, "lyrics": {"plainLyrics": "", "syncedLyrics": ""}}

    return {
        "candidate": best,
        "lyrics": {
            "plainLyrics": song.get("plainLyrics") or "",
            "syncedLyrics": song.get("syncedLyrics") or "",
        },
    }