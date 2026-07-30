import json
import hashlib
from pathlib import Path
from typing import Callable, Optional

import requests

from launcher.utils.storage import get_assets_dir


OBJECTS_DIR = "objects"


class AssetManager:
    def __init__(self):
        self.assets_dir = get_assets_dir()

    def get_index(self, asset_version: str) -> Optional[dict]:
        idx_path = self.assets_dir / "indexes" / f"{asset_version}.json"
        if idx_path.exists():
            with open(idx_path, "r") as f:
                return json.load(f)
        return None

    def get_objects(self, asset_version: str) -> dict:
        index = self.get_index(asset_version)
        if index:
            return index.get("objects", {})
        return {}

    def get_asset_path(self, asset_hash: str) -> Path:
        return self.assets_dir / OBJECTS_DIR / asset_hash[:2] / asset_hash

    def is_asset_downloaded(self, asset_hash: str) -> bool:
        return self.get_asset_path(asset_hash).exists()

    def verify_asset(self, asset_path: Path, expected_hash: str) -> bool:
        if not asset_path.exists():
            return False
        with open(asset_path, "rb") as f:
            actual = hashlib.sha1(f.read()).hexdigest()
        return actual == expected_hash

    def download_asset(self, obj_name: str, obj_info: dict, progress_callback: Callable = None) -> bool:
        obj_hash = obj_info.get("hash", "")
        if not obj_hash:
            return False
        dest = self.get_asset_path(obj_hash)
        if dest.exists() and self.verify_asset(dest, obj_hash):
            return True
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://resources.download.minecraft.net/{obj_hash[:2]}/{obj_hash}"
        try:
            resp = requests.get(url, timeout=30, stream=True)
            if resp.status_code != 200:
                url = f"https://resources.download.minecraft.net/{obj_hash[:2]}/{obj_hash}"
                resp = requests.get(url, timeout=30, stream=True)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                if progress_callback:
                    progress_callback(obj_name)
                return True
        except requests.RequestException:
            pass
        return False

    def download_assets(self, asset_version: str, progress_callback: Callable = None) -> int:
        objects = self.get_objects(asset_version)
        downloaded = 0
        total = len(objects)
        for i, (name, info) in enumerate(objects.items()):
            if self.download_asset(name, info):
                downloaded += 1
            if progress_callback:
                progress_callback(int((i + 1) / total * 100) if total > 0 else 100)
        return downloaded
