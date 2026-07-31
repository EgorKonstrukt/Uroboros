import threading
import re
import time
import typing
import json
import shutil
import hashlib
import hmac
import asyncio
import uuid
from dataclasses import fields, asdict
from datetime import datetime
from typing import get_type_hints
from pathlib import Path

from fastapi import APIRouter, Depends, Request, File, Form, UploadFile
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from server.config import ServerConfig, SERVER_DIR
from server.web.auth import require_admin, create_token, delete_token
from server.auth.ratelimit import login_limiter
from server.auth.crypto import hash_password
from server.models import InstanceModel, ModpackModel, UserModel, UserBanModel, ServerSessionModel
from server.database import get_session
from sqlalchemy import select, update, delete
from server.mc.registry import (
    load_instances, get_instance,
    add_instance, remove_instance, update_instance,
    get_manager, get_manager_sync, reload_manager,
)
from server.mc.config import instance_model_to_dict, dict_to_instance_model
from server.mc.pidfile import is_running
from server.mc.whitelist import sync_instance_whitelist, sync_all_whitelists
from server.mc.bans import (
    sync_all_bans, create_ban, remove_ban, remove_ban_by_id,
)

router = APIRouter(dependencies=[Depends(require_admin)])

_static_dir = Path(__file__).parent / "static"
_template_dir = Path(__file__).parent / "templates"

router.mount("/static", StaticFiles(directory=str(_static_dir)), name="admin_static")

_INSTANCE_FIELD_META = {
    "name": {"label": "Server Name", "description": "Human-readable server name"},
    "enabled": {"label": "Enabled", "description": "Enable this server instance"},
    "server_dir": {"label": "Server Directory", "description": "Working directory for the MC server"},
    "server_filename": {"label": "Server JAR", "description": "Minecraft server JAR filename"},
    "java_executable_path": {"label": "Java Executable", "description": "Path to java binary"},
    "max_memory": {"label": "Max Memory (MB)", "description": "Max heap size (-Xmx)"},
    "min_memory": {"label": "Min Memory (MB)", "description": "Min heap size (-Xms)"},
    "additional_flags": {"label": "JVM Flags", "description": "Extra JVM flags"},
    "arguments": {"label": "Server Arguments", "description": "Args passed to the JAR (e.g. --nogui)"},
    "api_url": {"label": "Auth API URL", "description": "Auth server URL for the injector"},
    "auth_plugin": {"label": "Auth Plugin", "description": "Authentication plugin type"},
    "injector_filename": {"label": "Injector JAR", "description": "authlib-injector JAR filename"},
    "auto_restart": {"label": "Auto Restart", "description": "Automatically restart on crash"},
    "auto_accept_eula": {"label": "Auto Accept EULA", "description": "Write eula=true before starting"},
    "whitelist_enabled": {"label": "Whitelist Mode", "description": "Enable whitelist and sync player nicknames from the database"},
    "version": {"label": "MC Version", "description": "Minecraft version (e.g. 1.20.1)"},
    "jar_url": {"label": "JAR Download URL", "description": "URL to download server JAR (optional)"},
    "project_id": {"label": "Linked Project ID", "description": "Project that this instance belongs to"},
    "modpack_id": {"label": "Modpack", "description": "Modpack to install on this server"},
}


def _unwrap_type(annotation) -> type:
    origin = typing.get_origin(annotation)
    if origin is not None:
        args = typing.get_args(annotation)
        if args:
            return args[0]
    if annotation is bool:
        return bool
    if annotation is int:
        return int
    return annotation

def _get_inst_field_type(field_name: str) -> str:
    hints = InstanceModel.__annotations__
    raw = hints.get(field_name, str)
    actual = _unwrap_type(raw)
    if actual is bool:
        return "bool"
    if actual is int:
        return "int"
    return "str"


def _get_sorted_java_options() -> list:
    from server.mc.java import get_cached
    runtimes = get_cached()
    result = [j.path for j in runtimes] + ["java"]
    seen = set()
    unique = []
    for p in result:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


async def _get_modpack_options() -> list:
    try:
        from server.database import get_session
        from server.models import ModpackModel, ProjectModel
        from sqlalchemy import select
        options = [{"value": "", "label": "(None)"}]
        async with get_session() as session:
            stmt = select(
                ModpackModel.id, ModpackModel.name,
                ModpackModel.project_id, ProjectModel.name.label("proj_name")
            ).join(ProjectModel, ModpackModel.project_id == ProjectModel.id)
            rows = (await session.execute(stmt)).all()
            for r in rows:
                label = f"{r.proj_name}/{r.name}" if r.proj_name else r.name
                options.append({"value": r.id, "label": label, "project_id": r.project_id})
        return options
    except Exception:
        return [{"value": "", "label": "(None)"}]


def _instance_to_api(inst: InstanceModel) -> dict:
    mgr = get_manager_sync(inst)
    running = mgr is not None and mgr.is_running()
    result = instance_model_to_dict(inst)
    result["running"] = running
    result["last_error"] = mgr.last_error if mgr else None
    if running and mgr and mgr.process:
        result["pid"] = mgr.process.pid
        try:
            import psutil
            p = psutil.Process(mgr.process.pid)
            result["cpu_percent"] = p.cpu_percent(interval=0)
            result["memory_mb"] = round(p.memory_info().rss / 1024 / 1024, 1)
            result["uptime_seconds"] = int(time.time() - p.create_time())
        except Exception:
            pass
    return result


# ── List instances ──

