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

    def find_java(self, version: int = 17) -> Optional[str]:
        system_java = shutil.which("java")
        if system_java and self.matches_version(system_java, version):
            return system_java
        java_dir = get_java_dir()
        if java_dir.exists():
            if sys.platform == "win32":
                javas = list(java_dir.rglob("javaw.exe")) + list(java_dir.rglob("java.exe"))
            else:
                javas = list(java_dir.rglob("java"))
            for j in javas:
                if j.is_file() and self.matches_version(str(j), version):
                    return str(j)
        return None

    @staticmethod
    def matches_version(java_path: str, version: int) -> bool:
        try:
            out = subprocess.check_output(
                [java_path, "-version"], stderr=subprocess.STDOUT, timeout=10
            ).decode(errors="replace")
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, OSError):
            return False
        if not version:
            return True
        if f'version "1.{version}' in out:
            return True
        if re.search(rf'version "{version}(\.|_)', out):
            return True
        return False

    def download_java(self, java_version: int = 17, progress_callback=None, should_cancel=None) -> Optional[str]:
        if should_cancel and should_cancel():
            raise CancelledError()
        assets = self.get_available_versions(java_version)
        if not assets:
            return None

        os_name = self.get_os()
        arch = self.get_arch()

        asset = None
        for a in assets:
            bp = a.get("binary", {}).get("package", {})
            if bp.get("os", "").lower() == os_name and bp.get("architecture", "").lower() == arch:
                asset = a
                break
        if not asset:
            for a in assets:
                bp = a.get("binary", {}).get("package", {})
                if bp.get("os", "").lower() == os_name:
                    asset = a
                    break
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
