from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from django.core.cache import cache

from .providers.lrclib import LRCLibError, LrcLibClient

_lrclib = LrcLibClient(timeout=(3.0, 15.0), user_agent="Sound2Mean/0.1")
_last_provider_error: ContextVar[Optional[LRCLibError]] = ContextVar("last_lyrics_provider_error", default=None)

SEARCH_TTL_SECONDS = 60 * 30
SEARCH_LYRICS_TTL_SECONDS = 60 * 30
GET_TTL_SECONDS = 60 * 60 * 24 * 7

_WORD_RE = re.compile(r"[a-zA-Z']+")
_DASH_RE = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2212]+")
_BRACKET_RE = re.compile(r"\s*[\(\[\{][^()\[\]{}]*[\)\]\}]\s*")
_SPACE_DASH_SPLIT_RE = re.compile(r"^(?P<artist>.+?)(?:\s+-\s*|\s*-\s+)(?P<title>.+)$")
_PUNCT_RE = re.compile(r"[^0-9a-z\s-]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "feat",
    "featuring",
    "for",
    "from",
    "ft",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def _norm(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _set_last_provider_error(error: Optional[LRCLibError]) -> None:
    _last_provider_error.set(error)


def get_last_provider_error() -> Optional[LRCLibError]:
    return _last_provider_error.get()


def consume_last_provider_error() -> Optional[LRCLibError]:
    error = _last_provider_error.get()
    _last_provider_error.set(None)
    return error


def normalize_search_text(text: str, *, strip_parenthetical: bool = False) -> str:
    value = (text or "").strip().lower()
    if not value:
        return ""

    value = _DASH_RE.sub("-", value)
    if strip_parenthetical:
        previous = None
        while previous != value:
            previous = value
            value = _BRACKET_RE.sub(" ", value)

    value = value.replace("&", " and ")
    value = value.replace("/", " ")
    value = value.replace("\\", " ")
    value = re.sub(r"[\"'`\u201c\u201d\u2018\u2019]", "", value)
    value = re.sub(r"\s*-\s*", " - ", value)
    value = _PUNCT_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" -")
    return value


def parse_artist_title_query(query: str) -> Optional[Dict[str, str]]:
    value = _norm(query or "")
    if not value:
        return None

    value = _DASH_RE.sub("-", value)
    match = _SPACE_DASH_SPLIT_RE.match(value)
    if not match:
        return None

    artist = _norm(match.group("artist"))
    title = _norm(match.group("title"))
    if not artist or not title:
        return None

    return {
        "artist": artist,
        "track_name": title,
    }


def _candidate_norm(value: str, *, strip_parenthetical: bool = True) -> str:
    return normalize_search_text(value, strip_parenthetical=strip_parenthetical)


def _significant_tokens(text: str) -> List[str]:
    normalized = _candidate_norm(text)
    seen = set()
    tokens: List[str] = []

    for token in _WORD_RE.findall(normalized):
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)

    return tokens[:8]


def _token_similarity(left: str, right: str) -> float:
    left_tokens = _significant_tokens(left)
    right_tokens = _significant_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0

    total = 0.0
    for left_token in left_tokens:
        total += max(SequenceMatcher(None, left_token, right_token).ratio() for right_token in right_tokens)
    return total / len(left_tokens)


def _phrase_similarity(left: str, right: str) -> float:
    left_norm = _candidate_norm(left)
    right_norm = _candidate_norm(right)
    if not left_norm or not right_norm:
        return 0.0

    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    token_ratio = _token_similarity(left_norm, right_norm)
    contains_bonus = 0.0

    if left_norm in right_norm or right_norm in left_norm:
        contains_bonus = 0.18

    left_words = left_norm.split()
    right_words = right_norm.split()
    if left_words and right_words:
        prefix_hits = 0
        for left_word in left_words:
            if any(
                right_word.startswith(left_word) or left_word.startswith(right_word)
                for right_word in right_words
            ):
                prefix_hits += 1
        contains_bonus += min(0.14, (prefix_hits / len(left_words)) * 0.14)

    return min(1.0, (ratio * 0.52) + (token_ratio * 0.34) + contains_bonus)


