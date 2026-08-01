import os
from pathlib import Path

import requests

from launcher.utils.storage import get_launcher_dir


INJECTOR_FILENAME = "authlib-injector.jar"
_INJECTOR_CACHE = get_launcher_dir() / INJECTOR_FILENAME


def get_injector_path() -> Path:
    return _INJECTOR_CACHE


def injector_downloaded() -> bool:
    try:
        return _INJECTOR_CACHE.exists() and _INJECTOR_CACHE.stat().st_size > 1000
    except OSError:
        return False


def download_injector(api_url: str, verify_ssl: bool = True, timeout: int = 180) -> Path:
    """Download authlib-injector.jar from the Uroboros server into the launcher dir."""
    base = api_url.rstrip("/")
    url = f"{base}/launcher/injector"
    get_launcher_dir().mkdir(parents=True, exist_ok=True)
    tmp = _INJECTOR_CACHE.with_suffix(".jar.tmp")
    resp = requests.get(url, timeout=timeout, verify=verify_ssl, stream=True)
    resp.raise_for_status()
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    if tmp.stat().st_size <= 1000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Downloaded authlib-injector.jar is too small / invalid")
    os.replace(tmp, _INJECTOR_CACHE)
    return _INJECTOR_CACHE
