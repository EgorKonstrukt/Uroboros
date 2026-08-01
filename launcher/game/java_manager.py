import os
import re
import sys
import zipfile
import tarfile
import shutil
import subprocess
import platform as plat
from pathlib import Path
from typing import Optional

import requests

from launcher.utils.storage import get_java_dir
from launcher.utils.http import get_session
from launcher.utils.progress import FileProgress, CancelledError


ADOPTIUM_API = "https://api.adoptium.net/v3/assets/latest/{version}/hotspot"

INSTALLABLE_VERSIONS = [8, 11, 16, 17, 21, 25]


class JavaManager:
    @staticmethod
    def get_os() -> str:
        if sys.platform == "win32":
            return "windows"
        if sys.platform == "darwin":
            return "mac"
        return "linux"

    @staticmethod
    def get_arch() -> str:
        machine = plat.machine().lower()
        if machine in ("amd64", "x86_64"):
            return "x64"
        if machine in ("aarch64", "arm64"):
            return "arm64"
        return "x64"

    @staticmethod
    def get_java_major_version(java_path: str) -> int:
        try:
            out = subprocess.check_output(
                [java_path, "-version"], stderr=subprocess.STDOUT, timeout=10
            ).decode(errors="replace")
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, OSError):
            return 0
        m = re.search(r'version "([^"]+)"', out)
        if not m:
            return 0
        ver = m.group(1)
        if ver.startswith("1."):
            try:
                return int(ver.split(".")[1])
            except (ValueError, IndexError):
                return 0
        try:
            return int(ver.split(".")[0])
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def matches_version(java_path: str, version: int) -> bool:
        if not version:
            return True
        return JavaManager.get_java_major_version(java_path) == version

    @staticmethod
    def java_required_for_mc(mc_version: str) -> int:
        try:
            parts = re.findall(r"\d+", mc_version or "")
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            return 17
        if major > 1:
            return 21
        if major == 0:
            return 17
        if (minor, patch) >= (20, 5):
            return 21
        if (minor, patch) >= (18, 0):
            return 17
        if (minor, patch) >= (17, 0):
            return 16
        return 8

    def get_available_versions(self, java_version: int = 17) -> list:
        try:
            resp = requests.get(
                ADOPTIUM_API.format(version=java_version),
                headers={"Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return []

    @staticmethod
    def _system_java_dirs() -> list:
        dirs = []
        env_home = os.environ.get("JAVA_HOME")
        if env_home:
            dirs.append(Path(env_home))
        if sys.platform == "win32":
            for base in (
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
            ):
                if not base.exists():
                    continue
                for sub in ("Java", "Eclipse Adoptium", "Zulu", "Microsoft", "Temurin", "jdk"):
                    p = base / sub
                    if p.exists():
                        dirs.append(p)
        else:
            for p in (Path("/usr/lib/jvm"), Path("/usr/java"), Path("/opt/java")):
                if p.exists():
                    dirs.append(p)
        return dirs

    def _discover_java_candidates(self) -> list:
        found = []
        system_java = shutil.which("java")
        if system_java:
            found.append(Path(system_java))
        java_dir = get_java_dir()
        if java_dir.exists():
            found.append(java_dir)
        found.extend(self._system_java_dirs())

        by_dir = {}
        for base in found:
            if not base.exists():
                continue
            if base.is_file() and base.name in ("java", "java.exe", "javaw.exe"):
                cands = [base]
            elif sys.platform == "win32":
                cands = list(base.rglob("java.exe")) + list(base.rglob("javaw.exe"))
            else:
                cands = list(base.rglob("java"))
            for j in cands:
                j = Path(j)
                if not j.is_file():
                    continue
                dkey = os.path.normcase(str(j.parent))
                entry = by_dir.get(dkey)
                if entry is None or j.name == "java.exe":
                    by_dir[dkey] = j
        return list(by_dir.values())

    def find_java(self, version: int = 17) -> Optional[str]:
        version = version or 0
        javas = self._discover_java_candidates()
        exact = None
        for j in javas:
            v = self.get_java_major_version(str(j))
            if version == 0 or v == version:
                exact = j
                break
        if exact is None and version >= 16:
            for j in javas:
                if self.get_java_major_version(str(j)) >= version:
                    exact = j
                    break
        return str(exact) if exact else None

    def list_managed(self) -> list:
        return [e for e in self.list_all() if e["managed"]]

    def _is_managed(self, java_path) -> bool:
        try:
            p = Path(java_path).resolve()
            runtime = get_java_dir().resolve()
            return runtime in p.parents
        except OSError:
            return False

    def list_all(self) -> list:
        result = []
        seen = set()
        for j in self._discover_java_candidates():
            j = Path(j)
            key = os.path.normcase(str(j))
            if key in seen:
                continue
            seen.add(key)
            version = self.get_java_major_version(str(j))
            managed = self._is_managed(str(j))
            result.append({
                "version": version,
                "path": str(j),
                "managed": managed,
                "dir": str(get_java_dir() / f"jdk-{version}") if managed else "",
            })
        result.sort(key=lambda e: e["version"], reverse=True)
        return result

    def remove_managed(self, entry: dict) -> bool:
        d = Path(entry.get("dir", ""))
        if d.exists() and d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False

    def ensure_java(self, required: int = 0, progress_callback=None, should_cancel=None) -> Optional[str]:
        java = self.find_java(required) if required else self.find_java()
        if not java and required:
            java = self.download_java(required, progress_callback, should_cancel)
        elif not java:
            java = self.download_java(17, progress_callback, should_cancel)
        return java

    def _pick_asset(self, assets: list) -> Optional[dict]:
        os_name = self.get_os()
        arch = self.get_arch()
        for a in assets:
            b = a.get("binary", {})
            pkg = b.get("package", {})
            if not pkg.get("link"):
                continue
            if (b.get("os", "").lower() == os_name
                    and b.get("architecture", "").lower() == arch
                    and b.get("image_type", "").lower() == "jdk"):
                return a
        for a in assets:
            b = a.get("binary", {})
            pkg = b.get("package", {})
            if not pkg.get("link"):
                continue
            if b.get("os", "").lower() == os_name and b.get("architecture", "").lower() == arch:
                return a
        for a in assets:
            b = a.get("binary", {})
            pkg = b.get("package", {})
            if not pkg.get("link"):
                continue
            if b.get("os", "").lower() == os_name:
                return a
        return None

    def download_java(self, java_version: int = 17, progress_callback=None, should_cancel=None) -> Optional[str]:
        if should_cancel and should_cancel():
            raise CancelledError()
        assets = self.get_available_versions(java_version)
        if not assets:
            return None

        asset = self._pick_asset(assets)
        if not asset:
            return None

        pkg = asset.get("binary", {}).get("package", {})
        dl_url = pkg.get("link", "")
        if not dl_url:
            return None

        ext = ".zip" if sys.platform == "win32" else ".tar.gz"
        java_archive = get_java_dir() / f"java{java_version}{ext}"

        progress = FileProgress(progress_callback, "java", java_archive.name)
        tmp = java_archive.with_name(java_archive.name + ".part")
        try:
            resp = get_session().get(dl_url, timeout=300, stream=True)
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
            tmp.replace(java_archive)
            progress.done()
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

        if progress_callback:
            progress_callback({
                "phase": "java_extract", "file": "Extracting...",
                "current": 0, "total": 0, "speed": 0, "files_done": 0, "files_total": 0,
            })

        extract_dir = get_java_dir() / f"jdk-{java_version}"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        if sys.platform == "win32":
            with zipfile.ZipFile(java_archive, "r") as zf:
                zf.extractall(extract_dir)
        else:
            with tarfile.open(java_archive, "r:gz") as tf:
                tf.extractall(extract_dir)

        java_archive.unlink()

        if sys.platform == "win32":
            javas = list(extract_dir.rglob("javaw.exe")) + list(extract_dir.rglob("java.exe"))
        else:
            javas = list(extract_dir.rglob("java"))
        for j in javas:
            if j.is_file():
                if sys.platform != "win32":
                    j.chmod(j.stat().st_mode | 0o111)
                return str(j)
        return None
