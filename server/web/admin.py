import threading
import re
import os
import stat
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
from typing import get_type_hints, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, Request, File, Form, UploadFile, Body
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.responses import FileResponse
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
    "java_executable_path": {"label": "Java Executable", "description": "Java binary for this server (default: java from PATH)"},
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
    options = [{"value": "java", "label": "Default (java from PATH)"}]
    seen = {"java"}
    for jr in runtimes:
        if jr.path in seen:
            continue
        seen.add(jr.path)
        label = "Java " + str(jr.major_version)
        if jr.vendor and jr.vendor != "Unknown":
            label += " \u00b7 " + jr.vendor
        if jr.version:
            label += " \u00b7 " + jr.version
        label += " \u00b7 " + jr.path
        options.append({"value": jr.path, "label": label})
    return options


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


_PLAYER_LINE_RE = re.compile(
    r"There are (\d+) of a max of (\d+) players online", re.IGNORECASE
)


def _parse_players_from_output(mgr) -> Optional[dict]:
    if mgr is None:
        return None
    lines = mgr.get_output(500)
    for line in reversed(lines):
        m = _PLAYER_LINE_RE.search(line)
        if m:
            return {"online": int(m.group(1)), "max": int(m.group(2))}
    return None


def _instance_to_api(inst: InstanceModel) -> dict:
    mgr = get_manager_sync(inst)
    running = mgr is not None and mgr.is_running()
    result = instance_model_to_dict(inst)
    result["running"] = running
    result["stopping"] = bool(mgr and mgr.is_stopping())
    result["starting"] = bool(mgr and mgr.is_starting())
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


def _get_overview(inst: InstanceModel) -> dict:
    import psutil
    import platform

    mgr = get_manager_sync(inst)
    running = mgr is not None and mgr.is_running()

    cfg = instance_model_to_dict(inst)
    for key in ("created_at", "last_error"):
        cfg.pop(key, None)

    try:
        refresh = int(ServerConfig.load().stats_refresh_seconds)
    except Exception:
        refresh = 2
    refresh = max(1, min(60, refresh))

    d = {
        "running": running,
        "stopping": bool(mgr and mgr.is_stopping()),
        "starting": bool(mgr and mgr.is_starting()),
        "last_error": mgr.last_error if mgr else None,
        "players": _parse_players_from_output(mgr),
        "log_lines": len(mgr.get_output(0)) if mgr else 0,
        "last_output": (mgr.get_output(1)[-1] if mgr and mgr.get_output(1) else None),
        "config": cfg,
        "refresh_interval": refresh,
        "system": {},
        "process": None,
    }

    try:
        vm = psutil.virtual_memory()
        boot = psutil.boot_time()
        d["system"] = {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "kernel": platform.version(),
            "python": platform.python_version(),
            "boot_time": boot,
            "cpu_count": psutil.cpu_count(logical=True),
            "cpu_physical": psutil.cpu_count(logical=False) or 0,
            "cpu_percent": round(psutil.cpu_percent(interval=0.15), 1),
            "memory_total_mb": round(vm.total / 1024 / 1024, 1),
            "memory_used_mb": round(vm.used / 1024 / 1024, 1),
            "memory_available_mb": round(vm.available / 1024 / 1024, 1),
            "memory_percent": round(vm.percent, 1),
        }
        server_dir = inst.server_dir or str(Path.cwd())
        du = psutil.disk_usage(server_dir)
        d["system"]["disk_total_gb"] = round(du.total / 1e9, 2)
        d["system"]["disk_used_gb"] = round(du.used / 1e9, 2)
        d["system"]["disk_free_gb"] = round(du.free / 1e9, 2)
    except Exception:
        pass

    if running and mgr and mgr.process:
        try:
            p = psutil.Process(mgr.process.pid)
            with p.oneshot():
                mem = p.memory_info()
                cpu_times = p.cpu_times()
                d["process"] = {
                    "pid": p.pid,
                    "status": p.status(),
                    "create_time": p.create_time(),
                    "uptime_seconds": int(time.time() - p.create_time()),
                    "cpu_percent": round(p.cpu_percent(interval=0.15), 1),
                    "cpu_time_user": round(cpu_times.user, 2),
                    "cpu_time_system": round(cpu_times.system, 2),
                    "memory_rss_mb": round(mem.rss / 1024 / 1024, 1),
                    "memory_vms_mb": round(mem.vms / 1024 / 1024, 1),
                    "memory_percent": round(p.memory_percent(), 2),
                    "num_threads": p.num_threads(),
                    "username": p.username(),
                    "executable": p.exe(),
                    "cwd": p.cwd(),
                }
                try:
                    d["process"]["connections"] = len(p.connections())
                except Exception:
                    pass
                try:
                    d["process"]["open_files"] = len(p.open_files())
                except Exception:
                    pass
        except Exception:
            pass

    return d


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


