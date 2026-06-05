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


class VocabularyWord(models.Model):
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="vocabulary_words",
    )
    word_en = models.CharField(max_length=255)
    word_ru = models.CharField(max_length=255)
    is_favorite = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Vocabulary word"
        verbose_name_plural = "Vocabulary words"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "word_en"],
                name="unique_word_en_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.word_en} — {self.word_ru}"
