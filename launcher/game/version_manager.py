import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

import requests

from launcher.utils.storage import (
    get_versions_dir, get_assets_dir, get_libraries_dir, get_log_config_path, get_work_dir,
)
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
                "libraries": self._dedup_libraries(
                    parent.get("libraries", []) + merged.get("libraries", [])
                ),
                "arguments": self._merge_arguments(
                    parent.get("arguments"), merged.get("arguments")
                ),
            }
            parent_id = parent.get("inheritsFrom", "")
        return merged

    @staticmethod
    def _dedup_libraries(libraries: list) -> list:
        seen = set()
        result = []
        for lib in libraries:
            dl = lib.get("downloads", {}) or {}
            artifact = dl.get("artifact") or {}
            key = artifact.get("path", "")
            if not key:
                for v in (dl.get("classifiers") or {}).values():
                    if v.get("path"):
                        key = v["path"]
                        break
            if not key:
                key = lib.get("name", "")
            if key in seen:
                continue
            seen.add(key)
            result.append(lib)
        return result

    @staticmethod
    def _merge_arguments(parent: dict, child: dict) -> dict:
        parent = parent or {}
        child = child or {}
        merged = {}
        for section in ("game", "jvm"):
            merged[section] = list(parent.get(section, [])) + list(child.get(section, []))
        return merged

    def install_loader(self, mc_version: str, loader: str, loader_version: str = "",
                       progress_callback=None, should_cancel=None) -> str:
        loader = (loader or "").strip().lower()
        if loader in ("fabric", "quilt"):
            return self._install_fabric_like(mc_version, loader, loader_version)
        if loader == "neoforge":
            return self._install_neoforge(mc_version, loader_version, progress_callback, should_cancel)
        return mc_version

    def _install_fabric_like(self, mc_version: str, loader: str, loader_version: str = "") -> str:
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

    def _install_neoforge(self, mc_version: str, loader_version: str = "",
                          progress_callback=None, should_cancel=None) -> str:
        import shutil
        import tempfile
        import zipfile
        tmp_dir = None
        try:
            if not loader_version:
                resp = requests.get(
                    "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml",
                    timeout=30,
                )
                resp.raise_for_status()
                loader_version = self._latest_neoforge_version(resp.text)
            installer_url = (
                f"https://maven.neoforged.net/releases/net/neoforged/neoforge/"
                f"{loader_version}/neoforge-{loader_version}-installer.jar"
            )
            resp = requests.get(installer_url, timeout=60)
            resp.raise_for_status()
            tmp_dir = Path(tempfile.mkdtemp(prefix="neoforge_"))
            installer = tmp_dir / "installer.jar"
            installer.write_bytes(resp.content)
            with zipfile.ZipFile(installer) as zf:
                names = zf.namelist()
                entry = next((n for n in names if n.endswith("version.json")), None)
                if not entry:
                    return mc_version
                profile = json.loads(zf.read(entry))
                total_steps = 9
                proc_entry = next((n for n in names if n.endswith("install_profile.json")), None)
                if proc_entry:
                    try:
                        ip = json.loads(zf.read(proc_entry))
                        if isinstance(ip.get("processors"), list) and ip["processors"]:
                            total_steps = len(ip["processors"])
                    except (json.JSONDecodeError, OSError):
                        pass
            vid = profile.get("id") or f"{mc_version}-neoforge-{loader_version}"
            profile["id"] = vid
            path = self.get_meta_path(vid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
            if not self._neoforge_patch_ready(loader_version):
                self._run_neoforge_installer(
                    installer, profile, total_steps, progress_callback, should_cancel
                )
            return vid
        except CancelledError:
            raise
        except (requests.RequestException, OSError, RuntimeError):
            return mc_version
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _neoforge_patch_ready(loader_version: str) -> bool:
        libs = get_libraries_dir()
        nf_dir = libs / "net" / "neoforged" / "neoforge" / loader_version
        if not ((nf_dir / f"neoforge-{loader_version}-universal.jar").exists()
                and (nf_dir / f"neoforge-{loader_version}-client.jar").exists()):
            return False
        mc_root = libs / "net" / "minecraft" / "client"
        if not mc_root.is_dir():
            return False
        return any(
            (d / f"client-{d.name}-srg.jar").exists() and (d / f"client-{d.name}-extra.jar").exists()
            for d in mc_root.iterdir() if d.is_dir()
        )

    def _run_neoforge_installer(self, installer_jar: Path, profile: dict, total_steps: int,
                                progress_callback=None, should_cancel=None):
        import subprocess
        from launcher.game.java_manager import JavaManager
        work_dir = get_work_dir()
        work_dir.mkdir(parents=True, exist_ok=True)
        profiles = work_dir / "launcher_profiles.json"
        if not profiles.exists():
            profiles.write_text(json.dumps({
                "profiles": {},
                "settings": {},
                "version": 3,
                "selectedProfile": "(Default)",
                "clientToken": "",
                "launcherVersion": {"name": "", "format": 0},
            }, indent=2), encoding="utf-8")
        required = int(profile.get("javaVersion", {}).get("majorVersion") or 0) or 17
        manager = JavaManager()
        java = manager.find_java(required) or manager.find_java(0)
        if not java:
            raise RuntimeError("Java not found to run the NeoForge installer")
        if should_cancel and should_cancel():
            raise CancelledError()
        if progress_callback:
            progress_callback({
                "phase": "neoforge", "file": "processing", "current": 0, "total": total_steps,
                "speed": 0, "files_done": 0, "files_total": total_steps,
            })
        cmd = [java, "-jar", str(installer_jar), "--installClient", str(work_dir)]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        processed = 0
        try:
            for line in proc.stdout:
                if "Processor:" in line and processed < total_steps:
                    processed += 1
                    if progress_callback:
                        progress_callback({
                            "phase": "neoforge", "file": "processing", "current": processed,
                            "total": total_steps, "speed": 0,
                            "files_done": processed, "files_total": total_steps,
                        })
                if should_cancel and should_cancel():
                    proc.kill()
                    raise CancelledError()
        finally:
            proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"NeoForge installer failed with exit code {proc.returncode}")
        if progress_callback:
            progress_callback({
                "phase": "neoforge", "file": "processing", "current": total_steps,
                "total": total_steps, "speed": 0,
                "files_done": total_steps, "files_total": total_steps,
            })

    @staticmethod
    def _latest_neoforge_version(metadata_xml: str) -> str:
        import re
        versions = re.findall(r"<version>([^<]+)</version>", metadata_xml or "")
        if not versions:
            return ""
        return versions[-1]

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
        if not self.get_meta_path(version_id).exists():
            return False
        meta = self.get_version_meta(version_id)
        client_url = (meta.downloads.get("client") or {}).get("url", "")
        if not client_url:
            return True
        return self.get_jar_path(version_id).exists()

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