@router.get("/instances")
async def list_instances():
    instances = await load_instances()
    modpack_names = {}
    project_names = {}
    try:
        from server.database import get_session
        from server.models import ModpackModel, ProjectModel
        from sqlalchemy import select
        async with get_session() as session:
            mrows = (await session.execute(select(ModpackModel.id, ModpackModel.name))).all()
            for mid, mname in mrows:
                modpack_names[mid] = mname
            prows = (await session.execute(select(ProjectModel.id, ProjectModel.name))).all()
            for pid, pname in prows:
                project_names[pid] = pname
    except Exception:
        pass
    result = []
    for inst in instances:
        d = _instance_to_api(inst)
        d["modpack_name"] = modpack_names.get(inst.modpack_id or "", "") if inst.modpack_id else ""
        d["project_name"] = project_names.get(inst.project_id or "", "") if inst.project_id else ""
        result.append(d)
    return result


@router.get("/instances/{instance_id}")
async def get_instance_route(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    return _instance_to_api(inst)


@router.post("/instances")
async def create_instance(body: dict):
    iid = body.get("id", "").strip()
    name = body.get("name", "").strip() or iid
    if not iid or not re.match(r"^[a-zA-Z0-9_-]+$", iid):
        return JSONResponse(content={"error": "Invalid ID (alphanumeric, hyphens, underscores only)"}, status_code=400)
    existing = await get_instance(iid)
    if existing:
        return JSONResponse(content={"error": f"Instance '{iid}' already exists"}, status_code=409)
    inst = InstanceModel(id=iid, name=name)
    inst = dict_to_instance_model(body, inst)
    if await add_instance(inst):
        return _instance_to_api(inst)
    return JSONResponse(content={"error": "Failed to create"}, status_code=500)


@router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str):
    if not await get_instance(instance_id):
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if await remove_instance(instance_id):
        return {"status": "deleted", "id": instance_id}
    return JSONResponse(content={"error": "Failed to delete"}, status_code=500)


@router.patch("/instances/{instance_id}")
async def update_instance_route(instance_id: str, body: dict):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    for key in body:
        if key in ("id",):
            continue
        expected = InstanceModel.__annotations__.get(key)
        if expected is None:
            continue
        actual = _unwrap_type(expected)
        val = body[key]
        if actual is bool:
            if isinstance(val, str):
                val = val.lower() in ("true", "1", "yes")
            elif not isinstance(val, bool):
                continue
        elif actual is int:
            try:
                val = int(val)
            except (TypeError, ValueError):
                continue
        setattr(inst, key, val)
    if "modpack_id" in body and body["modpack_id"]:
        try:
            from server.database import get_session
            from server.models import ModpackModel
            from sqlalchemy import select
            async with get_session() as session:
                stmt = select(ModpackModel.project_id).where(ModpackModel.id == body["modpack_id"])
                pid = (await session.execute(stmt)).scalar_one_or_none()
                if pid:
                    inst.project_id = pid
        except Exception:
            pass
    if await update_instance(inst):
        if inst.whitelist_enabled:
            await sync_instance_whitelist(inst)
        return _instance_to_api(inst)
    return JSONResponse(content={"error": "Failed to update"}, status_code=500)


# ── Per-instance config schema ──

