import json
import asyncio
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import select

from server.config import SERVER_DIR
from server.database import get_session, init_db
from server.models import ProjectModel, ProjectNewsModel, ModpackModel, InstanceModel
from server.mc.status import probe
from server.web.auth import require_admin


projects_router = APIRouter()
news_router = APIRouter()
launcher_router = APIRouter()

PROJECTS_STORAGE = SERVER_DIR / "projects"

_VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _modpack_dir(project_id: str, modpack_id: str) -> Path:
    return PROJECTS_STORAGE / project_id / "modpacks" / modpack_id


def _get_modpack_file_count(project_id: str, modpack_id: str) -> int:
    mp_dir = _modpack_dir(project_id, modpack_id)
    if not mp_dir.exists():
        return 0
    return len([f for f in mp_dir.rglob("*") if f.is_file() and f.name != "files.json"])


async def _modpack_model_to_dict(m: ModpackModel) -> dict:
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
        "file_count": _get_modpack_file_count(m.project_id, m.id),
    }


async def _list_modpacks(project_id: str) -> list:
    async with get_session() as session:
        stmt = select(ModpackModel).where(
            ModpackModel.project_id == project_id
        ).order_by(ModpackModel.name)
        result = await session.execute(stmt)
        modpacks = result.scalars().all()
        return [await _modpack_model_to_dict(m) for m in modpacks]


async def _project_to_dict(p: ProjectModel) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "icon": p.icon,
        "logo_url": p.logo_url,
        "background_url": p.background_url,
        "primary_color": p.primary_color,
        "accent_color": p.accent_color,
        "window_title": p.window_title,
        "brand_name": p.brand_name or p.name,
    }


async def _news_to_dict(n: ProjectNewsModel) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "important": n.important,
        "created_at": str(n.created_at),
    }


# ── Projects ──

@projects_router.get("")
async def list_projects():
    async with get_session() as session:
        stmt = select(ProjectModel).order_by(ProjectModel.name)
        result = await session.execute(stmt)
        projects = result.scalars().all()
        output = []
        for p in projects:
            d = await _project_to_dict(p)
            d["modpacks"] = await _list_modpacks(p.id)
            output.append(d)
        return output


@projects_router.get("/{project_id}")
async def get_project(project_id: str):
    async with get_session() as session:
        project = await session.get(ProjectModel, project_id)
        if not project:
            return JSONResponse(content={"error": "Project not found"}, status_code=404)
        d = await _project_to_dict(project)
        d["modpacks"] = await _list_modpacks(project_id)
        return d


@projects_router.post("", dependencies=[Depends(require_admin)])
async def create_project(body: dict):
    pid = body.get("id", "").strip()
    if not pid:
        return JSONResponse(content={"error": "Project ID required"}, status_code=400)
    if not _VALID_ID.match(pid):
        return JSONResponse(content={"error": "Invalid Project ID (alphanumeric, hyphens, underscores only)"}, status_code=400)
    async with get_session() as session:
        existing = await session.get(ProjectModel, pid)
        if existing:
            return JSONResponse(content={"error": "Project exists"}, status_code=409)
        project = ProjectModel(
            id=pid,
            name=body.get("name", pid),
            description=body.get("description", ""),
            icon=body.get("icon", ""),
            logo_url=body.get("logo_url", ""),
            background_url=body.get("background_url", ""),
            primary_color=body.get("primary_color", "#6c63ff"),
            accent_color=body.get("accent_color", ""),
            window_title=body.get("window_title", ""),
            brand_name=body.get("brand_name", ""),
        )
        session.add(project)
        await session.commit()
        return await _project_to_dict(project)


@projects_router.delete("/{project_id}", dependencies=[Depends(require_admin)])
async def delete_project(project_id: str):
    if not _VALID_ID.match(project_id):
        return JSONResponse(content={"error": "Invalid Project ID"}, status_code=400)
    async with get_session() as session:
        project = await session.get(ProjectModel, project_id)
        if not project:
            return JSONResponse(content={"error": "Not found"}, status_code=404)
        storage = PROJECTS_STORAGE / project_id
        if storage.exists():
            shutil.rmtree(storage, ignore_errors=True)
        await session.delete(project)
        await session.commit()
        return {"status": "deleted"}


@projects_router.patch("/{project_id}", dependencies=[Depends(require_admin)])
async def update_project(project_id: str, body: dict):
    if not _VALID_ID.match(project_id):
        return JSONResponse(content={"error": "Invalid Project ID"}, status_code=400)
    async with get_session() as session:
        project = await session.get(ProjectModel, project_id)
        if not project:
            return JSONResponse(content={"error": "Not found"}, status_code=404)
        for key in ("name", "description", "icon",
                    "logo_url", "background_url", "primary_color",
                    "accent_color", "window_title", "brand_name"):
            if key in body:
                setattr(project, key, body[key])
        await session.commit()
        return await _project_to_dict(project)


