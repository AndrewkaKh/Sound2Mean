from django.db import models


class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Telegram user"
        verbose_name_plural = "Telegram users"

    def __str__(self) -> str:
        if self.username:
            return f"@{self.username}"
        return f"tg:{self.telegram_id}"

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return f"ID {self.telegram_id}"


class SearchHistory(models.Model):
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="search_history",
    )
    query = models.CharField(max_length=255)
    normalized_query = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "normalized_query"],
                name="unique_telegram_user_search_query",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user}: {self.query}"
