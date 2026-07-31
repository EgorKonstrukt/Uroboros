import os
import sys
from pathlib import Path


def get_launcher_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "UroborosLauncher"


def get_projects_dir() -> Path:
    return get_launcher_dir() / "projects"


def get_project_dir(project_id: str) -> Path:
    return get_projects_dir() / project_id


def get_modpack_dir(project_id: str, modpack_id: str) -> Path:
    return get_project_dir(project_id) / "modpacks" / modpack_id


def get_work_dir() -> Path:
    return get_launcher_dir() / "work"


def get_versions_dir() -> Path:
    return get_work_dir() / "versions"


def get_assets_dir() -> Path:
    return get_work_dir() / "assets"


def get_libraries_dir() -> Path:
    return get_work_dir() / "libraries"


def get_java_dir() -> Path:
    return get_work_dir() / "runtime"


def get_log_config_dir() -> Path:
    return get_work_dir() / "log_configs"


def get_log_config_path(version_id: str) -> Path:
    return get_log_config_dir() / f"{version_id}.xml"


def get_logs_dir() -> Path:
    return get_launcher_dir() / "logs"


def ensure_dirs():
    for d in [get_launcher_dir(), get_work_dir(), get_versions_dir(),
              get_assets_dir(), get_libraries_dir(), get_java_dir(),
              get_logs_dir(), get_projects_dir(), get_log_config_dir()]:
        d.mkdir(parents=True, exist_ok=True)
