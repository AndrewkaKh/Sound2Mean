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
    context = models.TextField(blank=True, default="")
    song_source = models.CharField(max_length=50, blank=True, default="")
    song_external_id = models.CharField(max_length=100, blank=True, default="")
    song_title = models.CharField(max_length=255, blank=True, default="")
    song_artist = models.CharField(max_length=255, blank=True, default="")
    is_favorite = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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


class WordPlaylist(models.Model):
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="word_playlists",
    )
    name = models.CharField(max_length=100)
    share_code = models.CharField(max_length=12, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Word playlist"
        verbose_name_plural = "Word playlists"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_playlist_name_per_user",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class WordPlaylistItem(models.Model):
    playlist = models.ForeignKey(
        WordPlaylist,
        on_delete=models.CASCADE,
        related_name="items",
    )
    word = models.ForeignKey(
        VocabularyWord,
        on_delete=models.CASCADE,
        related_name="playlist_items",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Word playlist item"
        verbose_name_plural = "Word playlist items"
        ordering = ["word__word_en", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "word"],
                name="unique_word_per_playlist",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.playlist.name}: {self.word.word_en}"


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


class SongTranslation(models.Model):
    source = models.CharField(max_length=50, default="lrclib")
    external_id = models.CharField(max_length=100)
    language = models.CharField(max_length=10, default="ru")
    original_hash = models.CharField(max_length=64)
    translated_text = models.TextField(blank=True)
    aligned_lines = models.JSONField(default=list, blank=True)
    provider = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id", "language", "original_hash"],
                name="unique_song_translation",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.external_id}:{self.language}"
