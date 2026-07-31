import threading
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from server.database import get_session
from server.models import InstanceModel
from server.mc.config import instance_model_to_dict, dict_to_instance_model
from server.mc.manager import ServerManager


_manager_cache: dict[str, ServerManager] = {}
_lock = threading.Lock()


def _create_manager(inst: InstanceModel) -> ServerManager:
    from server.mc.auth_plugin import create_server_auth_plugin
    auth_plugin = create_server_auth_plugin(
        inst.auth_plugin,
        injector_filename=inst.injector_filename,
    )
    return ServerManager(inst, auth_plugin=auth_plugin)


def get_manager_sync(inst: InstanceModel) -> ServerManager:
    with _lock:
        if inst.id in _manager_cache:
            mgr = _manager_cache[inst.id]
            if mgr is not None:
                return mgr
        mgr = _create_manager(inst)
        _manager_cache[inst.id] = mgr
        return mgr


async def get_manager(instance_id: str) -> Optional[ServerManager]:
    with _lock:
        if instance_id in _manager_cache:
            mgr = _manager_cache[instance_id]
            if mgr is not None:
                return mgr
    inst = await get_instance(instance_id)
    if inst is None:
        return None
    return get_manager_sync(inst)


async def load_instances() -> list[InstanceModel]:
    async with get_session() as session:
        stmt = select(InstanceModel).order_by(InstanceModel.name)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_instance(instance_id: str) -> Optional[InstanceModel]:
    async with get_session() as session:
        return await session.get(InstanceModel, instance_id)


async def add_instance(config: InstanceModel) -> bool:
    async with get_session() as session:
        existing = await session.get(InstanceModel, config.id)
        if existing:
            return False
        session.add(config)
        await session.commit()
    _manager_cache.pop(config.id, None)
    return True


async def remove_instance(instance_id: str) -> bool:
    mgr = _manager_cache.get(instance_id)
    if mgr and mgr.is_running():
        mgr.stop()
    async with get_session() as session:
        inst = await session.get(InstanceModel, instance_id)
        if inst is None:
            return False
        await session.delete(inst)
        await session.commit()
    _manager_cache.pop(instance_id, None)
    return True


async def update_instance(config: InstanceModel) -> bool:
    async with get_session() as session:
        existing = await session.get(InstanceModel, config.id)
        if existing is None:
            return False
        for key in ("name", "project_id", "enabled",
                     "server_dir", "server_filename", "java_executable_path",
                     "max_memory", "min_memory", "additional_flags", "arguments",
                     "api_url", "auth_plugin", "injector_filename",
                     "auto_restart", "auto_accept_eula", "version", "jar_url",
                     "modpack_id"):
            setattr(existing, key, getattr(config, key))
        await session.commit()
    _manager_cache.pop(config.id, None)
    return True


async def instance_exists(instance_id: str) -> bool:
    return await get_instance(instance_id) is not None


async def reload_manager(instance_id: str) -> bool:
    with _lock:
        old = _manager_cache.get(instance_id)
        was_running = old is not None and old.is_running()
        _manager_cache.pop(instance_id, None)

    inst = await get_instance(instance_id)
    if inst is None:
        return False

    mgr = _create_manager(inst)
    _manager_cache[instance_id] = mgr

    if was_running:
        mgr.start()
    return True


def migrate_instances_from_json():
    from server.config import SERVER_DIR
    json_path = SERVER_DIR / "instances.json"
    if not json_path.exists():
        return

    import json
    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, Exception):
        return

    if not isinstance(data, list) or not data:
        return

    import asyncio
    from server.database import get_session

    async def _migrate():
        async with get_session() as session:
            for item in data:
                existing = await session.get(InstanceModel, item.get("id", ""))
                if existing:
                    continue
                instance = InstanceModel(
                    id=item.get("id", "default"),
                    name=item.get("name", "Default Server"),
                    project_id=item.get("project_id", ""),
                    enabled=item.get("enabled", True),
                    server_dir=item.get("server_dir", str(Path.cwd())),
                    server_filename=item.get("server_filename", "server.jar"),
                    java_executable_path=item.get("java_executable_path", "java"),
                    max_memory=item.get("max_memory", 2048),
                    min_memory=item.get("min_memory", 1024),
                    additional_flags=item.get("additional_flags", ""),
                    arguments=item.get("arguments", ""),
                    api_url=item.get("api_url", "http://127.0.0.1:25581"),
                    auth_plugin=item.get("auth_plugin", "injector"),
                    injector_filename=item.get("injector_filename", "authlib-injector.jar"),
                    auto_restart=item.get("auto_restart", False),
                    auto_accept_eula=item.get("auto_accept_eula", True),
                    version=item.get("version", ""),
                    jar_url=item.get("jar_url", ""),
                )
                session.add(instance)
            await session.commit()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_migrate())
    finally:
        loop.close()

    backup = json_path.with_suffix(".json.bak")
    json_path.rename(backup)