@router.get("/instances/{instance_id}/schema")
async def instance_schema(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    hints = InstanceModel.__annotations__
    result = []
    for key in sorted(hints.keys()):
        if key.startswith("_") or key in ("id", "created_at"):
            continue
        meta = _INSTANCE_FIELD_META.get(key, {})
        ftype = _get_inst_field_type(key)
        raw_val = getattr(inst, key, None)
        default_val = "" if raw_val is None else raw_val
        item = {
            "key": key,
            "type": ftype,
            "value": raw_val if raw_val is not None else ("" if ftype != "int" else 0),
            "default": default_val,
            "label": meta.get("label", key),
            "description": meta.get("description", ""),
        }
        if key == "auth_plugin":
            item["options"] = ["injector", ""]
        if key == "java_executable_path":
            item["options"] = _get_sorted_java_options()
        if key == "modpack_id":
            item["options"] = await _get_modpack_options()
        result.append(item)
    return result


# ── Server actions ──

@router.get("/instances/{instance_id}/status")
async def instance_status(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    return _instance_to_api(inst)


@router.post("/instances/{instance_id}/start")
async def instance_start(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    # Auto-install modpack files before starting
    if inst.modpack_id:
        mp_dir = _modpack_dir(inst.project_id or "", inst.modpack_id)
        if mp_dir.exists():
            server_dir = Path(inst.server_dir)
            if server_dir.exists():
                for entry in mp_dir.rglob("*"):
                    if entry.is_file() and entry.name != "files.json":
                        rel = entry.relative_to(mp_dir)
                        dest = server_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(entry, dest)
    mgr = await get_manager(instance_id)
    if mgr is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if mgr.is_running():
        return JSONResponse(content={"error": "Already running"}, status_code=400)
    if inst.whitelist_enabled:
        await sync_instance_whitelist(inst)
    if mgr.start():
        threading.Thread(target=mgr.process.wait, daemon=True).start()
        return {"status": "started", "pid": mgr.process.pid, "id": instance_id}
    err = mgr.last_error or "Start failed"
    return JSONResponse(content={"error": err}, status_code=500)


@router.post("/instances/{instance_id}/stop")
async def instance_stop(instance_id: str):
    mgr = await get_manager(instance_id)
    if mgr is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if not mgr.is_running():
        return JSONResponse(content={"error": "Not running"}, status_code=400)
    mgr.stop()
    return {"status": "stopped", "id": instance_id}


@router.post("/instances/{instance_id}/restart")
async def instance_restart(instance_id: str):
    mgr = await get_manager(instance_id)
    if mgr is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if mgr.restart():
        threading.Thread(target=mgr.process.wait, daemon=True).start()
        return {"status": "restarted", "pid": mgr.process.pid, "id": instance_id}
    err = mgr.last_error or "Restart failed"
    return JSONResponse(content={"error": err}, status_code=500)


@router.post("/instances/{instance_id}/whitelist/sync")
async def instance_whitelist_sync(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    result = await sync_instance_whitelist(inst)
    mgr = await get_manager(instance_id)
    if mgr and mgr.is_running():
        mgr.send_command("whitelist reload")
    return result


@router.post("/instances/{instance_id}/install-modpack")
async def install_instance_modpack(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if not inst.modpack_id:
        return JSONResponse(content={"error": "No modpack linked to this server"}, status_code=400)
    mp_dir = _modpack_dir(inst.project_id or "", inst.modpack_id)
    if not mp_dir.exists():
        return JSONResponse(content={"error": "Modpack directory not found on server"}, status_code=404)
    server_dir = Path(inst.server_dir)
    if not server_dir.exists():
        return JSONResponse(content={"error": "Server directory not found"}, status_code=404)
    all_files = [e for e in mp_dir.rglob("*") if e.is_file() and e.name != "files.json"]
    total = len(all_files)
    copied = 0
    for idx, entry in enumerate(all_files):
        rel = entry.relative_to(mp_dir)
        dest = server_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, dest)
        copied += 1
    return {"status": "ok", "files_copied": copied, "file_count": total, "modpack": inst.modpack_id}


@router.get("/instances/{instance_id}/output")
async def instance_output(instance_id: str, tail: int = 100):
    mgr = await get_manager(instance_id)
    if mgr is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    return {"lines": mgr.get_output(tail), "running": mgr.is_running(), "id": instance_id}


@router.post("/instances/{instance_id}/command")
async def instance_command(instance_id: str, command: str):
    mgr = await get_manager(instance_id)
    if mgr is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if not mgr.is_running():
        return JSONResponse(content={"error": "Not running"}, status_code=400)
    mgr.send_command(command)
    return {"status": "sent", "id": instance_id}


# ── Global config ──

@router.get("/config")
async def get_config():
    cfg = ServerConfig.load()
    return {k: v for k, v in asdict(cfg).items() if not k.startswith("_")}


_GLOBAL_FIELD_META = {
    "host": {"label": "Bind Host", "description": "IP address for the HTTP server"},
    "port": {"label": "Port", "description": "HTTP server port"},
    "db_path": {"label": "Database Path", "description": "SQLite database file location"},
    "admin_password": {"label": "Admin Password", "description": "Password to protect this panel (auto-generated if empty)"},
    "log_level": {"label": "Log Level", "description": "Logging verbosity"},
    "curseforge_api_key": {"label": "CurseForge API Key", "description": "API key for CurseForge mod resolution (optional)"},
}


@router.get("/config/schema")
async def get_config_schema():
    cfg = ServerConfig.load()
    raw = asdict(cfg)
    result = []
    for f in fields(ServerConfig):
        if f.name.startswith("_"):
            continue
        meta = _GLOBAL_FIELD_META.get(f.name, {})
        hints = get_type_hints(ServerConfig)
        ftype = hints.get(f.name, str)
        if ftype is bool:
            stype = "bool"
        elif ftype is int:
            stype = "int"
        else:
            stype = "str"
        item = {
            "key": f.name,
            "type": stype,
            "value": raw.get(f.name),
            "default": f.default if f.default != f.default_factory else None,
            "label": meta.get("label", f.name),
            "description": meta.get("description", ""),
        }
        if f.name == "admin_password":
            item["type"] = "password"
            item["value"] = ""
        if f.name == "log_level":
            item["options"] = ["critical", "error", "warning", "info", "debug"]
        result.append(item)
    return result


@router.post("/config")
async def update_config(body: dict):
    cfg = ServerConfig.load()
    errors = []
    updated = {}
    hints = get_type_hints(ServerConfig)
    for key, value in body.items():
        if not hasattr(cfg, key):
            errors.append(f"Unknown field: {key}")
            continue
        expected = hints.get(key)
        if expected is bool:
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
            elif not isinstance(value, bool):
                errors.append(f"{key}: expected boolean")
                continue
        elif expected is int:
            try:
                value = int(value)
            except (TypeError, ValueError):
                errors.append(f"{key}: expected integer")
                continue
        setattr(cfg, key, value)
        updated[key] = value
    if errors:
        return JSONResponse(content={"status": "partial", "updated": updated, "errors": errors}, status_code=400)
    cfg.save()
    return {"status": "saved", "updated": updated}


# ── Logs (global) ──

@router.get("/logs")
async def get_logs(tail: int = 50):
    from server.config import SERVER_DIR
    log_file = SERVER_DIR / "server.log"
    if not log_file.exists():
        return {"lines": []}
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    return {"lines": all_lines[-tail:], "total": len(all_lines)}


# ── Files (per-instance) ──

@router.get("/instances/{instance_id}/files")
async def list_files(instance_id: str, path: str = ""):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    base = Path(inst.server_dir)
    target = base
    if path:
        target = (base / path).resolve()
        if not str(target).startswith(str(base.resolve())):
            return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
    if not target.exists() or not target.is_dir():
        return JSONResponse(content={"error": "Directory not found"}, status_code=404)
    items = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        stat = entry.stat()
        items.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": stat.st_size if entry.is_file() else 0,
            "modified": stat.st_mtime,
        })
    rel = str(target.relative_to(base)) if target != base else ""
    return {"path": rel, "absolute": str(target), "items": items}


async def _resolve_file_path(instance_id: str, file_path: str) -> Path | None:
    inst = await get_instance(instance_id)
    if inst is None:
        return None
    base = Path(inst.server_dir).resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        return None
    return target


@router.get("/instances/{instance_id}/files/read")
async def read_file(instance_id: str, path: str = ""):
    target = await _resolve_file_path(instance_id, path)
    if target is None:
        return JSONResponse(content={"error": "File not found or access denied"}, status_code=404)
    if not target.exists() or not target.is_file():
        return JSONResponse(content={"error": "Not a file"}, status_code=404)
    try:
        content = target.read_bytes()
        is_text = True
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            is_text = False
        return {
            "path": str(target),
            "name": target.name,
            "size": len(content),
            "is_text": is_text,
            "content": content.decode("utf-8", errors="replace").replace("\r\n", "\n") if is_text else "",
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/instances/{instance_id}/files/write")
async def write_file(instance_id: str, body: dict):
    target = await _resolve_file_path(instance_id, body.get("path", ""))
    if target is None:
        return JSONResponse(content={"error": "Access denied"}, status_code=403)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        content = body.get("content", "")
        target.write_text(content, encoding="utf-8")
        return {"status": "saved", "path": str(target)}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/instances/{instance_id}/files/upload")
async def upload_file(instance_id: str, file: UploadFile = File(...), path: str = Form("")):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    base = Path(inst.server_dir).resolve()
    target = base
    if path:
        target = (base / path).resolve()
        if not str(target).startswith(str(base)):
            return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
    if not target.exists() or not target.is_dir():
        return JSONResponse(content={"error": "Directory not found"}, status_code=404)
    file_path = target / file.filename
    try:
        content = await file.read()
        file_path.write_bytes(content)
        return {"status": "uploaded", "path": str(file_path), "size": len(content)}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ── Java management ──

@router.get("/java")
async def list_java():
    from server.mc.java import get_cached
    return [{"path": j.path, "version": j.version, "major": j.major_version, "vendor": j.vendor, "arch": j.arch} for j in get_cached()]


@router.post("/java/scan")
async def scan_java():
    from server.mc.java import scan_java as do_scan
    runtimes = do_scan()
    return {
        "found": len(runtimes),
        "runtimes": [{"path": j.path, "version": j.version, "major": j.major_version, "vendor": j.vendor, "arch": j.arch} for j in runtimes],
    }


# ── Modpack management ──

PROJECTS_STORAGE = SERVER_DIR / "projects"


def _modpack_dir(project_id: str, modpack_id: str) -> Path:
    return PROJECTS_STORAGE / project_id / "modpacks" / modpack_id


def _update_files_hash(project_id: str, modpack_id: str):
    mp_dir = _modpack_dir(project_id, modpack_id)
    if not mp_dir.exists():
        return
    index = {}
    for entry in sorted(mp_dir.rglob("*")):
        if entry.is_file() and entry.name != "files.json":
            rel = entry.relative_to(mp_dir).as_posix()
            index[rel] = hashlib.sha256(entry.read_bytes()).hexdigest()
    (mp_dir / "files.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


async def _modpack_model_to_dict(m: ModpackModel) -> dict:
    mp_dir = _modpack_dir(m.project_id, m.id)
    file_count = len([f for f in mp_dir.iterdir() if f.is_file()]) if mp_dir.exists() else 0
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description,
        "version": m.version,
        "mc_version": m.mc_version,
        "loader": m.loader,
        "loader_version": m.loader_version,
        "min_memory": m.min_memory,
        "max_memory": m.max_memory,
        "java_args": m.java_args,
        "java_path": m.java_path,
        "changelog": m.changelog,
        "file_count": file_count,
    }


async def _get_modpack(project_id: str, modpack_id: str) -> ModpackModel | None:
    async with get_session() as session:
        stmt = select(ModpackModel).where(
            ModpackModel.project_id == project_id,
            ModpackModel.id == modpack_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def _migrate_modpacks_from_json():
    """One-time migration from JSON metadata files to DB."""
    projects_dir = PROJECTS_STORAGE
    if not projects_dir.exists():
        return
    async with get_session() as session:
        for proj_dir in projects_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            pid = proj_dir.name
            mp_base = proj_dir / "modpacks"
            if not mp_base.exists():
                continue
            for mp_dir in mp_base.iterdir():
                if not mp_dir.is_dir():
                    continue
                meta_path = mp_dir / "metadata.json"
                if not meta_path.exists():
                    continue
                existing = await session.get(ModpackModel, (mp_dir.name, pid))
                if existing:
                    continue
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                session.add(ModpackModel(
                    id=mp_dir.name,
                    project_id=pid,
                    name=meta.get("name", mp_dir.name),
                    description=meta.get("description", ""),
                    version=meta.get("version", "1.0"),
                    mc_version=meta.get("mc_version", ""),
                    loader=meta.get("loader", ""),
                    loader_version=meta.get("loader_version", ""),
                    min_memory=meta.get("min_memory", 1024),
                    max_memory=meta.get("max_memory", 2048),
                    java_args=meta.get("java_args", ""),
                    java_path=meta.get("java_path", ""),
                    changelog=meta.get("changelog", ""),
                ))
        await session.commit()


@router.get("/projects/{project_id}/modpacks")
async def list_modpacks(project_id: str):
    async with get_session() as session:
        stmt = select(ModpackModel).where(
            ModpackModel.project_id == project_id
        ).order_by(ModpackModel.name)
        result = await session.execute(stmt)
        modpacks = result.scalars().all()
        return [await _modpack_model_to_dict(m) for m in modpacks]


@router.post("/projects/{project_id}/modpacks")
async def create_modpack(project_id: str, body: dict):
    import uuid
    mpid = body.get("id", "").strip() or uuid.uuid4().hex[:8]
    async with get_session() as session:
        existing = await session.get(ModpackModel, (mpid, project_id))
        if existing:
            return JSONResponse(content={"error": "Modpack already exists"}, status_code=409)
        m = ModpackModel(
            id=mpid,
            project_id=project_id,
            name=body.get("name", mpid),
            description=body.get("description", ""),
            version=body.get("version", "1.0"),
            mc_version=body.get("mc_version", ""),
            loader=body.get("loader", ""),
            loader_version=body.get("loader_version", ""),
            min_memory=body.get("min_memory", 1024),
            max_memory=body.get("max_memory", 2048),
            java_args=body.get("java_args", ""),
            java_path=body.get("java_path", ""),
            changelog=body.get("changelog", ""),
        )
        session.add(m)
        await session.commit()
        _modpack_dir(project_id, mpid).mkdir(parents=True, exist_ok=True)
        return await _modpack_model_to_dict(m)


@router.get("/projects/{project_id}/modpacks/{modpack_id}")
async def get_modpack(project_id: str, modpack_id: str):
    m = await _get_modpack(project_id, modpack_id)
    if not m:
        return JSONResponse(content={"error": "Modpack not found"}, status_code=404)
    return await _modpack_model_to_dict(m)


@router.put("/projects/{project_id}/modpacks/{modpack_id}")
async def update_modpack(project_id: str, modpack_id: str, body: dict):
    async with get_session() as session:
        m = await session.get(ModpackModel, (modpack_id, project_id))
        if not m:
            return JSONResponse(content={"error": "Modpack not found"}, status_code=404)
        for key in ("name", "description", "version", "mc_version", "loader",
                    "loader_version", "min_memory", "max_memory", "java_args",
                    "java_path", "changelog"):
            if key in body:
                setattr(m, key, body[key])
        await session.commit()
        return await _modpack_model_to_dict(m)


@router.delete("/projects/{project_id}/modpacks/{modpack_id}")
async def delete_modpack(project_id: str, modpack_id: str):
    async with get_session() as session:
        m = await session.get(ModpackModel, (modpack_id, project_id))
        if not m:
            return JSONResponse(content={"error": "Modpack not found"}, status_code=404)
        await session.delete(m)
        await session.commit()
    mp_dir = _modpack_dir(project_id, modpack_id)
    if mp_dir.exists():
        shutil.rmtree(mp_dir, ignore_errors=True)
    return {"status": "deleted"}


@router.get("/projects/{project_id}/modpacks/{modpack_id}/mods")
async def list_modpack_mods(project_id: str, modpack_id: str):
    mp_dir = _modpack_dir(project_id, modpack_id)
    if not mp_dir.exists():
        mp_dir.mkdir(parents=True, exist_ok=True)
    index_path = mp_dir / "files.json"
    hash_index = {}
    if index_path.exists():
        hash_index = json.loads(index_path.read_text(encoding="utf-8"))
    items = []
    for entry in sorted(mp_dir.rglob("*.jar"), key=lambda e: str(e).lower()):
        if entry.is_file():
            rel = entry.relative_to(mp_dir).as_posix()
            stat = entry.stat()
            items.append({
                "name": rel,
                "size": stat.st_size,
                "sha256": hash_index.get(rel, ""),
                "modified": stat.st_mtime,
            })
    return {"items": items}


# ── Modpack file manager ──

EMPTY_DIR_MARKER = ".uroboros_keep"


async def _resolve_mp_path(project_id: str, modpack_id: str, file_path: str) -> Path | None:
    mp_dir = _modpack_dir(project_id, modpack_id)
    if not mp_dir.exists():
        return None
    base = mp_dir.resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        return None
    return target


@router.get("/projects/{project_id}/modpacks/{modpack_id}/files")
async def list_modpack_files(project_id: str, modpack_id: str, path: str = ""):
    mp_dir = _modpack_dir(project_id, modpack_id)
    mp_dir.mkdir(parents=True, exist_ok=True)
    target = mp_dir
    if path:
        resolved = await _resolve_mp_path(project_id, modpack_id, path)
        if resolved is None:
            return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
        if not resolved.exists() or not resolved.is_dir():
            return JSONResponse(content={"error": "Directory not found"}, status_code=404)
        target = resolved
    items = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if entry.name == "files.json" or entry.name == EMPTY_DIR_MARKER:
            continue
        stat = entry.stat()
        items.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": stat.st_size if entry.is_file() else 0,
            "modified": stat.st_mtime,
        })
    rel = str(target.relative_to(mp_dir).as_posix()) if target != mp_dir else ""
    return {"path": rel, "absolute": str(target), "items": items}


@router.get("/projects/{project_id}/modpacks/{modpack_id}/files/read")
async def read_modpack_file(project_id: str, modpack_id: str, path: str = ""):
    target = await _resolve_mp_path(project_id, modpack_id, path)
    if target is None:
        return JSONResponse(content={"error": "File not found or access denied"}, status_code=404)
    if not target.exists() or not target.is_file():
        return JSONResponse(content={"error": "Not a file"}, status_code=404)
    try:
        content = target.read_bytes()
        is_text = True
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            is_text = False
        return {
            "path": str(target),
            "name": target.name,
            "size": len(content),
            "is_text": is_text,
            "content": content.decode("utf-8", errors="replace").replace("\r\n", "\n") if is_text else "",
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/write")
async def write_modpack_file(project_id: str, modpack_id: str, body: dict):
    target = await _resolve_mp_path(project_id, modpack_id, body.get("path", ""))
    if target is None:
        return JSONResponse(content={"error": "Access denied"}, status_code=403)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        content = body.get("content", "")
        target.write_text(content, encoding="utf-8")
        _update_files_hash(project_id, modpack_id)
        return {"status": "saved", "path": body["path"]}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/projects/{project_id}/modpacks/{modpack_id}/files/download")
async def download_modpack_file(project_id: str, modpack_id: str, path: str = ""):
    target = await _resolve_mp_path(project_id, modpack_id, path)
    if target is None or not target.exists() or not target.is_file():
        return JSONResponse(content={"error": "File not found"}, status_code=404)
    from starlette.responses import FileResponse
    return FileResponse(target, filename=target.name)


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/extract")
async def extract_modpack_archive(
    project_id: str, modpack_id: str,
    file: UploadFile = File(...),
    clear: bool = Form(False),
):
    """Extract a zip/archive directly into the modpack directory (not CF/MR import)."""
    mp_dir = _modpack_dir(project_id, modpack_id)
    mp_dir.mkdir(parents=True, exist_ok=True)
    if not file.filename.lower().endswith(('.zip', '.mrpack')):
        return JSONResponse(content={"error": "Only .zip or .mrpack archives supported"}, status_code=400)
    import zipfile, tempfile, shutil
    try:
        content = await file.read()
        if clear:
            for child in list(mp_dir.iterdir()):
                if child.name == "files.json":
                    continue
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / file.filename
            archive_path.write_bytes(content)
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(str(tmp_path / "extracted"))
            extracted = tmp_path / "extracted"
            if not extracted.exists():
                return JSONResponse(content={"error": "Empty archive"}, status_code=400)
            subdirs = [d for d in extracted.iterdir() if d.is_dir()]
            if len(subdirs) == 1 and not any(f.is_file() for f in extracted.iterdir() if f.name != "__MACOSX"):
                extracted = subdirs[0]
            total = 0
            for entry in extracted.rglob("*"):
                if entry.is_file():
                    rel = entry.relative_to(extracted).as_posix()
                    if rel == "files.json":
                        continue
                    dest = mp_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(entry, dest)
                    total += 1
        _update_files_hash(project_id, modpack_id)
        return {"status": "extracted", "files": total}
    except zipfile.BadZipFile:
        return JSONResponse(content={"error": "Invalid zip archive"}, status_code=400)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/upload")
async def upload_modpack_file(
    project_id: str, modpack_id: str,
    file: UploadFile = File(...),
    path: str = Form(""),
):
    mp_dir = _modpack_dir(project_id, modpack_id)
    mp_dir.mkdir(parents=True, exist_ok=True)
    target_dir = mp_dir
    if path:
        resolved = await _resolve_mp_path(project_id, modpack_id, path)
        if resolved is None:
            return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
        if not resolved.exists():
            resolved.mkdir(parents=True, exist_ok=True)
        target_dir = resolved
    file_path = target_dir / file.filename
    try:
        content = await file.read()
        file_path.write_bytes(content)
        _update_files_hash(project_id, modpack_id)
        return {"status": "uploaded", "path": str(file_path), "size": len(content)}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.delete("/projects/{project_id}/modpacks/{modpack_id}/files")
async def delete_modpack_file(project_id: str, modpack_id: str, path: str = ""):
    if not path:
        return JSONResponse(content={"error": "path is required"}, status_code=400)
    target = await _resolve_mp_path(project_id, modpack_id, path)
    if target is None:
        return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
    if not target.exists():
        return JSONResponse(content={"error": "Not found"}, status_code=404)
    try:
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        _update_files_hash(project_id, modpack_id)
        return {"status": "deleted"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ── Async import task tracking ──

_import_tasks: dict[str, dict] = {}
_import_tasks_lock = threading.Lock()


def _make_progress_callback(task_id: str):
    def cb(state: dict):
        with _import_tasks_lock:
            if task_id in _import_tasks:
                _import_tasks[task_id].update(state)
    return cb


# ── Modpack import from archive ──


@router.post("/projects/{project_id}/modpacks/{modpack_id}/import")
async def import_modpack(
    project_id: str, modpack_id: str,
    file: UploadFile = File(...),
):
    from server.modpack_importer import import_modpack_archive

    mp_dir = _modpack_dir(project_id, modpack_id)
    mp_dir.mkdir(parents=True, exist_ok=True)

    task_id = str(uuid.uuid4())
    with _import_tasks_lock:
        _import_tasks[task_id] = {"status": "starting", "current": 0, "total": 0, "message": "Starting...", "error": ""}

    archive_path = mp_dir / f"__import_{file.filename}"
    try:
        content = await file.read()
        archive_path.write_bytes(content)
    except Exception as e:
        with _import_tasks_lock:
            if task_id in _import_tasks:
                _import_tasks[task_id]["status"] = "error"
                _import_tasks[task_id]["error"] = str(e)
        return JSONResponse(content={"task_id": task_id}, status_code=202)

    async def run_import():
        try:
            result = await import_modpack_archive(project_id, modpack_id, archive_path,
                                                   progress_callback=_make_progress_callback(task_id))
            with _import_tasks_lock:
                if task_id in _import_tasks:
                    t = _import_tasks[task_id]
                    t["status"] = "error" if result.get("status") == "error" else "done"
                    t["result"] = result
                    if result.get("error"):
                        t["error"] = result["error"]
        except Exception as e:
            with _import_tasks_lock:
                if task_id in _import_tasks:
                    _import_tasks[task_id]["status"] = "error"
                    _import_tasks[task_id]["error"] = str(e)
        finally:
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)

    asyncio.create_task(run_import())
    return JSONResponse(content={"task_id": task_id}, status_code=202)


@router.get("/projects/{project_id}/modpacks/{modpack_id}/import-progress/{task_id}")
async def import_progress(project_id: str, modpack_id: str, task_id: str):
    with _import_tasks_lock:
        state = _import_tasks.get(task_id)
    if state is None:
        return JSONResponse(content={"error": "Task not found"}, status_code=404)
    resp = {k: v for k, v in state.items() if k != "result"}
    if state.get("status") in ("done", "error"):
        resp["result"] = state.get("result")
        # Clean up completed tasks after returning
        def cleanup():
            with _import_tasks_lock:
                _import_tasks.pop(task_id, None)
        threading.Thread(target=cleanup, daemon=True).start()
    return resp





# ── Dashboard pages ──

@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard():
    with open(_template_dir / "admin.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ── Auth endpoints ──

@router.get("/auth-status")
async def auth_status(request: Request):
    from server.web.auth import validate_token
    cfg = ServerConfig.load()
    enabled = bool(cfg.admin_password)
    authenticated = False
    if enabled:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and validate_token(auth[7:]):
            authenticated = True
    return {"enabled": enabled, "authenticated": authenticated}


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    cfg = ServerConfig.load()
    if not cfg.admin_password:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin/")
    with open(_template_dir / "login.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@router.post("/login")
async def login(request: Request, body: dict):
    cfg = ServerConfig.load()
    if not cfg.admin_password:
        return JSONResponse(content={"error": "Auth is disabled"}, status_code=400)
    ip = request.client.host if request.client else ""
    if not login_limiter.allow(ip):
        return JSONResponse(content={"error": "Too many attempts, try again later"}, status_code=429)
    password = body.get("password", "")
    if not hmac.compare_digest(password.encode("utf-8"), cfg.admin_password.encode("utf-8")):
        return JSONResponse(content={"error": "Invalid password"}, status_code=401)
    token = create_token()
    return {"token": token}


@router.post("/logout")
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        delete_token(auth[7:])
    return {"status": "logged_out"}


# ── Players management ──

async def _instance_names() -> dict:
    instances = await load_instances()
    return {i.id: i.name for i in instances}


_online_probe_cache = {"ts": 0.0, "data": {}}
ONLINE_CACHE_TTL = 5.0


async def _probe_online_players() -> dict:
    now = time.time()
    if now - _online_probe_cache["ts"] < ONLINE_CACHE_TTL:
        return _online_probe_cache["data"]
    from server.web import _server_address
    from server.mc.status import probe
    from server.mc.pidfile import is_running as pid_running

    instances = await load_instances()
    tasks = []
    entries = []
    for inst in instances:
        if not inst.enabled:
            continue
        running = get_manager_sync(inst).is_running() or pid_running(inst.id)
        if not running:
            continue
        host, port = _server_address(inst)
        entries.append((inst.id, inst.name or inst.id))
        tasks.append(asyncio.to_thread(probe, host, port, 2.0))

    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    online_by_name = {}
    for (iid, iname), status in zip(entries, results):
        if isinstance(status, Exception) or not status.get("online"):
            continue
        for entry in status.get("players_sample") or []:
            name = (entry.get("name") or "").strip()
            if name:
                online_by_name[name.lower()] = {
                    "instance_id": iid,
                    "instance_name": iname,
                }
    _online_probe_cache["ts"] = now
    _online_probe_cache["data"] = online_by_name
    return online_by_name


@router.get("/users")
async def admin_list_users():
    now = datetime.now()
    async with get_session() as session:
        users = (await session.execute(select(UserModel).order_by(UserModel.id))).scalars().all()
        sessions = (await session.execute(select(ServerSessionModel))).scalars().all()
    from server.mc.bans import _match_reasons, _active_ban_rows
    inst_names = await _instance_names()
    last_seen_by = {}
    for s in sessions:
        key = (s.display_name or "").lower()
        if s.created_at and (key not in last_seen_by or s.created_at > last_seen_by[key]):
            last_seen_by[key] = s.created_at
    online_map = await _probe_online_players()
    active_rows = [r for r in await _active_ban_rows()
                   if r[0].expires_at is None or r[0].expires_at > now]
    bans_by_user = {}
    for u in users:
        matching = []
        for ban, banned_user in active_rows:
            if ban.user_id == u.id or _match_reasons(banned_user, user=u):
                matching.append((ban, banned_user))
        bans_by_user[u.id] = matching
    return [
        {
            "id": u.id,
            "uuid": u.uuid,
            "username": u.username,
            "display_name": u.display_name,
            "email": u.email,
            "last_ip": u.last_ip or "",
            "ip_history": [
                {"ip": ip, "last_seen": ts}
                for ip, ts in sorted(
                    (u.ip_history or {}).items(), key=lambda kv: kv[1], reverse=True
                )
            ],
            "has_skin": bool(u.skin),
            "skin_model": u.skin_model or "classic",
            "online": bool(online_map.get((u.display_name or "").lower())),
            "current_server": (online_map.get((u.display_name or "").lower()) or {}).get("instance_id", ""),
            "current_server_name": (online_map.get((u.display_name or "").lower()) or {}).get("instance_name", ""),
            "last_seen": str(last_seen_by.get((u.display_name or "").lower(), "")) if last_seen_by.get((u.display_name or "").lower()) else "",
            "created_at": str(u.created_at),
            "bans": [
                {
                    "id": b.id,
                    "instance_id": b.instance_id,
                    "instance_name": inst_names.get(b.instance_id) if b.instance_id else "All servers",
                    "global": b.instance_id is None,
                    "reason": b.reason,
                    "expires_at": str(b.expires_at) if b.expires_at else None,
                    "permanent": b.expires_at is None,
                    "owner": b.user_id == u.id,
                    "via": _match_reasons(banned_user, user=u),
                }
                for b, banned_user in bans_by_user.get(u.id, [])
            ],
        }
        for u in users
    ]


@router.post("/users/{user_id}/nickname")
async def admin_change_nickname(user_id: int, body: dict):
    new_nick = (body.get("display_name") or "").strip()
    if not new_nick:
        return JSONResponse(content={"error": "Nickname is required"}, status_code=400)
    if len(new_nick) > 255:
        return JSONResponse(content={"error": "Nickname too long (max 255 characters)"}, status_code=400)
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)
        dup = await session.execute(select(UserModel).where(UserModel.display_name == new_nick))
        if dup.scalar_one_or_none() is not None:
            return JSONResponse(content={"error": "Nickname already in use"}, status_code=409)
        old_nick = user.display_name
        user.display_name = new_nick
        auto_login = f"{old_nick}@yggdrasil"
        if user.username == auto_login:
            new_login = f"{new_nick}@yggdrasil"
            dup_login = await session.execute(select(UserModel).where(UserModel.username == new_login))
            if dup_login.scalar_one_or_none() is None:
                user.username = new_login
        await session.execute(
            update(ServerSessionModel).where(ServerSessionModel.display_name == old_nick)
            .values(display_name=new_nick)
        )
        await session.commit()
    await sync_all_whitelists()
    await sync_all_bans()
    return {"status": "updated", "display_name": new_nick}


@router.post("/users/{user_id}/email")
async def admin_change_email(user_id: int, body: dict):
    new_email = (body.get("email") or "").strip()
    if not new_email:
        return JSONResponse(content={"error": "Email is required"}, status_code=400)
    if len(new_email) > 255:
        return JSONResponse(content={"error": "Email too long (max 255 characters)"}, status_code=400)
    if "@" not in new_email or "." not in new_email.split("@")[-1]:
        return JSONResponse(content={"error": "Invalid email address"}, status_code=400)
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)
        dup = await session.execute(select(UserModel).where(
            (UserModel.email == new_email) | (UserModel.username == new_email)
        ))
        dup_user = dup.scalar_one_or_none()
        if dup_user is not None and dup_user.id != user.id:
            return JSONResponse(content={"error": "Email already in use"}, status_code=409)
        old_email = user.email
        user.email = new_email
        if old_email and user.username == old_email:
            user.username = new_email
        await session.commit()
    await sync_all_bans()
    return {"status": "updated", "email": new_email}


@router.post("/users/{user_id}/password")
async def admin_change_password(user_id: int, body: dict):
    new_password = body.get("password") or ""
    if len(new_password) < 8:
        return JSONResponse(content={"error": "Password too short (min 8 characters)"}, status_code=400)
    if len(new_password) > 1024:
        return JSONResponse(content={"error": "Password too long (max 1024 characters)"}, status_code=400)
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)
        user.password_hash = hash_password(new_password)
        user.access_token_hash = ""
        user.client_token_hash = ""
        user.token_expires_at = None
        await session.commit()
    return {"status": "updated"}


MAX_SKIN_SIZE = 10 * 1024 * 1024
ALLOWED_SKIN_TYPES = {"image/png", "image/jpeg"}


def _validate_skin_model(model: str) -> str:
    model = (model or "classic").strip().lower()
    return model if model in ("classic", "slim") else "classic"


@router.post("/users/{user_id}/skin")
async def admin_upload_skin(user_id: int, file: UploadFile = File(...), model: str = Form("classic")):
    data = await file.read()
    if len(data) > MAX_SKIN_SIZE:
        return JSONResponse(content={"error": "Skin file too large (max 10 MB)"}, status_code=400)
    ctype = (file.content_type or "").lower()
    if ctype not in ALLOWED_SKIN_TYPES:
        return JSONResponse(content={"error": "Skin must be a PNG or JPEG image"}, status_code=400)
    skin_model = _validate_skin_model(model)
    import base64
    encoded = base64.b64encode(data).decode("ascii")
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)
        user.skin = encoded
        user.skin_model = skin_model
        await session.commit()
    return {"status": "updated", "has_skin": True, "model": skin_model}


@router.delete("/users/{user_id}/skin")
async def admin_remove_skin(user_id: int):
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)
        user.skin = ""
        await session.commit()
    return {"status": "removed"}


