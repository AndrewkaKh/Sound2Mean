from __future__ import annotations

import random

from ..models import VocabularyWord

DECK_ALL = "all"
DECK_FAVORITES = "favorites"
VALID_DECKS = {DECK_ALL, DECK_FAVORITES}


def get_deck_mode(request) -> str:
    mode = request.session.get("flashcard_mode", DECK_ALL)
    return mode if mode in VALID_DECKS else DECK_ALL


def set_deck_mode(request, mode: str) -> None:
    if mode not in VALID_DECKS:
        mode = DECK_ALL
    if get_deck_mode(request) != mode:
        request.session["flashcard_mode"] = mode
        reset_queue(request)


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
