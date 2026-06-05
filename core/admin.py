from django.contrib import admin

from .models import TelegramUser, VocabularyWord


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username")
    search_fields = ("username", "telegram_id")


@admin.register(VocabularyWord)
class VocabularyWordAdmin(admin.ModelAdmin):
    list_display = ("word_en", "word_ru", "is_favorite", "user")
    list_filter = ("user", "is_favorite")
    search_fields = ("word_en", "word_ru", "user__username")
