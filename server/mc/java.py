import os
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class JavaRuntime:
    path: str
    version: str
    major_version: int
    vendor: str
    arch: str
    source: str = ""


_JAVA_CACHE: List[JavaRuntime] = []


def get_cached() -> List[JavaRuntime]:
    return _JAVA_CACHE


def scan_java() -> List[JavaRuntime]:
    global _JAVA_CACHE
    found: dict[str, JavaRuntime] = {}

    for path in _find_candidates():
        if path in found:
            continue
        jr = _probe_java(path)
        if jr:
            found[jr.path] = jr

    _JAVA_CACHE = sorted(found.values(), key=lambda r: r.major_version, reverse=True)
    return _JAVA_CACHE


def _probe_java(path: str) -> Optional[JavaRuntime]:
    try:
        r = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = r.stderr + r.stdout

        m = re.search(r'version\s+"([^"]+)"', output)
        if not m:
            return None
        version = m.group(1)

        major_match = re.match(r"(\d+)", version)
        if not major_match:
            return None
        major = int(major_match.group(1))
        if major == 1:
            m2 = re.match(r"1\.(\d+)", version)
            if m2:
                major = int(m2.group(1))

        vendor = _detect_vendor(output)
        arch = "64-bit" if re.search(r"64[-\s]?[Bb]it|amd64|x86_64", output) else "32-bit"
        source = ""

        return JavaRuntime(
            path=str(Path(path).resolve()),
            version=version,
            major_version=major,
            vendor=vendor,
            arch=arch,
            source=source,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _detect_vendor(output: str) -> str:
    if re.search(r"Temurin|Eclipse Adoptium|AdoptOpenJDK", output):
        return "Adoptium"
    if "Java(TM)" in output or ("Oracle" in output and "OpenJDK" not in output):
        return "Oracle JDK"
    if "OpenJDK" in output:
        return "OpenJDK"
    if "Amazon" in output or "Corretto" in output:
        return "Amazon Corretto"
    if "Microsoft" in output:
        return "Microsoft"
    if "GraalVM" in output:
        return "GraalVM"
    if "IBM" in output:
        return "IBM"
    if "BellSoft" in output or "Liberica" in output:
        return "Liberica"
    if "Zulu" in output or "Azul" in output:
        return "Azul Zulu"
    if "SAP" in output:
        return "SAP"
    if "Red Hat" in output:
        return "Red Hat"
    return "Unknown"


def _find_candidates() -> List[str]:
    seen: set[str] = set()
    candidates: List[str] = []

    def add(p: str):
        if p and p not in seen:
            seen.add(p)
            candidates.append(p)

    for exe in ("java.exe", "java"):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d.strip():
                continue
            p = Path(d.strip()) / exe
            if p.exists():
                add(str(p.resolve()))

    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        for exe in ("java.exe", "java"):
            p = Path(java_home) / "bin" / exe
            if p.exists():
                add(str(p.resolve()))

    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        ):
            base_p = Path(base)
            if not base_p.exists():
                continue
            for vendor_dir in [
                "Eclipse Adoptium",
                "Adoptium",
                "Java",
                "Amazon Corretto",
                "Microsoft JDK",
                "BellSoft",
                "LibericaJDK",
                "Zulu",
                "GraalVM",
            ]:
                vdir = base_p / vendor_dir
                if vdir.exists():
                    for sub in sorted(vdir.iterdir()):
                        jp = sub / "bin" / "java.exe"
                        if jp.exists():
                            add(str(jp.resolve()))

        try:
            import winreg

            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for subkey in (
                    r"SOFTWARE\JavaSoft\Java Development Kit",
                    r"SOFTWARE\JavaSoft\Java Runtime Environment",
                    r"SOFTWARE\Adoptium\JDK",
                    r"SOFTWARE\Eclipse Foundation\JDK",
                ):
                    try:
                        with winreg.OpenKey(root, subkey) as k:
                            try:
                                cv = winreg.QueryValueEx(k, "CurrentVersion")[0]
                                with winreg.OpenKey(k, cv) as vk:
                                    jh = winreg.QueryValueEx(vk, "JavaHome")[0]
                                    p = Path(jh) / "bin" / "java.exe"
                                    if p.exists():
                                        add(str(p.resolve()))
                            except OSError:
                                pass
                            i = 0
                            while True:
                                try:
                                    sk_name = winreg.EnumKey(k, i)
                                    with winreg.OpenKey(k, sk_name) as sk:
                                        jh = winreg.QueryValueEx(sk, "JavaHome")[0]
                                        p = Path(jh) / "bin" / "java.exe"
                                        if p.exists():
                                            add(str(p.resolve()))
                                    i += 1
                                except OSError:
                                    break
                    except OSError:
                        continue
        except ImportError:
            pass

    return candidates


def resolve_java_path(desired: str, detected: Optional[List[JavaRuntime]] = None) -> str:
    if not detected:
        detected = _JAVA_CACHE
    for jr in detected:
        if jr.path == desired or jr.version == desired or str(jr.major_version) == desired:
            return jr.path
    return desired
