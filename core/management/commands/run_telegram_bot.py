import time

from django.conf import settings
from django.core.management.base import BaseCommand

from core.services.telegram_bot import TelegramBotError, get_updates, send_message
from core.services.telegram_users import upsert_from_telegram


class Command(BaseCommand):
    help = "Telegram bot: /start registers user for site login"

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stderr.write("Set TELEGRAM_BOT_TOKEN in .env")
            return

        bot_name = settings.TELEGRAM_BOT_USERNAME or "bot"
        proxy = settings.TELEGRAM_PROXY or "(direct)"
        self.stdout.write(self.style.SUCCESS(f"Bot @{bot_name} running, proxy={proxy}"))

        offset = None
        while True:
            try:
                updates = get_updates(offset=offset, timeout=30)
            except TelegramBotError as e:
                self.stderr.write(f"getUpdates error: {e}")
                time.sleep(5)
                continue
            except Exception as e:
                self.stderr.write(f"error: {e}")
                time.sleep(5)
                continue

            for item in updates:
                offset = item["update_id"] + 1
                message = item.get("message") or {}
                text = (message.get("text") or "").strip()
                chat = message.get("chat") or {}
                chat_id = chat.get("id")
                if not chat_id:
                    continue

                from_user = message.get("from") or {}
                telegram_id = from_user.get("id") or chat_id
                username = from_user.get("username") or ""

                if text.startswith("/start"):
                    user = upsert_from_telegram(
                        telegram_id=telegram_id,
                        username=username,
                    )
                    try:
                        send_message(
                            chat_id,
                            f"Привет, {user.display_name}!\n\n"
                            "Вы зарегистрированы в Sound2Mean.\n"
                            "На сайте укажите @username и нажмите «Получить код».",
                        )
                    except TelegramBotError as e:
                        self.stderr.write(f"sendMessage error: {e}")
                elif text in ("/help", "help"):
                    try:
                        send_message(
                            chat_id,
                            "1) /start — регистрация\n"
                            "2) На сайте введите @username\n"
                            "3) Получите код и войдите",
                        )
                    except TelegramBotError as e:
                        self.stderr.write(f"sendMessage error: {e}")
