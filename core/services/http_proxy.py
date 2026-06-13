from django.conf import settings


def normalize_proxy(proxy: str) -> str:
    proxy = proxy.strip()
    if proxy.startswith("socks5://"):
        return "socks5h://" + proxy[len("socks5://") :]
    if proxy.startswith("https://127.0.0.1:") or proxy.startswith("https://host.docker.internal:"):
        return "http://" + proxy[len("https://") :]
    return proxy


def get_proxy_request_kwargs() -> dict:
    proxy = getattr(settings, "TELEGRAM_PROXY", "") or ""
    if not proxy:
        return {}
    proxy = normalize_proxy(proxy)
    return {"proxies": {"http": proxy, "https": proxy}}