def _candidate_key_from_parts(title: str, artist: str) -> Tuple[str, str]:
    return (
        _candidate_norm(title),
        _candidate_norm(artist),
    )


def _candidate_key(item: Dict[str, Any]) -> Tuple[str, str]:
    title = item.get("trackName") or item.get("name") or ""
    artist = item.get("artistName") or ""
    return _candidate_key_from_parts(title, artist)


def _raw_item_completeness(item: Dict[str, Any]) -> int:
    plain = len(item.get("plainLyrics") or "")
    synced = len(item.get("syncedLyrics") or "")
    album = 20 if item.get("albumName") else 0
    duration = 5 if item.get("duration") else 0
    return plain + synced + album + duration


def _cache_key(prefix: str, *parts: str) -> str:
    raw = "|".join([prefix, *parts])
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
    return f"s2m:{prefix}:{digest}"


def _search_cache_keys(
    q: Optional[str],
    artist: Optional[str],
    track_name: Optional[str],
    limit: int,
) -> Tuple[str, str]:
    query_norm = _norm(q or "").lower()
    artist_norm = _norm(artist or "").lower()
    track_norm = _norm(track_name or "").lower()
    base = _cache_key("lrclib_search", query_norm, artist_norm, track_norm, str(limit))
    return base + ":cands", base + ":lyrics"


