import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

import requests

from launcher.utils.storage import get_versions_dir, get_assets_dir, get_libraries_dir, get_log_config_path
from launcher.utils.http import get_session
from launcher.utils.progress import FileProgress, ParallelProgress, CancelledError
from launcher.game.libraries_matcher import LibrariesMatcher, get_native_classifier_key


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

    @staticmethod
    def get_meta_path(version_id: str) -> Path:
        return get_versions_dir() / version_id / f"{version_id}.json"

    @staticmethod
    def get_jar_path(version_id: str) -> Path:
        return get_versions_dir() / version_id / f"{version_id}.jar"

    def _load_local_meta(self, version_id: str) -> Optional[dict]:
        path = self.get_meta_path(version_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def _fetch_remote_meta(self, version_id: str) -> dict:
        versions = self.get_versions()
        url = next((v.url for v in versions if v.id == version_id), "")
        if not url:
            raise ValueError(f"Version {version_id} not found")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _merge_inheritance(self, data: dict) -> dict:
        merged = dict(data)
        parent_id = data.get("inheritsFrom", "")
        seen = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = self._load_local_meta(parent_id)
            if not parent:
                try:
                    parent = self._fetch_remote_meta(parent_id)
                    path = self.get_meta_path(parent_id)
                    if not path.exists():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(parent, indent=2), encoding="utf-8")
                except requests.RequestException:
                    parent = None
            if not parent:
                break
            merged = {
                **parent,
                **merged,
                "libraries": parent.get("libraries", []) + merged.get("libraries", []),
            }
            parent_id = parent.get("inheritsFrom", "")
        return merged

    def install_loader(self, mc_version: str, loader: str, loader_version: str = "") -> str:
        loader = (loader or "").strip().lower()
        if loader not in ("fabric", "quilt"):
            return mc_version
        try:
            base = (
                "https://meta.fabricmc.net/v2/versions/loader"
                if loader == "fabric"
                else "https://meta.quiltmc.org/v3/versions/loader"
            )
            lv = loader_version
            if not lv:
                resp = requests.get(f"{base}/{mc_version}", timeout=30)
                resp.raise_for_status()
                items = resp.json()
                if not items:
                    return mc_version
                lv = items[0]["loader"]["version"]
            profile_url = f"{base}/{mc_version}/{lv}/profile/json"
            resp = requests.get(profile_url, timeout=30)
            resp.raise_for_status()
            profile = resp.json()
            vid = profile.get("id") or f"{mc_version}-{loader}-{lv}"
            profile["id"] = vid
            path = self.get_meta_path(vid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
            return vid
        except requests.RequestException:
            return mc_version

    @staticmethod
    def _meta_from_dict(version_id: str, data: dict) -> VersionMeta:
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

    def get_version_meta(self, version_id: str) -> VersionMeta:
        data = self._load_local_meta(version_id)
        if not data:
            data = self._fetch_remote_meta(version_id)
        data = self._merge_inheritance(data)
        return self._meta_from_dict(version_id, data)

    def get_local_versions(self) -> list[str]:
        vdir = get_versions_dir()
        if not vdir.exists():
            return []
        return [d.name for d in vdir.iterdir() if d.is_dir()]

    def is_version_installed(self, version_id: str) -> bool:
        return self.get_jar_path(version_id).exists() and self.get_meta_path(version_id).exists()

    def download_version(self, version_id: str, progress_callback=None, should_cancel=None) -> bool:
        meta = self.get_version_meta(version_id)
        vdir = get_versions_dir() / version_id
        vdir.mkdir(parents=True, exist_ok=True)
        session = get_session()

        json_path = self.get_meta_path(version_id)
        if not json_path.exists():
            data = self._fetch_remote_meta(version_id)
            json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        client_dl = meta.downloads.get("client", {})
        client_url = client_dl.get("url", "")
        if client_url:
            jar_path = self.get_jar_path(version_id)
            if not jar_path.exists():
                if should_cancel and should_cancel():
                    raise CancelledError()
                progress = FileProgress(progress_callback, "client", f"{version_id}.jar")
                tmp = jar_path.with_name(jar_path.name + ".part")
                try:
                    resp = session.get(client_url, timeout=120, stream=True)
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=262144):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress.update(downloaded, total)
                            if should_cancel and should_cancel():
                                raise CancelledError()
                    tmp.replace(jar_path)
                    progress.done()
                finally:
                    if tmp.exists():
                        try:
                            tmp.unlink()
                        except OSError:
                            pass

        self._download_asset_index(meta, progress_callback, should_cancel)
        self._download_libraries(meta, progress_callback, should_cancel)
        self._download_logging_config(meta, progress_callback, should_cancel)
        return True

    def _download_asset_index(self, meta: VersionMeta, progress_callback=None, should_cancel=None):
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
                if should_cancel and should_cancel():
                    raise CancelledError()
                progress = FileProgress(progress_callback, "assets_index", f"{meta.assets}.json",
                                        files_done=1, files_total=1)
                resp = get_session().get(url, timeout=30)
                if resp.status_code == 200:
                    idx_path.write_text(resp.text)
                progress.done()

    def _download_logging_config(self, meta: VersionMeta, progress_callback=None, should_cancel=None):
        client = meta.logging.get("client", {}) if meta.logging else {}
        url = client.get("file", {}).get("url", "")
        if not url:
            return
        dest = get_log_config_path(meta.id)
        if dest.exists():
            return
        if should_cancel and should_cancel():
            raise CancelledError()
        dest.parent.mkdir(parents=True, exist_ok=True)
        progress = FileProgress(progress_callback, "logging", dest.name, files_done=1, files_total=1)
        try:
            resp = get_session().get(url, timeout=30)
            if resp.status_code == 200:
                dest.write_text(resp.text)
        except requests.RequestException:
            pass
        progress.done()

    def _download_libraries(self, meta: VersionMeta, progress_callback=None, should_cancel=None):
        libs_dir = get_libraries_dir()
        targets = []
        for lib in meta.libraries:
            if not LibrariesMatcher.match_library(lib):
                continue
            dl = lib.get("downloads", {})
            artifact = dl.get("artifact", {})
            lib_url = artifact.get("url", "")
            lib_path_str = artifact.get("path", "")
            if not lib_url or not lib_path_str:
                classifiers = dl.get("classifiers", {})
                key = get_native_classifier_key(classifiers)
                if key:
                    native_artifact = classifiers[key]
                    lib_url = native_artifact.get("url", "")
                    lib_path_str = native_artifact.get("path", "")
            if lib_url and lib_path_str:
                targets.append((lib_url, lib_path_str))
        total = len(targets)
        if total == 0:
            return
        progress = ParallelProgress(progress_callback, "library", total)
        session = get_session()
        workers = max(1, min(8, total))

        def work(item):
            if should_cancel and should_cancel():
                raise CancelledError()
            lib_url, lib_path_str = item
            lib_path = libs_dir / lib_path_str
            if lib_path.exists():
                progress.finish(lib_path.name)
                return
            lib_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = lib_path.with_name(lib_path.name + ".part")
            progress.start_file(lib_path.name)
            try:
                resp = session.get(lib_url, timeout=60, stream=True)
                if resp.status_code == 200:
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=262144):
                            if not chunk:
                                continue
                            f.write(chunk)
                            progress.tick(lib_path.name, len(chunk))
                            if should_cancel and should_cancel():
                                raise CancelledError()
                    tmp.replace(lib_path)
            except requests.RequestException:
                pass
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                progress.finish(lib_path.name)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(work, t) for t in targets]
            for f in futures:
                f.result()
