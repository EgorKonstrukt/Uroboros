import asyncio
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

import aiohttp

from server.config import SERVER_DIR, ServerConfig

PROJECTS_STORAGE = SERVER_DIR / "projects"

MODRINTH_API = "https://api.modrinth.com/v2"
CF_API = "https://api.curseforge.com/v1"


def _modpack_dir(project_id: str, modpack_id: str) -> Path:
    return PROJECTS_STORAGE / project_id / "modpacks" / modpack_id


# ── Format detection ──


def detect_format(extract_dir: Path) -> str | None:
    if (extract_dir / "manifest.json").exists() and (extract_dir / "overrides").is_dir():
        return "curseforge"
    if (extract_dir / "modrinth.index.json").exists():
        return "modrinth"
    return None


# ── CurseForge manifest parsing ──


def parse_cf_manifest(extract_dir: Path) -> dict:
    path = extract_dir / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mc_version = data.get("minecraft", {}).get("version", "")
    loaders = data.get("minecraft", {}).get("modLoaders", [])
    loader = ""
    loader_version = ""
    for l in loaders:
        if l.get("primary"):
            lid = l.get("id", "")
            if "-" in lid:
                loader = lid.split("-")[0]
                loader_version = lid.split("-", 1)[1]
            break
    return {
        "name": data.get("name", ""),
        "version": data.get("version", ""),
        "mc_version": mc_version,
        "loader": loader,
        "loader_version": loader_version,
        "files": data.get("files", []),
        "overrides_dir": extract_dir / "overrides",
    }


# ── Modrinth index parsing ──


def parse_mr_index(extract_dir: Path) -> dict:
    path = extract_dir / "modrinth.index.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    deps = data.get("dependencies", {})
    mc_version = deps.get("minecraft", "")
    loader = ""
    loader_version = ""
    for dep, ver in deps.items():
        if dep != "minecraft":
            loader = dep
            loader_version = ver
    return {
        "name": data.get("name", ""),
        "version": data.get("version", ""),
        "mc_version": mc_version,
        "loader": loader,
        "loader_version": loader_version,
        "files": data.get("files", []),
        "overrides_dir": extract_dir / "overrides",
    }


# ── Modrinth file resolution ──


