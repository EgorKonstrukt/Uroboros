import json
import hashlib
from pathlib import Path

import requests


INJECTOR_META_URL = "https://authlib-injector.yushi.moe/artifact/latest.json"


class InjectorManager:
    def __init__(self, save_dir: Path):
        self.save_dir = save_dir
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def get_latest_info(self) -> dict:
        resp = requests.get(INJECTOR_META_URL, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def download(self, filename: str = "authlib-injector.jar") -> Path:
        info = self.get_latest_info()
        download_url = info.get("download_url", "")
        checksums = info.get("checksums", {})

        if not download_url:
            raise ValueError("No download URL in metadata")

        jar_path = self.save_dir / filename

        resp = requests.get(download_url, timeout=120, stream=True)
        resp.raise_for_status()

        with open(jar_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        if checksums:
            sha256 = checksums.get("sha256", "")
            if sha256:
                actual = hashlib.sha256()
                with open(jar_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        actual.update(chunk)
                if actual.hexdigest() != sha256:
                    jar_path.unlink()
                    raise ValueError("SHA-256 checksum mismatch")
        return jar_path

    def is_downloaded(self, filename: str = "authlib-injector.jar") -> bool:
        return (self.save_dir / filename).exists()
