from django.contrib import admin
from .models import TelegramUser, VocabularyWord, SearchHistory, SongTranslation, WordPlaylist, WordPlaylistItem


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username")
    search_fields = ("username", "telegram_id")


@admin.register(VocabularyWord)
class VocabularyWordAdmin(admin.ModelAdmin):
    list_display = ("word_en", "word_ru", "song_title", "is_favorite", "user", "updated_at")
    list_filter = ("user", "is_favorite")
    search_fields = ("word_en", "word_ru", "context", "song_title", "song_artist", "user__username")


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "query", "normalized_query", "created_at")
    search_fields = ("query", "normalized_query", "user__username", "user__telegram_id")
    list_filter = ("created_at",)


@admin.register(SongTranslation)
class SongTranslationAdmin(admin.ModelAdmin):
    list_display = ("source", "external_id", "language", "provider", "updated_at")
    search_fields = ("source", "external_id", "language", "provider")


@admin.register(WordPlaylist)
class WordPlaylistAdmin(admin.ModelAdmin):
    list_display = ("name", "share_code", "user", "created_at")
    search_fields = ("name", "share_code", "user__username")
    readonly_fields = ("share_code",)


@admin.register(WordPlaylistItem)
class WordPlaylistItemAdmin(admin.ModelAdmin):
    list_display = ("playlist", "word", "added_at")
    search_fields = ("playlist__name", "word__word_en")