@router.post("/users/{user_id}/ban")
async def admin_ban_user(user_id: int, body: dict):
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)

    raw_ids = body.get("instance_ids")
    if raw_ids is None:
        single = (body.get("instance_id") or "").strip() or None
        raw_ids = [single] if single else []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return JSONResponse(content={"error": "Invalid instance_ids"}, status_code=400)

    instance_ids = []
    seen = set()
    for item in raw_ids:
        iid = (str(item) or "").strip()
        if not iid or iid in seen:
            continue
        seen.add(iid)
        inst = await get_instance(iid)
        if inst is None:
            return JSONResponse(content={"error": f"Instance not found: {iid}"}, status_code=404)
        instance_ids.append(iid)

    reason = (body.get("reason") or "").strip()
    duration = body.get("duration")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return JSONResponse(content={"error": "Invalid duration"}, status_code=400)
        if duration < 0:
            return JSONResponse(content={"error": "Invalid duration"}, status_code=400)

    if not instance_ids:
        ban_id = await create_ban(user_id, None, reason, duration)
    else:
        ban_id = None
        for iid in instance_ids:
            ban_id = await create_ban(user_id, iid, reason, duration)
    await sync_all_bans()
    return {"status": "banned", "ban_id": ban_id, "instance_ids": instance_ids or [None]}


@router.post("/users/{user_id}/unban")
async def admin_unban_user(user_id: int, body: dict):
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)
    ban_id = body.get("ban_id")
    if ban_id is not None:
        try:
            ban_id = int(ban_id)
        except (TypeError, ValueError):
            return JSONResponse(content={"error": "Invalid ban id"}, status_code=400)
        removed = await remove_ban_by_id(user_id, ban_id)
    else:
        instance_id = (body.get("instance_id") or "").strip() or None
        removed = await remove_ban(user_id, instance_id)
    await sync_all_bans()
    return {"status": "unbanned", "removed": removed}


@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: int):
    async with get_session() as session:
        user = await session.get(UserModel, user_id)
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)
        await session.execute(delete(UserBanModel).where(UserBanModel.user_id == user_id))
        await session.execute(delete(ServerSessionModel).where(ServerSessionModel.display_name == user.display_name))
        await session.delete(user)
        await session.commit()
    await sync_all_whitelists()
    await sync_all_bans()
    return {"status": "deleted"}
