import json
import secrets
from pathlib import Path
from dataclasses import dataclass, asdict

from server.auth.crypto import hash_password


SERVER_DIR = Path.home() / ".yamcl" / "server"
CONFIG_FILE = SERVER_DIR / "config.json"

_WEAK_PASSWORDS = {"", "blabla", "admin", "password"}


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 25581
    db_path: str = ""
    admin_password: str = ""
    log_level: str = "info"
    curseforge_api_key: str = ""
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    stats_refresh_seconds: int = 2
    trust_proxy_headers: bool = False

    def save(self):
        SERVER_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls):
        inst = cls()
        if not CONFIG_FILE.exists():
            inst._ensure_secure_password()
            inst.save()
            return inst

        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)

        for k, v in raw.items():
            if hasattr(inst, k):
                setattr(inst, k, v)

        if not inst.db_path:
            inst.db_path = str(SERVER_DIR / "auth.db")

        if inst.admin_password in _WEAK_PASSWORDS:
            inst._ensure_secure_password()
            inst.save()

        if inst.admin_password and not inst.admin_password.startswith("scrypt$"):
            # Re-hash a password that was stored in plaintext before hashing was added
            inst.admin_password = hash_password(inst.admin_password)
            inst.save()

        return inst

    def _ensure_secure_password(self):
        generated = secrets.token_urlsafe(12)
        self.admin_password = hash_password(generated)
        print(f"[Uroboros] Generated admin panel password: {generated}")
        print(f"[Uroboros] Save it now — it will not be shown again.")
