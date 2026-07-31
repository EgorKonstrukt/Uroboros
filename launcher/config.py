import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional

from launcher.utils.storage import get_launcher_dir, set_work_dir


CONFIG_FILE = get_launcher_dir() / "config.json"
PROJECTS_CACHE = get_launcher_dir() / "projects_cache.json"


@dataclass
class ModpackInfo:
    id: str = ""
    name: str = ""
    description: str = ""
    version: str = "1.0"
    mc_version: str = ""
    loader: str = ""
    loader_version: str = ""
    min_memory: int = 1024
    max_memory: int = 2048
    java_args: str = ""
    java_path: str = ""
    changelog: str = ""
    file_count: int = 0


@dataclass
class ProjectInfo:
    id: str = ""
    name: str = ""
    description: str = ""
    icon: str = ""
    logo_url: str = ""
    background_url: str = ""
    primary_color: str = "#6c63ff"
    accent_color: str = ""
    window_title: str = ""
    brand_name: str = ""
    modpacks: list = None

    def __post_init__(self):
        if self.modpacks is None:
            self.modpacks = []


@dataclass
class LauncherConfig:
    api_url: str = "http://127.0.0.1:25581"
    project_id: str = ""
    java_path: str = "java"
    java_args: str = "-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC"
    min_memory: int = 1024
    max_memory: int = 2048
    access_token: str = ""
    client_token: str = ""
    account_uuid: str = ""
    account_name: str = ""
    account_properties: list = field(default_factory=list)
    work_dir: str = ""
    verify_ssl: bool = True
    window_width: int = 1100
    window_height: int = 700
    keep_launcher_open: bool = True

    def save(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            inst = cls(**valid)
        else:
            inst = cls()
            inst.save()
        set_work_dir(inst.work_dir)
        return inst


def cache_projects(data: dict):
    PROJECTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROJECTS_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_cached_projects() -> Optional[dict]:
    if PROJECTS_CACHE.exists():
        with open(PROJECTS_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
