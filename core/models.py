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