@router.get("/instances/{instance_id}/overview")
async def instance_overview(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    return _get_overview(inst)


@router.post("/instances/{instance_id}/start")
async def instance_start(instance_id: str):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
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
    if mgr.is_stopping():
        return JSONResponse(content={"error": "Server is already stopping"}, status_code=400)
    if not mgr.is_running():
        return JSONResponse(content={"error": "Not running"}, status_code=400)
    mgr.request_stop()
    return {"status": "stopping", "id": instance_id}


@router.post("/instances/{instance_id}/restart")
async def instance_restart(instance_id: str):
    mgr = await get_manager(instance_id)
    if mgr is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if mgr.is_stopping():
        return JSONResponse(content={"error": "Server is already stopping"}, status_code=400)
    if not mgr.is_running():
        return JSONResponse(content={"error": "Not running"}, status_code=400)
    if mgr.request_restart():
        return {"status": "restarting", "id": instance_id}
    err = mgr.last_error or "Restart failed"
    return JSONResponse(content={"error": err}, status_code=500)


@router.post("/instances/{instance_id}/reload")
async def instance_reload(instance_id: str):
    mgr = await get_manager(instance_id)
    if mgr is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    if mgr.is_stopping():
        return JSONResponse(content={"error": "Server is stopping"}, status_code=400)
    if not mgr.is_running():
        return JSONResponse(content={"error": "Not running"}, status_code=400)
    if mgr.reload():
        return {"status": "reloaded", "id": instance_id}
    return JSONResponse(content={"error": "Reload failed"}, status_code=500)


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
    "stats_refresh_seconds": {"label": "Overview Refresh Rate", "description": "How often the server overview auto-refreshes (seconds, 1-60)"},
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
        _make_writable(target)
        target.write_text(content, encoding="utf-8")
        return {"status": "saved", "path": str(target)}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/instances/{instance_id}/files/upload")
async def upload_file(instance_id: str, file: UploadFile = File(...), path: str = Form(""), relpath: str = Form("")):
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
    rel = (relpath or file.filename or "").replace("\\", "/")
    file_path = (target / rel).resolve()
    if not str(file_path).startswith(str(base)):
        return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
    try:
        content = await file.read()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        _make_writable(file_path)
        file_path.write_bytes(content)
        return {"status": "uploaded", "path": str(file_path), "size": len(content)}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/instances/{instance_id}/files/download")
async def download_file(instance_id: str, path: str = ""):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    base = Path(inst.server_dir).resolve()
    target = (base / path).resolve()
    if not str(target).startswith(str(base)):
        return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
    if not target.exists():
        return JSONResponse(content={"error": "File or directory not found"}, status_code=404)

    from starlette.responses import FileResponse

    if target.is_file():
        return FileResponse(target, filename=target.name)

    # Directory -> build a ZIP archive on disk and stream it
    import os
    import tempfile
    import zipfile

    zip_name = (target.name if target != base else base.name) or "server"
    fd, tmp_path = tempfile.mkstemp(prefix="uroboros_dl_", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(target):
                for name in files:
                    fpath = Path(root) / name
                    arc = str(fpath.relative_to(base))
                    try:
                        zf.write(fpath, arc)
                    except OSError:
                        continue
        return FileResponse(
            tmp_path,
            filename=zip_name + ".zip",
            background=lambda: os.remove(tmp_path),
        )
    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ── Files: advanced operations (instances) ──

async def _instance_base_dir(instance_id: str) -> Path | None:
    inst = await get_instance(instance_id)
    if inst is None:
        return None
    return Path(inst.server_dir).resolve()


def _unique_dest(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _make_writable(path: Path):
    if not path.exists():
        return
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    except OSError:
        pass


def _clear_readonly(path: Path):
    if path.is_dir():
        for entry in path.rglob("*"):
            _make_writable(entry)
    else:
        _make_writable(path)


def _remove_path(path: Path):
    _clear_readonly(path)
    if path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


@router.delete("/instances/{instance_id}/files")
async def delete_instance_files(instance_id: str, body: dict):
    raw = body.get("paths")
    if isinstance(raw, list):
        paths = raw
    else:
        single = (body.get("path") or "").strip()
        paths = [single] if single else []
    if not paths:
        return JSONResponse(content={"error": "path or paths is required"}, status_code=400)
    deleted = 0
    errors = []
    for p in paths:
        target = await _resolve_file_path(instance_id, p)
        if target is None or not target.exists():
            errors.append({"path": p, "error": "not found or access denied"})
            continue
        try:
            _remove_path(target)
            deleted += 1
        except Exception as e:
            errors.append({"path": p, "error": str(e)})
    return {"status": "deleted", "deleted": deleted, "errors": errors}


@router.post("/instances/{instance_id}/files/mkdir")
async def create_instance_folder(instance_id: str, body: dict):
    base = await _instance_base_dir(instance_id)
    if base is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    name = (body.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return JSONResponse(content={"error": "Invalid folder name"}, status_code=400)
    rel = (body.get("path") or "").strip().strip("/")
    target = await _resolve_file_path(instance_id, f"{rel}/{name}" if rel else name)
    if target is None:
        return JSONResponse(content={"error": "Access denied"}, status_code=403)
    if target.exists():
        return JSONResponse(content={"error": "Already exists"}, status_code=409)
    try:
        target.mkdir(parents=True, exist_ok=False)
        return {"status": "created", "count": 1, "path": (rel + "/" + name) if rel else name}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/instances/{instance_id}/files/rename")
async def rename_instance_file(instance_id: str, body: dict):
    path = (body.get("path") or "").strip().strip("/")
    new_name = (body.get("new_name") or "").strip()
    if not path:
        return JSONResponse(content={"error": "path is required"}, status_code=400)
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        return JSONResponse(content={"error": "Invalid name"}, status_code=400)
    target = await _resolve_file_path(instance_id, path)
    if target is None or not target.exists():
        return JSONResponse(content={"error": "Not found or access denied"}, status_code=404)
    dest = target.parent / new_name
    if dest.exists():
        return JSONResponse(content={"error": "Target already exists"}, status_code=409)
    try:
        target.rename(dest)
        return {"status": "renamed", "count": 1, "path": path, "new_name": new_name}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def _batch_move_copy(instance_id: str, body: dict, action: str):
    base = await _instance_base_dir(instance_id)
    if base is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths:
        return JSONResponse(content={"error": "paths is required"}, status_code=400)
    dest = (body.get("destination") or "").strip().strip("/")
    dest_dir = await _resolve_file_path(instance_id, dest)
    if dest_dir is None or not dest_dir.is_dir():
        return JSONResponse(content={"error": "Destination directory not found"}, status_code=404)
    done = 0
    errors = []
    for p in paths:
        src = await _resolve_file_path(instance_id, p)
        if src is None or not src.exists():
            errors.append({"path": p, "error": "not found or access denied"})
            continue
        if str(src.resolve()) == str(dest_dir.resolve()) or str(dest_dir.resolve()).startswith(str(src.resolve()) + os.sep):
            errors.append({"path": p, "error": "cannot move/copy into itself"})
            continue
        target = _unique_dest(dest_dir, src.name)
        try:
            if action == "move":
                shutil.move(str(src), str(target))
            elif src.is_dir():
                shutil.copytree(str(src), str(target))
            else:
                shutil.copy2(str(src), str(target))
            done += 1
        except Exception as e:
            errors.append({"path": p, "error": str(e)})
    return {"status": action, "count": done, "errors": errors}


@router.post("/instances/{instance_id}/files/move")
async def move_instance_files(instance_id: str, body: dict):
    return await _batch_move_copy(instance_id, body, "move")


@router.post("/instances/{instance_id}/files/copy")
async def copy_instance_files(instance_id: str, body: dict):
    return await _batch_move_copy(instance_id, body, "copy")


@router.post("/instances/{instance_id}/files/zip")
async def zip_instance_files(instance_id: str, body: dict):
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths:
        return JSONResponse(content={"error": "paths is required"}, status_code=400)
    base = await _instance_base_dir(instance_id)
    if base is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    import tempfile
    import zipfile
    fd, tmp_path = tempfile.mkstemp(prefix="uroboros_zip_", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                src = await _resolve_file_path(instance_id, p)
                if src is None or not src.exists():
                    continue
                if src.is_file():
                    zf.write(src, p.lstrip("/"))
                else:
                    for root, dirs, files in os.walk(src):
                        for name in files:
                            fpath = Path(root) / name
                            arc = str(fpath.relative_to(base)).replace("\\", "/")
                            try:
                                zf.write(fpath, arc)
                            except OSError:
                                continue
        return FileResponse(tmp_path, filename="selection.zip", background=lambda: os.remove(tmp_path))
    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/instances/{instance_id}/files/upload-batch")
async def upload_instance_files_batch(instance_id: str, request: Request, path: str = Form("")):
    inst = await get_instance(instance_id)
    if inst is None:
        return JSONResponse(content={"error": "Instance not found"}, status_code=404)
    base = Path(inst.server_dir).resolve()
    target_dir = base
    if path:
        target_dir = (base / path).resolve()
        if not str(target_dir).startswith(str(base)):
            return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
    target_dir.mkdir(parents=True, exist_ok=True)
    form = await request.form()
    files = form.getlist("file")
    relpaths = form.getlist("relpath")
    uploaded = 0
    errors = []
    for i, f in enumerate(files):
        rel = (relpaths[i] if i < len(relpaths) and relpaths[i] else (f.filename or "")).replace("\\", "/").lstrip("/")
        file_path = (target_dir / rel).resolve()
        if not str(file_path).startswith(str(base)):
            errors.append({"relpath": rel, "error": "path traversal denied"})
            continue
        try:
            content = await f.read()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            _make_writable(file_path)
            file_path.write_bytes(content)
            uploaded += 1
        except Exception as e:
            errors.append({"relpath": rel, "error": str(e)})
    return {"status": "uploaded", "uploaded": uploaded, "errors": errors}


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
        _remove_path(mp_dir)
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
    if target is None or not target.exists():
        return JSONResponse(content={"error": "File or directory not found"}, status_code=404)
    from starlette.responses import FileResponse

    if target.is_file():
        return FileResponse(target, filename=target.name)

    # Directory -> build a ZIP archive on disk and stream it
    import os
    import tempfile
    import zipfile

    mp_dir = _modpack_dir(project_id, modpack_id)
    zip_name = (target.name if target != mp_dir else mp_dir.name) or "modpack"
    fd, tmp_path = tempfile.mkstemp(prefix="uroboros_dl_", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(target):
                for name in files:
                    fpath = Path(root) / name
                    arc = str(fpath.relative_to(mp_dir).as_posix())
                    try:
                        zf.write(fpath, arc)
                    except OSError:
                        continue
        return FileResponse(
            tmp_path,
            filename=zip_name + ".zip",
            background=lambda: os.remove(tmp_path),
        )
    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JSONResponse(content={"error": str(e)}, status_code=500)


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
                _remove_path(child)
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
                    _make_writable(dest)
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
    relpath: str = Form(""),
):
    mp_dir = _modpack_dir(project_id, modpack_id)
    mp_dir.mkdir(parents=True, exist_ok=True)
    base = mp_dir.resolve()
    target_dir = mp_dir
    if path:
        resolved = await _resolve_mp_path(project_id, modpack_id, path)
        if resolved is None:
            return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
        if not resolved.exists():
            resolved.mkdir(parents=True, exist_ok=True)
        target_dir = resolved
    rel = (relpath or file.filename or "").replace("\\", "/")
    file_path = (target_dir / rel).resolve()
    if not str(file_path).startswith(str(base)):
        return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
    try:
        content = await file.read()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        _make_writable(file_path)
        file_path.write_bytes(content)
        _update_files_hash(project_id, modpack_id)
        return {"status": "uploaded", "path": str(file_path), "size": len(content)}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.delete("/projects/{project_id}/modpacks/{modpack_id}/files")
async def delete_modpack_file(project_id: str, modpack_id: str, path: str = "", body: dict | None = Body(default=None)):
    if body and isinstance(body.get("paths"), list):
        raw = body["paths"]
    elif path:
        raw = [path]
    elif body and body.get("path"):
        raw = [body["path"]]
    else:
        raw = []
    if not raw:
        return JSONResponse(content={"error": "path or paths is required"}, status_code=400)
    deleted = 0
    errors = []
    for p in raw:
        target = await _resolve_mp_path(project_id, modpack_id, p)
        if target is None or not target.exists():
            errors.append({"path": p, "error": "not found or access denied"})
            continue
        try:
            _remove_path(target)
            deleted += 1
        except Exception as e:
            errors.append({"path": p, "error": str(e)})
    if deleted or not errors:
        _update_files_hash(project_id, modpack_id)
    return {"status": "deleted", "deleted": deleted, "errors": errors}


# ── Modpack file manager: advanced operations ──


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/mkdir")
async def create_modpack_folder(project_id: str, modpack_id: str, body: dict):
    name = (body.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return JSONResponse(content={"error": "Invalid folder name"}, status_code=400)
    rel = (body.get("path") or "").strip().strip("/")
    target = await _resolve_mp_path(project_id, modpack_id, f"{rel}/{name}" if rel else name)
    if target is None:
        return JSONResponse(content={"error": "Access denied"}, status_code=403)
    if target.exists():
        return JSONResponse(content={"error": "Already exists"}, status_code=409)
    try:
        target.mkdir(parents=True, exist_ok=False)
        return {"status": "created", "count": 1, "path": (rel + "/" + name) if rel else name}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/rename")
async def rename_modpack_file(project_id: str, modpack_id: str, body: dict):
    path = (body.get("path") or "").strip().strip("/")
    new_name = (body.get("new_name") or "").strip()
    if not path:
        return JSONResponse(content={"error": "path is required"}, status_code=400)
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        return JSONResponse(content={"error": "Invalid name"}, status_code=400)
    target = await _resolve_mp_path(project_id, modpack_id, path)
    if target is None or not target.exists():
        return JSONResponse(content={"error": "Not found or access denied"}, status_code=404)
    dest = target.parent / new_name
    if dest.exists():
        return JSONResponse(content={"error": "Target already exists"}, status_code=409)
    try:
        target.rename(dest)
        _update_files_hash(project_id, modpack_id)
        return {"status": "renamed", "count": 1, "path": path, "new_name": new_name}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def _modpack_batch_move_copy(project_id: str, modpack_id: str, body: dict, action: str):
    mp_dir = _modpack_dir(project_id, modpack_id)
    if not mp_dir.exists():
        return JSONResponse(content={"error": "Modpack not found"}, status_code=404)
    base = mp_dir.resolve()
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths:
        return JSONResponse(content={"error": "paths is required"}, status_code=400)
    dest = (body.get("destination") or "").strip().strip("/")
    dest_dir = await _resolve_mp_path(project_id, modpack_id, dest)
    if dest_dir is None or not dest_dir.is_dir():
        return JSONResponse(content={"error": "Destination directory not found"}, status_code=404)
    done = 0
    errors = []
    for p in paths:
        src = await _resolve_mp_path(project_id, modpack_id, p)
        if src is None or not src.exists():
            errors.append({"path": p, "error": "not found or access denied"})
            continue
        if str(src.resolve()) == str(dest_dir.resolve()) or str(dest_dir.resolve()).startswith(str(src.resolve()) + os.sep):
            errors.append({"path": p, "error": "cannot move/copy into itself"})
            continue
        target = _unique_dest(dest_dir, src.name)
        try:
            if action == "move":
                shutil.move(str(src), str(target))
            elif src.is_dir():
                shutil.copytree(str(src), str(target))
            else:
                shutil.copy2(str(src), str(target))
            done += 1
        except Exception as e:
            errors.append({"path": p, "error": str(e)})
    _update_files_hash(project_id, modpack_id)
    return {"status": action, "count": done, "errors": errors}


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/move")
async def move_modpack_files(project_id: str, modpack_id: str, body: dict):
    return await _modpack_batch_move_copy(project_id, modpack_id, body, "move")


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/copy")
async def copy_modpack_files(project_id: str, modpack_id: str, body: dict):
    return await _modpack_batch_move_copy(project_id, modpack_id, body, "copy")


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/zip")
async def zip_modpack_files(project_id: str, modpack_id: str, body: dict):
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths:
        return JSONResponse(content={"error": "paths is required"}, status_code=400)
    mp_dir = _modpack_dir(project_id, modpack_id)
    if not mp_dir.exists():
        return JSONResponse(content={"error": "Modpack not found"}, status_code=404)
    base = mp_dir.resolve()
    import tempfile
    import zipfile
    fd, tmp_path = tempfile.mkstemp(prefix="uroboros_zip_", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                src = await _resolve_mp_path(project_id, modpack_id, p)
                if src is None or not src.exists():
                    continue
                if src.is_file():
                    zf.write(src, p.lstrip("/"))
                else:
                    for root, dirs, files in os.walk(src):
                        for name in files:
                            fpath = Path(root) / name
                            arc = str(fpath.relative_to(base)).replace("\\", "/")
                            try:
                                zf.write(fpath, arc)
                            except OSError:
                                continue
        return FileResponse(tmp_path, filename="selection.zip", background=lambda: os.remove(tmp_path))
    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/projects/{project_id}/modpacks/{modpack_id}/files/upload-batch")
async def upload_modpack_files_batch(project_id: str, modpack_id: str, request: Request, path: str = Form("")):
    mp_dir = _modpack_dir(project_id, modpack_id)
    mp_dir.mkdir(parents=True, exist_ok=True)
    base = mp_dir.resolve()
    target_dir = mp_dir
    if path:
        resolved = await _resolve_mp_path(project_id, modpack_id, path)
        if resolved is None:
            return JSONResponse(content={"error": "Path traversal denied"}, status_code=403)
        resolved.mkdir(parents=True, exist_ok=True)
        target_dir = resolved
    form = await request.form()
    files = form.getlist("file")
    relpaths = form.getlist("relpath")
    uploaded = 0
    errors = []
    for i, f in enumerate(files):
        rel = (relpaths[i] if i < len(relpaths) and relpaths[i] else (f.filename or "")).replace("\\", "/").lstrip("/")
        file_path = (target_dir / rel).resolve()
        if not str(file_path).startswith(str(base)):
            errors.append({"relpath": rel, "error": "path traversal denied"})
            continue
        try:
            content = await f.read()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            _make_writable(file_path)
            file_path.write_bytes(content)
            uploaded += 1
        except Exception as e:
            errors.append({"relpath": rel, "error": str(e)})
    _update_files_hash(project_id, modpack_id)
    return {"status": "uploaded", "uploaded": uploaded, "errors": errors}


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

_ADMIN_FRAGMENTS = (
    "head", "projects", "servers", "players", "config", "java",
    "modals", "scripts",
)


def _render_admin_page() -> str:
    parts = []
    for name in _ADMIN_FRAGMENTS:
        path = _template_dir / "admin" / f"{name}.html"
        with open(path, "r", encoding="utf-8") as f:
            parts.append(f.read())
    return "\n".join(parts)


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard():
    return HTMLResponse(_render_admin_page())


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
