import json
from pathlib import Path

from sqlalchemy import select

from server.database import get_session
from server.models import InstanceModel, UserModel

WHITE_LIST_KEY = "white-list"


def _uuid_with_dashes(uid: str) -> str:
    uid = uid.replace("-", "")
    if len(uid) != 32:
        return uid
    return f"{uid[0:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"


def _set_server_property(server_dir: Path, key: str, value: str):
    server_dir.mkdir(parents=True, exist_ok=True)
    props_path = server_dir / "server.properties"
    lines = []
    if props_path.exists():
        lines = props_path.read_text(encoding="utf-8", errors="replace").splitlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            pair = stripped.split("=", 1)
            if pair[0].strip() == key:
                lines[i] = f"{key}={value}"
                found = True
                break
    if not found:
        lines.append(f"{key}={value}")
    props_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _load_whitelisted_users():
    async with get_session() as session:
        stmt = select(UserModel).order_by(UserModel.display_name)
        result = await session.execute(stmt)
        return result.scalars().all()


async def sync_instance_whitelist(inst: InstanceModel) -> dict:
    server_dir = Path(inst.server_dir)
    server_dir.mkdir(parents=True, exist_ok=True)

    if not inst.whitelist_enabled:
        _set_server_property(server_dir, WHITE_LIST_KEY, "false")
        return {"enabled": False, "count": 0}

    users = await _load_whitelisted_users()
    entries = [
        {"uuid": _uuid_with_dashes(u.uuid), "name": u.display_name}
        for u in users
        if u.uuid and u.display_name
    ]

    whitelist_path = server_dir / "whitelist.json"
    whitelist_path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _set_server_property(server_dir, WHITE_LIST_KEY, "true")

    return {"enabled": True, "count": len(entries)}


async def sync_all_whitelists() -> dict:
    from server.mc.registry import get_manager

    async with get_session() as session:
        stmt = select(InstanceModel).where(InstanceModel.whitelist_enabled == True)
        result = await session.execute(stmt)
        instances = result.scalars().all()
    results = {}
    for inst in instances:
        results[inst.id] = await sync_instance_whitelist(inst)
        mgr = await get_manager(inst.id)
        if mgr and mgr.is_running():
            mgr.send_command("whitelist reload")
    return results
