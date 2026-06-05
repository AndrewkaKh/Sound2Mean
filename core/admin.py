from django.contrib import admin
from .models import TelegramUser, VocabularyWord, SearchHistory, SongTranslation


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username")
    search_fields = ("username", "telegram_id")


@admin.register(VocabularyWord)
class VocabularyWordAdmin(admin.ModelAdmin):
    list_display = ("word_en", "word_ru", "is_favorite", "user")
    list_filter = ("user", "is_favorite")
    search_fields = ("word_en", "word_ru", "user__username")
@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "query", "normalized_query", "created_at")
    search_fields = ("query", "normalized_query", "user__username", "user__telegram_id")
    list_filter = ("created_at",)


@admin.register(SongTranslation)
class SongTranslationAdmin(admin.ModelAdmin):
    list_display = ("source", "external_id", "language", "provider", "updated_at")
    search_fields = ("source", "external_id", "language", "provider")
