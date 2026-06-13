from __future__ import annotations

import random

from ..models import VocabularyWord

DECK_ALL = "all"
DECK_FAVORITES = "favorites"
PLAYLIST_DECK_PREFIX = "playlist:"
VALID_DECKS = {DECK_ALL, DECK_FAVORITES}


def is_playlist_deck(deck_mode: str) -> bool:
    return deck_mode.startswith(PLAYLIST_DECK_PREFIX)


def parse_playlist_id(deck_mode: str) -> int | None:
    if not is_playlist_deck(deck_mode):
        return None
    try:
        return int(deck_mode.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def playlist_deck_mode(playlist_id: int) -> str:
    return f"{PLAYLIST_DECK_PREFIX}{playlist_id}"


def get_deck_mode(request) -> str:
    mode = request.session.get("flashcard_mode", DECK_ALL)
    if mode in VALID_DECKS or is_playlist_deck(mode):
        return mode
    return DECK_ALL


def set_deck_mode(request, mode: str) -> None:
    if mode not in VALID_DECKS and not is_playlist_deck(mode):
        mode = DECK_ALL
    current = request.session.get("flashcard_mode", DECK_ALL)
    if current != mode:
        request.session["flashcard_mode"] = mode
        reset_queue(request)


def set_playlist_deck(request, playlist_id: int) -> None:
    set_deck_mode(request, playlist_deck_mode(playlist_id))


def is_shuffle_enabled(request) -> bool:
    return bool(request.session.get("flashcard_shuffle", False))


def set_shuffle_enabled(request, enabled: bool) -> None:
    if is_shuffle_enabled(request) != enabled:
        request.session["flashcard_shuffle"] = enabled
        request.session.modified = True


def toggle_shuffle(request) -> bool:
    enabled = not is_shuffle_enabled(request)
    set_shuffle_enabled(request, enabled)
    return enabled


def reset_queue(request) -> None:
    request.session.pop("flashcard_current_id", None)
    request.session.modified = True


def get_user_word_ids(user, *, favorites_only: bool = False) -> list[int]:
    qs = VocabularyWord.objects.filter(user=user)
    if favorites_only:
        qs = qs.filter(is_favorite=True)
    return list(qs.order_by("id").values_list("id", flat=True))


def get_deck_word_ids(user, deck_mode: str) -> list[int]:
    playlist_id = parse_playlist_id(deck_mode)
    if playlist_id is not None:
        return list(
            VocabularyWord.objects.filter(
                user=user,
                playlist_items__playlist_id=playlist_id,
                playlist_items__playlist__user=user,
            )
            .order_by("word_en", "id")
            .values_list("id", flat=True)
        )
    return get_user_word_ids(user, favorites_only=(deck_mode == DECK_FAVORITES))


def can_advance(word_ids: list[int]) -> bool:
    return len(word_ids) > 1


def _pick_next_random(word_ids: list[int], current_id: int | None) -> int:
    if len(word_ids) == 1:
        return word_ids[0]
    candidates = [wid for wid in word_ids if wid != current_id]
    return random.choice(candidates) if candidates else word_ids[0]


def _pick_next_sequential(word_ids: list[int], current_id: int | None) -> int:
    if len(word_ids) == 1:
        return word_ids[0]
    if current_id not in word_ids:
        return word_ids[0]
    idx = word_ids.index(current_id)
    return word_ids[(idx + 1) % len(word_ids)]


def _pick_initial_id(request, word_ids: list[int]) -> int:
    if is_shuffle_enabled(request):
        return random.choice(word_ids)
    return word_ids[0]


def get_current_word_id(request, word_ids: list[int]) -> int | None:
    if not word_ids:
        request.session.pop("flashcard_current_id", None)
        return None

    word_id_set = set(word_ids)
    current_id = request.session.get("flashcard_current_id")
    if current_id not in word_id_set:
        current_id = _pick_initial_id(request, word_ids)
        request.session["flashcard_current_id"] = current_id
        request.session.modified = True
    return current_id


def advance_to_next(request, word_ids: list[int]) -> int | None:
    if not word_ids:
        return None

    if len(word_ids) == 1:
        request.session["flashcard_current_id"] = word_ids[0]
        request.session.modified = True
        return word_ids[0]

    current_id = request.session.get("flashcard_current_id")
    if is_shuffle_enabled(request):
        next_id = _pick_next_random(word_ids, current_id)
    else:
        next_id = _pick_next_sequential(word_ids, current_id)

    request.session["flashcard_current_id"] = next_id
    request.session.modified = True
    return next_id
