from django.contrib import admin

from .models import SearchHistory, TelegramUser


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username")
    search_fields = ("username", "telegram_id")


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "query", "normalized_query", "created_at")
    search_fields = ("query", "normalized_query", "user__username", "user__telegram_id")
    list_filter = ("created_at",)
