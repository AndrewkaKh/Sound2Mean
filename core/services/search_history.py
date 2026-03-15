from __future__ import annotations

import re
from typing import List, Optional

from django.db import DatabaseError, transaction

from ..models import SearchHistory, TelegramUser

MAX_HISTORY_ITEMS = 5


def normalize_history_query(query: str) -> str:
    value = (query or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def get_recent_queries_for_user(user: TelegramUser, limit: int = MAX_HISTORY_ITEMS) -> List[str]:
    if not user:
        return []

    return list(
        SearchHistory.objects.filter(user=user)
        .order_by("-created_at", "-id")
        .values_list("query", flat=True)[: max(1, limit)]
    )


def save_user_query(user: Optional[TelegramUser], query: str, limit: int = MAX_HISTORY_ITEMS) -> None:
    if not user:
        return

    normalized_query = normalize_history_query(query)
    if not normalized_query:
        return

    display_query = re.sub(r"\s+", " ", (query or "").strip())
    try:
        with transaction.atomic():
            entry, created = SearchHistory.objects.get_or_create(
                user=user,
                normalized_query=normalized_query,
                defaults={"query": display_query},
            )
            if not created:
                entry.query = display_query
                entry.save(update_fields=["query", "created_at"])

            stale_ids = list(
                SearchHistory.objects.filter(user=user)
                .order_by("-created_at", "-id")
                .values_list("id", flat=True)[limit:]
            )
            if stale_ids:
                SearchHistory.objects.filter(user=user, id__in=stale_ids).delete()
    except DatabaseError:
        return
