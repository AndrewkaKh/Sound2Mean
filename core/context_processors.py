from django.conf import settings


def telegram_auth(request):
    tg_user = request.session.get("tg_user")
    bot_username = getattr(settings, "TELEGRAM_BOT_USERNAME", "") or ""
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
    return {
        "tg_user": tg_user,
        "telegram_bot_username": bot_username,
        "telegram_bot_configured": bool(bot_token),
        "telegram_bot_url": f"https://t.me/{bot_username}" if bot_username else "",
    }
