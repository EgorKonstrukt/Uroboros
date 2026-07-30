import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


SERVER_DIR = Path.home() / ".yamcl" / "server"
CONFIG_FILE = SERVER_DIR / "config.json"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 25581
    db_path: str = ""
    admin_password: str = "blabla"
    log_level: str = "info"
    curseforge_api_key: str = ""

    def save(self):
        SERVER_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls):
        inst = cls()
        if not CONFIG_FILE.exists():
            inst.save()
            return inst

        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)

        for k, v in raw.items():
            if hasattr(inst, k):
                setattr(inst, k, v)

        if not inst.db_path:
            inst.db_path = str(SERVER_DIR / "auth.db")

        return inst