# ── Project News ──

@news_router.get("/{project_id}/news")
async def list_news(project_id: str):
    async with get_session() as session:
        project = await session.get(ProjectModel, project_id)
        if not project:
            return JSONResponse(content={"error": "Project not found"}, status_code=404)
        stmt = select(ProjectNewsModel).where(
            ProjectNewsModel.project_id == project_id
        ).order_by(ProjectNewsModel.created_at.desc())
        result = await session.execute(stmt)
        news = result.scalars().all()
        return [await _news_to_dict(n) for n in news]


@news_router.post("/{project_id}/news", dependencies=[Depends(require_admin)])
async def create_news(project_id: str, body: dict):
    async with get_session() as session:
        project = await session.get(ProjectModel, project_id)
        if not project:
            return JSONResponse(content={"error": "Project not found"}, status_code=404)
        entry = ProjectNewsModel(
            project_id=project_id,
            title=body.get("title", ""),
            content=body.get("content", ""),
            important=body.get("important", False),
        )
        session.add(entry)
        await session.commit()
        return await _news_to_dict(entry)


@news_router.delete("/{project_id}/news/{news_id}", dependencies=[Depends(require_admin)])
async def delete_news(project_id: str, news_id: int):
    async with get_session() as session:
        entry = await session.get(ProjectNewsModel, news_id)
        if not entry or entry.project_id != project_id:
            return JSONResponse(content={"error": "Not found"}, status_code=404)
        await session.delete(entry)
        await session.commit()
        return {"status": "deleted"}


# ── Launcher Sync ──

def _server_address(inst: InstanceModel) -> tuple:
    host = "127.0.0.1"
    port = 25565
    props = {}
    props_path = Path(inst.server_dir) / "server.properties"
    if props_path.exists():
        for line in props_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                props[key.strip()] = val.strip()
    try:
        port = int(props.get("server-port", "25565"))
    except ValueError:
        pass
    ip = props.get("server-ip", "").strip()
    if ip:
        host = ip
    else:
        parsed = urlparse(inst.api_url)
        if parsed.hostname:
            host = parsed.hostname
    return host, port


@launcher_router.get("/projects/{project_id}/servers")
async def launcher_project_servers(project_id: str):
    from server.mc.registry import get_manager_sync
    from server.mc.pidfile import is_running as pid_running

    async with get_session() as session:
        stmt = select(InstanceModel).where(InstanceModel.project_id == project_id)
        result = await session.execute(stmt)
        instances = result.scalars().all()
        mstmt = select(ModpackModel).where(ModpackModel.project_id == project_id)
        mres = await session.execute(mstmt)
        modpacks = {m.id: m.name for m in mres.scalars().all()}

    entries = []
    tasks = []
    for inst in instances:
        if not inst.enabled:
            continue
        host, port = _server_address(inst)
        mgr = get_manager_sync(inst)
        running = mgr.is_running() or pid_running(inst.id)
        entries.append((inst, host, port, running))
        if running:
            tasks.append(asyncio.to_thread(probe, host, port, 2.0))
        else:
            tasks.append(asyncio.to_thread(_offline_status))

    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    servers = []
    for (inst, host, port, running), status in zip(entries, results):
        if isinstance(status, Exception):
            status = {"online": False}
        servers.append({
            "id": inst.id,
            "name": inst.name,
            "version": inst.version or "",
            "modpack_id": inst.modpack_id or "",
            "modpack_name": modpacks.get(inst.modpack_id, ""),
            "running": running,
            "address": host,
            "port": port,
            **status,
        })
    return {"items": servers}


def _offline_status() -> dict:
    return {"online": False}


@launcher_router.get("/bans/{uuid}")
async def launcher_player_bans(uuid: str):
    from server.mc.bans import find_active_bans, _match_reasons

    from server.database import get_session
    from server.models import InstanceModel, UserModel

    clean = uuid.replace("-", "").lower()
    async with get_session() as session:
        user = (await session.execute(
            select(UserModel).where(UserModel.uuid == clean)
        )).scalar_one_or_none()
        if user is None:
            return JSONResponse(content={"error": "User not found"}, status_code=404)

    rows = await find_active_bans(user=user)
    instance_ids = [ban.instance_id for ban, _ in rows if ban.instance_id]
    server_names = {}
    if instance_ids:
        async with get_session() as session:
            inst_stmt = select(InstanceModel.id, InstanceModel.name).where(
                InstanceModel.id.in_(instance_ids)
            )
            rows_i = (await session.execute(inst_stmt)).all()
            server_names = dict(rows_i)

    global_ban = None
    server_bans = []
    for ban, banned_user in rows:
        entry = {
            "instance_id": ban.instance_id or "",
            "reason": ban.reason or "Banned",
            "expires_at": str(ban.expires_at) if ban.expires_at else "",
            "created_at": str(ban.created_at) if ban.created_at else "",
            "via": _match_reasons(banned_user, user=user),
        }
        if ban.instance_id is None:
            global_ban = entry
        else:
            entry["server_name"] = server_names.get(ban.instance_id, ban.instance_id)
            server_bans.append(entry)

    return {
        "uuid": user.uuid,
        "banned": bool(global_ban or server_bans),
        "global": global_ban,
        "servers": server_bans,
    }


