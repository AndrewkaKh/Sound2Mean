import secrets

from django.core.cache import cache

CODE_TTL_SECONDS = 300
CODE_CACHE_PREFIX = "tg_login_code:"


def generate_code() -> str:
    return f"{secrets.randbelow(900000) + 100000:06d}"


def store_code(telegram_id: int, code: str) -> None:
    cache.set(f"{CODE_CACHE_PREFIX}{telegram_id}", code, CODE_TTL_SECONDS)


def verify_code(telegram_id: int, code: str) -> bool:
    expected = cache.get(f"{CODE_CACHE_PREFIX}{telegram_id}")
    if not expected:
        return False
    code = (code or "").strip()
    if not code or code != expected:
        return False
    cache.delete(f"{CODE_CACHE_PREFIX}{telegram_id}")
    return True