async def resolve_mr_version(mod_id: str, mc_version: str, loader: str) -> dict | None:
    """Find the best matching version for a Modrinth project."""
    url = f"{MODRINTH_API}/project/{mod_id}/version"
    params = {
        "game_versions": f'["{mc_version}"]',
        "loaders": f'["{loader}"]',
        "featured": "true",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None
                versions = await resp.json()
                if versions:
                    return versions[0]
    except Exception:
        return None
    return None


async def download_mr_file(download_url: str, dest: Path) -> bool:
    """Download a single file from Modrinth."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    return False
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    while True:
                        chunk = await resp.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                return True
    except Exception:
        return False


async def download_modrinth_mod(mod_id: str, mc_version: str, loader: str, dest_dir: Path) -> bool:
    version = await resolve_mr_version(mod_id, mc_version, loader)
    if not version:
        return False
    for file_info in version.get("files", []):
        url = file_info.get("url", "")
        filename = file_info.get("filename", f"{mod_id}.jar")
        if url:
            ok = await download_mr_file(url, dest_dir / filename)
            if ok:
                return True
    return False


# ── CurseForge file resolution ──


async def resolve_cf_file(project_id: int, file_id: int, api_key: str) -> tuple[dict | None, str]:
    """Resolve a CF file to get download URL and filename. Returns (data, error_msg)."""
    url = f"{CF_API}/mods/{project_id}/files/{file_id}"
    headers = {"x-api-key": api_key, "User-Agent": "Uroboros/1.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                body = await resp.text()
                if resp.status == 403:
                    return None, "CF API 403: API key rejected — check your key in Admin > Config > CurseForge API Key"
                if resp.status != 200:
                    return None, f"CF API {resp.status}: {body[:200]}"
                import json
                data = json.loads(body)
                return data.get("data"), ""
    except Exception as e:
        return None, str(e)


async def download_cf_file(download_url: str, dest: Path) -> tuple[bool, str]:
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Uroboros/1.0"}) as session:
            async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return False, f"HTTP {resp.status}: {body[:200]}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    while True:
                        chunk = await resp.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                return True, ""
    except Exception as e:
        return False, str(e)


async def download_curseforge_mod(project_id: int, file_id: int, api_key: str, dest_dir: Path) -> tuple[bool, str]:
    info, err = await resolve_cf_file(project_id, file_id, api_key)
    if err:
        return False, f"resolve: {err}"
    if not info:
        return False, "no data returned"
    download_url = info.get("downloadUrl", "")
    filename = info.get("fileName", f"cf-{project_id}-{file_id}.jar")
    if not download_url:
        return False, "no downloadUrl in response"
    ok, dl_err = await download_cf_file(download_url, dest_dir / filename)
    if not ok:
        return False, f"download: {dl_err}"
    return True, ""


# ── Main import function ──


async def import_modpack_archive(
    project_id: str,
    modpack_id: str,
    archive_path: Path,
    progress_callback=None,
) -> dict:
    cfg = ServerConfig.load()
    api_key = getattr(cfg, "curseforge_api_key", "") or ""
    tmp_dir = PROJECTS_STORAGE / "tmp" / modpack_id
    mp_dir = _modpack_dir(project_id, modpack_id)
    mp_dir.mkdir(parents=True, exist_ok=True)

    results = {"status": "ok", "downloaded": 0, "skipped": 0, "errors": []}

    def progress(state: dict):
        if progress_callback:
            progress_callback(state)

    try:
        # 1. Extract archive
        progress({"status": "extracting", "message": "Extracting archive...", "current": 0, "total": 0})
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(str(tmp_dir))

        # 2. Detect format
        fmt = detect_format(tmp_dir)
        if fmt is None:
            # Plain archive — extract all files directly
            progress({"status": "extracting", "message": "Plain archive — extracting files...", "current": 0, "total": 0})
            for entry in tmp_dir.iterdir():
                if entry.is_file() and entry.suffix != ".zip":
                    dest = mp_dir / entry.name
                    shutil.copy2(entry, dest)
            _update_files_hash(project_id, modpack_id)
            results["status"] = "ok"
            return results

        # 3. Parse manifest
        if fmt == "curseforge":
            manifest = parse_cf_manifest(tmp_dir)
        else:
            manifest = parse_mr_index(tmp_dir)

        mc_ver = manifest.get("mc_version", "")
        loader = manifest.get("loader", "")
        loader_ver = manifest.get("loader_version", "")
        progress({"status": "parsed", "message": f"Detected: {fmt}, MC {mc_ver}, {loader} {loader_ver}", "current": 0, "total": 0})

        # 4. Copy overrides first
        overrides_dir = manifest.get("overrides_dir")
        if overrides_dir and overrides_dir.exists():
            all_override_files = [e for e in overrides_dir.rglob("*") if e.is_file()]
            total_ov = len(all_override_files)
            progress({"status": "overrides", "message": f"Copying {total_ov} override files...", "current": 0, "total": total_ov})
            for idx, entry in enumerate(all_override_files):
                rel = entry.relative_to(overrides_dir).as_posix()
                dest = mp_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, dest)
                if (idx + 1) % 50 == 0 or idx == total_ov - 1:
                    progress({"status": "overrides", "message": f"Copying overrides... {idx+1}/{total_ov}", "current": idx + 1, "total": total_ov})

        # 5. Download mod files
        files = manifest.get("files", [])
        if fmt == "curseforge" and not api_key:
            progress({"status": "warning", "message": "No CurseForge API key configured — mod downloads will be skipped. Set it in Config.", "current": 0, "total": 0})
        total = len(files)
        progress({"status": "downloading", "message": f"Resolving {total} mods...", "current": 0, "total": total})

        for idx, fentry in enumerate(files):
            if fmt == "curseforge":
                pid = fentry.get("projectID")
                fid = fentry.get("fileID")
                if not api_key:
                    results["skipped"] += 1
                    progress({"status": "downloading", "message": f"[{idx+1}/{total}] SKIP (no CF API key)", "current": idx + 1, "total": total})
                else:
                    progress({"status": "downloading", "message": f"[{idx+1}/{total}] Resolving cf-{pid}/{fid}...", "current": idx + 1, "total": total})
                    ok, err = await download_curseforge_mod(pid, fid, api_key, mp_dir)
                    if ok:
                        results["downloaded"] += 1
                    else:
                        results["errors"].append(f"cf-{pid}/{fid}: {err}")
                        progress({"status": "downloading", "message": f"[{idx+1}/{total}] FAIL cf-{pid}/{fid}: {err}", "current": idx + 1, "total": total})

            elif fmt == "modrinth":
                mid = fentry.get("projectId", "")
                vid = fentry.get("versionId", "")
                progress({"status": "downloading", "message": f"[{idx+1}/{total}] Resolving {mid}...", "current": idx + 1, "total": total})
                url = f"https://api.modrinth.com/v2/version/{vid}"
                try:
                    async with aiohttp.ClientSession(headers={"User-Agent": "Uroboros/1.0"}) as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status == 200:
                                vdata = await resp.json()
                                for finfo in vdata.get("files", []):
                                    furl = finfo.get("url", "")
                                    fname = finfo.get("filename", f"{mid}.jar")
                                    if furl:
                                        ok = await download_mr_file(furl, mp_dir / fname)
                                        if ok:
                                            results["downloaded"] += 1
                                        else:
                                            results["errors"].append(f"{mid}: download failed")
                                        break
                            else:
                                body = await resp.text()
                                results["errors"].append(f"{mid}: API {resp.status}")
                                progress({"status": "downloading", "message": f"[{idx+1}/{total}] FAIL {mid}: API {resp.status}", "current": idx + 1, "total": total})
                except Exception as e:
                    results["errors"].append(f"{mid}: {e}")
                    progress({"status": "downloading", "message": f"[{idx+1}/{total}] FAIL {mid}: {e}", "current": idx + 1, "total": total})

        # 6. Update modpack metadata in DB if mc_version was detected
        try:
            from server.database import get_session
            from server.models import ModpackModel
            from sqlalchemy import select

            async with get_session() as session:
                stmt = select(ModpackModel).where(
                    ModpackModel.id == modpack_id,
                    ModpackModel.project_id == project_id,
                )
                result = await session.execute(stmt)
                m = result.scalar_one_or_none()
                if m:
                    if mc_ver and not m.mc_version:
                        m.mc_version = mc_ver
                    if loader and not m.loader:
                        m.loader = loader
                    if loader_ver and not m.loader_version:
                        m.loader_version = loader_ver
                    await session.commit()
        except Exception:
            pass  # DB not available (e.g. during testing)

        # 7. Update hash index
        progress({"status": "hashing", "message": "Computing file hashes...", "current": 0, "total": 0})
        _update_files_hash(project_id, modpack_id)
        progress({"status": "done", "message": "Import complete.", "current": 0, "total": 0})

    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return results


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
