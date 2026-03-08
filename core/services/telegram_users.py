from .login_code import generate_code, store_code
from .telegram_bot import send_message
from ..models import TelegramUser


def normalize_username(value: str) -> str:
    return (value or "").strip().lstrip("@").lower()


def upsert_from_telegram(*, telegram_id: int, username: str) -> TelegramUser:
    return TelegramUser.objects.update_or_create(
        telegram_id=telegram_id,
        defaults={"username": normalize_username(username)},
    )[0]


def find_by_username(username: str) -> TelegramUser | None:
    normalized = normalize_username(username)
    if not normalized:
        return None
    return TelegramUser.objects.filter(username=normalized).first()


def send_login_code(user: TelegramUser) -> None:
    code = generate_code()
    store_code(user.telegram_id, code)
    send_message(
        user.telegram_id,
        f"Код для входа на Sound2Mean: {code}\n\nДействует 5 минут.",
    )
