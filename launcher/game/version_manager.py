import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

import requests

from launcher.utils.storage import get_versions_dir, get_libraries_dir, get_assets_dir


MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
ASSETS_INDEX_URL = "https://launchermeta.mojang.com/v1/packages/{sha1}/{}"


class VersionType(Enum):
    RELEASE = "release"
    SNAPSHOT = "snapshot"
    OLD_BETA = "old_beta"
    OLD_ALPHA = "old_alpha"


@dataclass
class VersionInfo:
    id: str
    type: str
    url: str
    time: str
    release_time: str
    sha1: str = ""
    compliance_level: int = 0


@dataclass
class VersionMeta:
    id: str
    type: str
    minecraft_arguments: str = ""
    main_class: str = ""
    assets: str = ""
    asset_index: dict = field(default_factory=dict)
    libraries: list = field(default_factory=list)
    downloads: dict = field(default_factory=dict)
    java_version: dict = field(default_factory=dict)
    logging: dict = field(default_factory=dict)
    inherits_from: str = ""
    arguments: dict = field(default_factory=dict)


class VersionManager:
    _manifest: Optional[dict] = None
    _manifest_time: float = 0
    _manifest_ttl: float = 300

    def fetch_manifest(self) -> dict:
        import time
        now = time.time()
        if self._manifest and (now - self._manifest_time) < self._manifest_ttl:
            return self._manifest
        resp = requests.get(MANIFEST_URL, timeout=30)
        resp.raise_for_status()
        self._manifest = resp.json()
        self._manifest_time = now
        return self._manifest

    def get_versions(self) -> list[VersionInfo]:
        manifest = self.fetch_manifest()
        return [
            VersionInfo(
                id=v["id"],
                type=v["type"],
                url=v["url"],
                time=v.get("time", ""),
                release_time=v.get("releaseTime", ""),
                sha1=v.get("sha1", ""),
            )
            for v in manifest.get("versions", [])
        ]

    def get_latest_release(self) -> str:
        manifest = self.fetch_manifest()
        return manifest.get("latest", {}).get("release", "")

    def get_latest_snapshot(self) -> str:
        manifest = self.fetch_manifest()
        return manifest.get("latest", {}).get("snapshot", "")

    def get_version_meta(self, version_id: str) -> VersionMeta:
        versions = self.get_versions()
        url = ""
        for v in versions:
            if v.id == version_id:
                url = v.url
                break
        if not url:
            raise ValueError(f"Version {version_id} not found")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return VersionMeta(
            id=data.get("id", version_id),
            type=data.get("type", ""),
            minecraft_arguments=data.get("minecraftArguments", ""),
            main_class=data.get("mainClass", ""),
            assets=data.get("assets", ""),
            asset_index=data.get("assetIndex", {}),
            libraries=data.get("libraries", []),
            downloads=data.get("downloads", {}),
            java_version=data.get("javaVersion", {}),
            logging=data.get("logging", {}),
            inherits_from=data.get("inheritsFrom", ""),
            arguments=data.get("arguments", {}),
        )

    def get_local_versions(self) -> list[str]:
        vdir = get_versions_dir()
        if not vdir.exists():
            return []
        return [d.name for d in vdir.iterdir() if d.is_dir()]

    def is_version_installed(self, version_id: str) -> bool:
        jar_path = get_versions_dir() / version_id / f"{version_id}.jar"
        json_path = get_versions_dir() / version_id / f"{version_id}.json"
        return jar_path.exists() and json_path.exists()

    def download_version(self, version_id: str, progress_callback=None) -> bool:
        meta = self.get_version_meta(version_id)
        vdir = get_versions_dir() / version_id
        vdir.mkdir(parents=True, exist_ok=True)

        json_path = vdir / f"{version_id}.json"
        if not json_path.exists():
            versions = self.get_versions()
            for v in versions:
                if v.id == version_id:
                    meta_resp = requests.get(v.url, timeout=30)
                    meta_resp.raise_for_status()
                    (vdir / f"{version_id}.json").write_text(json.dumps(meta_resp.json(), indent=2))
                    break

        client_dl = meta.downloads.get("client", {})
        client_url = client_dl.get("url", "")
        if client_url:
            jar_path = vdir / f"{version_id}.jar"
            if not jar_path.exists():
                resp = requests.get(client_url, timeout=120, stream=True)
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(jar_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total:
                                progress_callback(int(downloaded / total * 100))
                if progress_callback:
                    progress_callback(100)

        self._download_asset_index(meta)
        self._download_libraries(meta, progress_callback)
        return True

    def _download_asset_index(self, meta: VersionMeta):
        asset_index = meta.asset_index
        if not asset_index:
            return
        url = asset_index.get("url", "")
        sha1 = asset_index.get("sha1", "")
        if not url:
            url = ASSETS_INDEX_URL.format(sha1, meta.assets)
        if url:
            idx_dir = get_assets_dir() / "indexes"
            idx_dir.mkdir(parents=True, exist_ok=True)
            idx_path = idx_dir / f"{meta.assets}.json"
            if not idx_path.exists():
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    idx_path.write_text(resp.text)

    def _download_libraries(self, meta: VersionMeta, progress_callback=None):
        libs_dir = get_libraries_dir()
        for lib in meta.libraries:
            dl = lib.get("downloads", {})
            artifact = dl.get("artifact", {})
            lib_url = artifact.get("url", "")
            lib_path_str = artifact.get("path", "")
            if not lib_url or not lib_path_str:
                natives = dl.get("classifiers", {})
                import platform
                import sys
                os_name = sys.platform
                if os_name == "win32":
                    native_key = f"natives-windows"
                elif os_name == "darwin":
                    native_key = "natives-osx"
                else:
                    native_key = "natives-linux"
                arch_key = f"natives-{os_name}-{platform.machine().lower()}" if os_name == "win32" else native_key
                for key, native_artifact in natives.items():
                    if native_key in key or arch_key in key:
                        lib_url = native_artifact.get("url", "")
                        lib_path_str = native_artifact.get("path", "")
                        break
            if lib_url and lib_path_str:
                lib_path = libs_dir / lib_path_str
                if not lib_path.exists():
                    lib_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        resp = requests.get(lib_url, timeout=60, stream=True)
                        if resp.status_code == 200:
                            with open(lib_path, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                    except requests.RequestException:
                        pass
