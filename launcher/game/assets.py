import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import requests

from launcher.utils.storage import get_assets_dir
from launcher.utils.http import get_session
from launcher.utils.progress import ParallelProgress, CancelledError

CHUNK = 262144
WORKERS = 16

OBJECTS_DIR = "objects"


class AssetManager:
    def __init__(self):
        self.assets_dir = get_assets_dir()
        self.session = get_session()

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

    def _download_one(self, obj_name: str, obj_info: dict, progress: ParallelProgress,
                      should_cancel: Callable = None) -> bool:
        obj_hash = obj_info.get("hash", "")
        if not obj_hash:
            return False
        dest = self.get_asset_path(obj_hash)
        if dest.exists() and self.verify_asset(dest, obj_hash):
            progress.finish(obj_name)
            return True
        if should_cancel and should_cancel():
            raise CancelledError()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        url = f"https://resources.download.minecraft.net/{obj_hash[:2]}/{obj_hash}"
        try:
            progress.start_file(obj_name)
            resp = self.session.get(url, timeout=60, stream=True)
            if resp.status_code != 200:
                resp.close()
                resp = self.session.get(url, timeout=60, stream=True)
            if resp.status_code == 200:
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=CHUNK):
                        if not chunk:
                            continue
                        f.write(chunk)
                        progress.tick(obj_name, len(chunk))
                        if should_cancel and should_cancel():
                            raise CancelledError()
                tmp.replace(dest)
                progress.finish(obj_name)
                return True
        except requests.RequestException:
            pass
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            progress.finish(obj_name)
        return False

    def download_assets(self, asset_version: str, progress_callback: Callable = None,
                        should_cancel: Callable = None) -> int:
        objects = self.get_objects(asset_version)
        items = list(objects.items())
        total = len(items)
        if total == 0:
            return 0
        progress = ParallelProgress(progress_callback, "asset", total)
        workers = max(1, min(WORKERS, total))

        def work(pair):
            name, info = pair
            return self._download_one(name, info, progress, should_cancel)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(work, items))
        return sum(1 for r in results if r)
