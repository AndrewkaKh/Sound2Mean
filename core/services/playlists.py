from __future__ import annotations

import secrets
import string
from typing import Any, Literal

from django.db import DatabaseError, IntegrityError, transaction

from ..models import TelegramUser, VocabularyWord, WordPlaylist, WordPlaylistItem

ShareCodeAlphabet = string.ascii_uppercase + string.digits
ImportPlaylistStatus = Literal["imported", "not_found", "invalid", "own", "failed"]


def normalize_playlist_name(name: str) -> str:
    return " ".join((name or "").split())


def normalize_share_code(code: str) -> str:
    return "".join((code or "").split()).upper()


def generate_share_code() -> str:
    while True:
        code = "".join(secrets.choice(ShareCodeAlphabet) for _ in range(8))
        if not WordPlaylist.objects.filter(share_code=code).exists():
            return code


def get_user_playlists(user: TelegramUser) -> list[WordPlaylist]:
    return list(
        WordPlaylist.objects.filter(user=user)
        .prefetch_related("items__word")
        .order_by("name", "id")
    )


def build_playlists_payload(user: TelegramUser, *, word_id: int | None = None) -> list[dict[str, Any]]:
    membership: set[int] = set()
    if word_id:
        membership = set(
            WordPlaylistItem.objects.filter(
                playlist__user=user,
                word_id=word_id,
            ).values_list("playlist_id", flat=True)
        )

    payload: list[dict[str, Any]] = []
    for playlist in get_user_playlists(user):
        items = list(playlist.items.all())
        payload.append(
            {
                "id": playlist.id,
                "name": playlist.name,
                "share_code": playlist.share_code,
                "word_count": len(items),
                "contains_word": playlist.id in membership if word_id else False,
            }
        )
    return payload


def _unique_playlist_name(user: TelegramUser, base_name: str) -> str:
    name = base_name
    counter = 2
    while WordPlaylist.objects.filter(user=user, name=name).exists():
        name = f"{base_name} ({counter})"
        counter += 1
    return name


def create_playlist(user: TelegramUser, name: str) -> WordPlaylist | None:
    cleaned = normalize_playlist_name(name)
    if not cleaned:
        return None

    try:
        return WordPlaylist.objects.create(
            user=user,
            name=cleaned,
            share_code=generate_share_code(),
        )
    except IntegrityError:
        return None
    except DatabaseError:
        return None


def get_playlist_for_user(user: TelegramUser, playlist_id: int) -> WordPlaylist | None:
    return WordPlaylist.objects.filter(pk=playlist_id, user=user).first()


def get_playlist_by_share_code(code: str) -> WordPlaylist | None:
    normalized = normalize_share_code(code)
    if not normalized:
        return None
    return WordPlaylist.objects.filter(share_code=normalized).prefetch_related("items__word").first()


def get_word_for_user(user: TelegramUser, word_id: int) -> VocabularyWord | None:
    return VocabularyWord.objects.filter(pk=word_id, user=user).first()


def add_word_to_playlist(user: TelegramUser, playlist_id: int, word_id: int) -> bool:
    playlist = get_playlist_for_user(user, playlist_id)
    word = get_word_for_user(user, word_id)
    if not playlist or not word:
        return False

    try:
        WordPlaylistItem.objects.get_or_create(playlist=playlist, word=word)
        return True
    except (IntegrityError, DatabaseError):
        return False


def remove_word_from_playlist(user: TelegramUser, playlist_id: int, word_id: int) -> bool:
    deleted, _ = WordPlaylistItem.objects.filter(
        playlist_id=playlist_id,
        playlist__user=user,
        word_id=word_id,
        word__user=user,
    ).delete()
    return deleted > 0


def delete_playlist(user: TelegramUser, playlist_id: int) -> bool:
    deleted, _ = WordPlaylist.objects.filter(pk=playlist_id, user=user).delete()
    return deleted > 0


def import_playlist_by_code(user: TelegramUser, code: str) -> tuple[ImportPlaylistStatus, WordPlaylist | None]:
    normalized = normalize_share_code(code)
    if not normalized or len(normalized) != 8:
        return "invalid", None

    source = get_playlist_by_share_code(normalized)
    if not source:
        return "not_found", None
    if source.user_id == user.pk:
        return "own", source

    try:
        with transaction.atomic():
            playlist = WordPlaylist.objects.create(
                user=user,
                name=_unique_playlist_name(user, source.name),
                share_code=generate_share_code(),
            )
            for item in source.items.select_related("word"):
                src_word = item.word
                word, _ = VocabularyWord.objects.get_or_create(
                    user=user,
                    word_en=src_word.word_en,
                    defaults={
                        "word_ru": src_word.word_ru,
                        "context": src_word.context,
                        "song_source": src_word.song_source,
                        "song_external_id": src_word.song_external_id,
                        "song_title": src_word.song_title,
                        "song_artist": src_word.song_artist,
                    },
                )
                WordPlaylistItem.objects.get_or_create(playlist=playlist, word=word)
        return "imported", playlist
    except (IntegrityError, DatabaseError):
        return "failed", None


def toggle_word_in_playlist(user: TelegramUser, playlist_id: int, word_id: int) -> bool | None:
    playlist = get_playlist_for_user(user, playlist_id)
    word = get_word_for_user(user, word_id)
    if not playlist or not word:
        return None

    try:
        with transaction.atomic():
            item = WordPlaylistItem.objects.filter(playlist=playlist, word=word).first()
            if item:
                item.delete()
                return False
            WordPlaylistItem.objects.create(playlist=playlist, word=word)
            return True
    except (IntegrityError, DatabaseError):
        return None