@launcher_router.get("/sync/{project_id}")
async def launcher_sync_project(project_id: str):
    async with get_session() as session:
        p = await session.get(ProjectModel, project_id)
        if not p:
            return JSONResponse(content={"error": "Project not found"}, status_code=404)

        nstmt = select(ProjectNewsModel).where(
            ProjectNewsModel.project_id == p.id
        ).order_by(ProjectNewsModel.created_at.desc()).limit(10)
        nresult = await session.execute(nstmt)
        news_list = nresult.scalars().all()

        return {
            **await _project_to_dict(p),
            "modpacks": await _list_modpacks(project_id),
            "news": [await _news_to_dict(n) for n in news_list],
        }


@launcher_router.get("/projects/{project_id}/modpacks/{modpack_id}")
async def launcher_get_modpack(project_id: str, modpack_id: str):
    if not (_VALID_ID.match(project_id) and _VALID_ID.match(modpack_id)):
        return JSONResponse(content={"error": "Invalid project or modpack id"}, status_code=403)
    async with get_session() as session:
        m = await session.get(ModpackModel, (modpack_id, project_id))
        if not m:
            return JSONResponse(content={"error": "Modpack not found"}, status_code=404)
        return await _modpack_model_to_dict(m)


@launcher_router.get("/projects/{project_id}/modpacks/{modpack_id}/files")
async def launcher_list_modpack_files(project_id: str, modpack_id: str):
    if not (_VALID_ID.match(project_id) and _VALID_ID.match(modpack_id)):
        return JSONResponse(content={"error": "Invalid project or modpack id"}, status_code=403)
    mp_dir = _modpack_dir(project_id, modpack_id)
    if not mp_dir.exists():
        return JSONResponse(content={"error": "Modpack not found"}, status_code=404)
    index_path = mp_dir / "files.json"
    hash_index = {}
    if index_path.exists():
        hash_index = json.loads(index_path.read_text(encoding="utf-8"))
    items = []
    for entry in sorted(mp_dir.rglob("*"), key=lambda e: (not e.is_file(), str(e).lower())):
        if entry.is_file() and entry.name != "files.json":
            rel = entry.relative_to(mp_dir).as_posix()
            stat = entry.stat()
            items.append({
                "name": rel,
                "is_dir": False,
                "size": stat.st_size,
                "sha256": hash_index.get(rel, ""),
            })
    return {"items": items}


@launcher_router.get("/projects/{project_id}/modpacks/{modpack_id}/download/{filename:path}")
async def launcher_download_modpack_file(project_id: str, modpack_id: str, filename: str):
    if not (_VALID_ID.match(project_id) and _VALID_ID.match(modpack_id)):
        return JSONResponse(content={"error": "Invalid project or modpack id"}, status_code=403)
    mp_dir = _modpack_dir(project_id, modpack_id)
    target = (mp_dir / filename).resolve()
    if not _is_within(mp_dir, target):
        return JSONResponse(content={"error": "Access denied"}, status_code=403)
    if not target.exists() or not target.is_file():
        return JSONResponse(content={"error": "File not found"}, status_code=404)
    return FileResponse(
        path=str(target), filename=filename,
        media_type="application/octet-stream",
    )


@launcher_router.get("/injector")
async def launcher_injector():
    """Serve the authlib-injector JAR to launcher clients.

    Downloads the JAR on first request (cached in the server dir).
    """
    from server.mc.injector import InjectorManager
    mgr = InjectorManager(SERVER_DIR / "injector")
    if not mgr.is_downloaded():
        try:
            mgr.download()
        except Exception as e:
            return JSONResponse(
                content={"error": f"Failed to download authlib-injector: {e}"},
                status_code=500,
            )
    jar = mgr.save_dir / "authlib-injector.jar"
    return FileResponse(
        path=str(jar),
        filename="authlib-injector.jar",
        media_type="application/java-archive",
    )