def _make_preview(plain: str, synced: str, max_len: int = 180) -> str:
    text = plain or synced or ""
    if not text:
        return ""

    text = re.sub(r"\[\d{2}:\d{2}\.\d{2}\]\s*", "", text)
    text = text.replace("\r", "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return (text[: max_len - 1] + "...") if len(text) > max_len else text


def _text_match_score(fragment: str, lyrics: str) -> float:
    fragment_norm = _norm(fragment).lower()
    lyrics_norm = (lyrics or "").lower()
    score = 0.0

    if fragment_norm and fragment_norm in lyrics_norm:
        score += 5.0

    tokens = [token for token in _WORD_RE.findall(fragment_norm) if len(token) >= 3][:12]
    if tokens:
        hits = sum(1 for token in tokens if token in lyrics_norm)
        score += (hits / len(tokens)) * 3.0

    return score


def _lyrics_similarity(fragment: str, lyrics: str) -> float:
    if not fragment or not lyrics:
        return 0.0
    phrase = _phrase_similarity(fragment, lyrics)
    token = min(1.0, _text_match_score(fragment, lyrics) / 8.0)
    return min(1.0, (phrase * 0.65) + (token * 0.35))


def _candidate_score(
    item: Dict[str, Any],
    *,
    query: str,
    query_search: str,
    artist_query: str,
    track_query: str,
    strict_artist_title: bool,
) -> Optional[float]:
    title = item.get("trackName") or item.get("name") or ""
    artist = item.get("artistName") or ""
    combo = " - ".join(part for part in [artist, title] if part)
    lyrics = item.get("plainLyrics") or item.get("syncedLyrics") or ""
    artist_similarity = _phrase_similarity(artist_query, artist) if artist_query else 0.0
    title_similarity = _phrase_similarity(track_query, title) if track_query else 0.0
    full_similarity = _phrase_similarity(query or query_search, combo) if (query or query_search) else 0.0
    lyrics_fragment = track_query or query_search or query
    lyrics_similarity = _lyrics_similarity(lyrics_fragment, lyrics)

    if strict_artist_title and artist_query:
        if artist_similarity < 0.2:
            return None

        score = (
            (artist_similarity * 0.45)
            + (title_similarity * 0.40)
            + (full_similarity * 0.10)
            + (lyrics_similarity * 0.05)
        )
        if artist_similarity < 0.35:
            score *= 0.2

        if artist_similarity >= 0.75 and lyrics_similarity >= 0.55:
            score += 0.04

        return round(min(1.0, score), 3)

    score = 0.0
    if query:
        score += _phrase_similarity(query, title) * 0.34
        score += _phrase_similarity(query, artist) * 0.16
        score += _phrase_similarity(query, combo) * 0.30
        if lyrics:
            score += _lyrics_similarity(query_search or query, lyrics) * 0.12

    if track_query:
        score += title_similarity * 0.26

    if artist_query:
        score += artist_similarity * 0.18

    if query_search:
        title_norm = _candidate_norm(title)
        combo_norm = _candidate_norm(combo)
        if query_search == title_norm:
            score += 0.08
        if query_search == combo_norm:
            score += 0.08

    if track_query and track_query == _candidate_norm(title):
        score += 0.07

    if artist_query and artist_query == _candidate_norm(artist):
        score += 0.05

    return round(min(1.0, score), 3)


def _simplify_candidate(item: Dict[str, Any], score: float) -> Dict[str, Any]:
    plain = item.get("plainLyrics") or ""
    synced = item.get("syncedLyrics") or ""
    return {
        "source": "lrclib",
        "id": item.get("id"),
        "title": item.get("trackName") or item.get("name"),
        "artist": item.get("artistName"),
        "album": item.get("albumName") or "",
        "duration": item.get("duration"),
        "instrumental": item.get("instrumental"),
        "has_plain": bool(plain),
        "has_synced": bool(synced),
        "preview": _make_preview(plain, synced),
        "score": round(float(score), 3),
        "_plainLyrics": plain,
        "_syncedLyrics": synced,
    }


def _add_search_attempt(
    attempts: List[Dict[str, Optional[str]]],
    seen: set[Tuple[Tuple[str, str], ...]],
    *,
    query: Optional[str] = None,
    artist_name: Optional[str] = None,
    track_name: Optional[str] = None,
) -> None:
    params = {
        "query": _norm(query or "") or None,
        "artist_name": _norm(artist_name or "") or None,
        "track_name": _norm(track_name or "") or None,
    }
    if not params["query"] and not params["track_name"]:
        return

    key = tuple(sorted((param_name, param_value) for param_name, param_value in params.items() if param_value))
    if key in seen:
        return

    seen.add(key)
    attempts.append(params)


def _build_search_attempts(
    *,
    q: Optional[str],
    artist: Optional[str],
    track_name: Optional[str],
) -> Tuple[List[Dict[str, Optional[str]]], List[Dict[str, Optional[str]]], Dict[str, str]]:
    query = _norm(q or "")
    direct_artist = _norm(artist or "")
    direct_track = _norm(track_name or "")
    parsed = parse_artist_title_query(query)

    parsed_artist = parsed["artist"] if parsed else ""
    parsed_track = parsed["track_name"] if parsed else ""
    effective_artist = direct_artist or parsed_artist
    effective_track = direct_track or parsed_track
    strict_artist_title = bool(parsed_artist and parsed_track)

    normalized_query = normalize_search_text(query)
    normalized_query_stripped = normalize_search_text(query, strip_parenthetical=True)
    normalized_artist = normalize_search_text(effective_artist, strip_parenthetical=True)
    normalized_track = normalize_search_text(effective_track, strip_parenthetical=True)

    combined_query = query or " ".join(part for part in [effective_artist, effective_track] if part)
    combined_query = _norm(combined_query)

    significant_tokens = _significant_tokens(combined_query)
    track_tokens = _significant_tokens(effective_track or query)
    artist_tokens = _significant_tokens(effective_artist)

    primary: List[Dict[str, Optional[str]]] = []
    fallback: List[Dict[str, Optional[str]]] = []
    seen_primary: set[Tuple[Tuple[str, str], ...]] = set()
    seen_fallback: set[Tuple[Tuple[str, str], ...]] = set()

    if strict_artist_title:
        _add_search_attempt(primary, seen_primary, track_name=effective_track, artist_name=effective_artist or None)
        _add_search_attempt(primary, seen_primary, query=f"{effective_artist} {effective_track}")
        _add_search_attempt(primary, seen_primary, query=query)

        if normalized_track and normalized_artist:
            _add_search_attempt(primary, seen_primary, track_name=normalized_track, artist_name=normalized_artist)
            _add_search_attempt(primary, seen_primary, query=f"{normalized_artist} {normalized_track}")

        if normalized_query and normalized_query != query.lower():
            _add_search_attempt(primary, seen_primary, query=normalized_query, artist_name=normalized_artist or None)

        _add_search_attempt(fallback, seen_fallback, query=effective_artist)
        if artist_tokens and track_tokens:
            _add_search_attempt(fallback, seen_fallback, query=f"{artist_tokens[0]} {' '.join(track_tokens[:3])}")

        if normalized_query_stripped and normalized_query_stripped != normalized_query:
            _add_search_attempt(
                fallback,
                seen_fallback,
                query=normalized_query_stripped,
                artist_name=normalized_artist or None,
            )

        if track_tokens and normalized_artist:
            _add_search_attempt(
                fallback,
                seen_fallback,
                track_name=" ".join(track_tokens[:4]),
                artist_name=normalized_artist,
            )
        elif track_tokens:
            _add_search_attempt(fallback, seen_fallback, track_name=" ".join(track_tokens[:4]))
    else:
        if effective_track:
            _add_search_attempt(primary, seen_primary, track_name=effective_track, artist_name=effective_artist or None)
            _add_search_attempt(primary, seen_primary, track_name=effective_track)

        if query:
            _add_search_attempt(primary, seen_primary, query=query, artist_name=direct_artist or None)

        if normalized_query and normalized_query != query.lower():
            _add_search_attempt(primary, seen_primary, query=normalized_query, artist_name=normalized_artist or None)

        if normalized_track and (
            normalized_track != normalize_search_text(effective_track)
            or normalized_artist != normalize_search_text(effective_artist)
        ):
            _add_search_attempt(primary, seen_primary, track_name=normalized_track, artist_name=normalized_artist or None)

        if effective_artist and not effective_track:
            _add_search_attempt(primary, seen_primary, query=effective_artist)

        if parsed_artist and parsed_track:
            _add_search_attempt(primary, seen_primary, track_name=parsed_track, artist_name=parsed_artist)
            _add_search_attempt(primary, seen_primary, query=f"{parsed_artist} {parsed_track}")

        if normalized_query_stripped and normalized_query_stripped != normalized_query:
            _add_search_attempt(
                fallback,
                seen_fallback,
                query=normalized_query_stripped,
                artist_name=normalized_artist or None,
            )

        if significant_tokens:
            _add_search_attempt(fallback, seen_fallback, query=" ".join(significant_tokens[:4]))
            if len(significant_tokens) >= 2:
                _add_search_attempt(fallback, seen_fallback, query=" ".join(significant_tokens[:2]))
            if len(significant_tokens) >= 3:
                _add_search_attempt(fallback, seen_fallback, query=" ".join(significant_tokens[-3:]))

        if track_tokens and normalized_artist:
            _add_search_attempt(
                fallback,
                seen_fallback,
                track_name=" ".join(track_tokens[:4]),
                artist_name=normalized_artist,
            )
        elif track_tokens:
            _add_search_attempt(fallback, seen_fallback, track_name=" ".join(track_tokens[:4]))

        if artist_tokens and not effective_track:
            _add_search_attempt(fallback, seen_fallback, query=" ".join(artist_tokens[:3]))

    fallback = [attempt for attempt in fallback if attempt not in primary]

    context = {
        "query": _norm(combined_query),
        "query_search": normalized_query_stripped or normalized_query,
        "artist_query": normalized_artist,
        "track_query": normalized_track,
        "strict_artist_title": "1" if strict_artist_title else "",
    }
    return primary, fallback, context


def _merge_raw_results(
    pool: Dict[Tuple[str, str], Dict[str, Any]],
    results: List[Dict[str, Any]],
) -> None:
    for item in results:
        key = _candidate_key(item)
        if not any(key):
            continue

        current = pool.get(key)
        if current is None or _raw_item_completeness(item) >= _raw_item_completeness(current):
            pool[key] = item


def _rank_raw_results(
    pool: Dict[Tuple[str, str], Dict[str, Any]],
    *,
    limit: int,
    query: str,
    query_search: str,
    artist_query: str,
    track_query: str,
    strict_artist_title: bool,
) -> List[Tuple[float, Dict[str, Any]]]:
    ranked: List[Tuple[float, Dict[str, Any]]] = []

    for item in pool.values():
        track_id = item.get("id")
        title = item.get("trackName") or item.get("name") or ""
        artist = item.get("artistName") or ""
        if not track_id or not title or not artist:
            continue

        score = _candidate_score(
            item,
            query=query,
            query_search=query_search,
            artist_query=artist_query,
            track_query=track_query,
            strict_artist_title=strict_artist_title,
        )
        if score is None:
            continue

        ranked.append((score, item))

    ranked.sort(key=lambda pair: pair[0], reverse=True)

    if strict_artist_title and ranked:
        top_score = ranked[0][0]
        min_allowed = 0.4 if top_score >= 0.55 else 0.35
        ranked = [pair for pair in ranked if pair[0] >= min_allowed or pair[0] >= top_score - 0.08]

    top: List[Tuple[float, Dict[str, Any]]] = []
    seen = set()
    for score, item in ranked:
        key = _candidate_key(item)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        top.append((score, item))
        if len(top) >= limit:
            break

    return top


def _collect_search_results(
    attempts: List[Dict[str, Optional[str]]],
    pool: Dict[Tuple[str, str], Dict[str, Any]],
) -> None:
    for attempt in attempts:
        results = _lrclib.search(**attempt)
        _merge_raw_results(pool, results)


def search_candidates(
    *,
    q: Optional[str],
    artist: Optional[str],
    track_name: Optional[str] = None,
    limit: int = 10,
    cache_lyrics_top: int = 5,
) -> List[Dict[str, Any]]:
    _set_last_provider_error(None)
    limit = max(1, min(int(limit), 25))
    candidates_key, lyrics_map_key = _search_cache_keys(q, artist, track_name, limit)

    cached = cache.get(candidates_key)
    if cached is not None:
        return cached

    primary_attempts, fallback_attempts, context = _build_search_attempts(
        q=q,
        artist=artist,
        track_name=track_name,
    )

    try:
        pool: Dict[Tuple[str, str], Dict[str, Any]] = {}
        _collect_search_results(primary_attempts, pool)

        top = _rank_raw_results(
            pool,
            limit=limit,
            query=context["query"],
            query_search=context["query_search"],
            artist_query=context["artist_query"],
            track_query=context["track_query"],
            strict_artist_title=bool(context["strict_artist_title"]),
        )
 
        best_score = top[0][0] if top else 0.0
        needs_fallback = not top or len(top) < limit or best_score < 0.72
        if needs_fallback and fallback_attempts:
            _collect_search_results(fallback_attempts, pool)
            top = _rank_raw_results(
                pool,
                limit=limit,
                query=context["query"],
                query_search=context["query_search"],
                artist_query=context["artist_query"],
                track_query=context["track_query"],
                strict_artist_title=bool(context["strict_artist_title"]),
            )
    except LRCLibError as exc:
        _set_last_provider_error(exc)
        return []

    candidates = [_simplify_candidate(item, score) for score, item in top]

    lyrics_map: Dict[int, Dict[str, str]] = {}
    for score, item in top[: max(1, min(cache_lyrics_top, limit))]:
        track_id = item.get("id")
        if not track_id:
            continue
        lyrics_map[int(track_id)] = {
            "plainLyrics": item.get("plainLyrics") or "",
            "syncedLyrics": item.get("syncedLyrics") or "",
        }

    if candidates:
        cache.set(candidates_key, candidates, SEARCH_TTL_SECONDS)
        cache.set(lyrics_map_key, lyrics_map, SEARCH_LYRICS_TTL_SECONDS)

    return candidates


def get_song(track_id: int) -> Optional[Dict[str, Any]]:
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
    limit = max(1, min(int(limit), 25))
    candidates = search_candidates(q=q, artist=artist, track_name=track_name, limit=limit)
    if not candidates:
        return None

    best = candidates[0]
    track_id = best.get("id")
    if not track_id:
        return {"candidate": best, "lyrics": {"plainLyrics": "", "syncedLyrics": ""}}

    _, lyrics_map_key = _search_cache_keys(q, artist, track_name, limit)
    lyrics_map = cache.get(lyrics_map_key) or {}
    cached_lyrics = lyrics_map.get(int(track_id))

    if cached_lyrics and (cached_lyrics.get("plainLyrics") or cached_lyrics.get("syncedLyrics")):
        return {"candidate": best, "lyrics": cached_lyrics}

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
