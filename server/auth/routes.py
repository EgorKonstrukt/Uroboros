import base64
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Request, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import UserModel, ServerSessionModel
from .schemas import (
    AuthRequest, RegisterRequest, TokenRequest, RefreshRequest,
    JoinRequest, SignoutRequest,
)
from .crypto import hash_password, check_password, hash_token, new_uuid, new_token
from .ratelimit import auth_limiter
from server.web.auth import require_admin
from fastapi import Depends

router = APIRouter()
yggdrasil_router = APIRouter()

ACCESS_TOKEN_TTL = timedelta(hours=24)
SERVER_SESSION_TTL = timedelta(seconds=30)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _error(message: str, code: int = 403) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"error": "ForbiddenOperationException", "errorMessage": message},
    )


def _client_ip(request: Request) -> str:
    """Best-effort client IP.

    Only trusts X-Forwarded-For when explicitly configured via
    `trust_proxy_headers`, otherwise it is spoofable and ignored.
    """
    try:
        from server.config import ServerConfig
        cfg = ServerConfig.load()
        trust_proxy = bool(getattr(cfg, "trust_proxy_headers", False))
    except Exception:
        trust_proxy = False
    if trust_proxy:
        fwd = request.headers.get("X-Forwarded-For")
        if fwd:
            return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def _record_ip(user, ip: str):
    ip = (ip or "").strip()
    if not ip:
        return
    user.last_ip = ip
    history = dict(user.ip_history or {})
    history[ip] = _now().isoformat()
    items = sorted(history.items(), key=lambda kv: kv[1], reverse=True)
    user.ip_history = dict(items[:10])


def _check_rate(request: Request) -> Optional[JSONResponse]:
    if not auth_limiter.allow(_client_ip(request)):
        return JSONResponse(
            status_code=429,
            content={"error": "TooManyRequests", "errorMessage": "Too many requests, try again later"},
        )
    return None


async def _get_user_by_username(session: AsyncSession, username: str) -> Optional[UserModel]:
    stmt = select(UserModel).where(
        or_(
            UserModel.username == username,
            UserModel.display_name == username,
            UserModel.email == username,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_user_by_token(session: AsyncSession, token: str) -> Optional[UserModel]:
    if not token:
        return None
    stmt = select(UserModel).where(
        UserModel.access_token_hash == hash_token(token),
        UserModel.token_expires_at > _now(),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_user_by_uuid(session: AsyncSession, uid: str) -> Optional[UserModel]:
    stmt = select(UserModel).where(UserModel.uuid == uid)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _properties_to_list(properties: dict) -> list:
    if not properties:
        return []
    if isinstance(properties, list):
        return properties
    out = []
    for name, value in properties.items():
        encoded = base64.b64encode(str(value).encode("utf-8")).decode("ascii")
        out.append({"name": str(name), "value": encoded})
    return out


def _textures_value(user: UserModel, base_url: str) -> Optional[str]:
    if not user.skin:
        return None
    payload = {
        "timestamp": int(time.time() * 1000),
        "profileId": user.uuid,
        "profileName": user.display_name,
        "textures": {
            "SKIN": {
                "url": f"{base_url}/auth/skin/{user.uuid}",
                "metadata": {"model": user.skin_model or "classic"},
            }
        },
    }
    return json.dumps(payload, separators=(",", ":"))


def _user_properties(user: UserModel, base_url: str) -> list:
    props = _properties_to_list(user.properties)
    tex = _textures_value(user, base_url)
    if tex:
        props.append({
            "name": "textures",
            "value": base64.b64encode(tex.encode("utf-8")).decode("ascii"),
        })
    return props


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _issue_token(user: UserModel, client_token: str) -> str:
    token = new_token()
    user.access_token_hash = hash_token(token)
    user.client_token_hash = hash_token(client_token) if client_token else ""
    user.token_expires_at = _now() + ACCESS_TOKEN_TTL
    return token


def _user_to_profile(user: UserModel) -> dict:
    return {"id": user.uuid, "name": user.display_name}


def _user_to_auth_response(user: UserModel, access_token: str, client_token: str, request_user: bool, base_url: str) -> dict:
    profiles = [_user_to_profile(user)]
    resp = {
        "accessToken": access_token,
        "clientToken": client_token,
        "availableProfiles": profiles,
        "selectedProfile": profiles[0],
    }
    if request_user:
        resp["user"] = {
            "id": user.uuid,
            "properties": _user_properties(user, base_url),
        }
    return resp


@router.post("/authenticate")
async def authenticate(request: Request, body: AuthRequest):
    limited = _check_rate(request)
    if limited:
        return limited
    async with get_session() as session:
        user = await _get_user_by_username(session, body.username)
        if not user or not check_password(body.password, user.password_hash):
            return _error("Invalid credentials")

        from server.mc.bans import get_global_ban
        ban = await get_global_ban(user, _client_ip(request))
        if ban is not None:
            return _error(f"You are banned: {ban.reason or 'Banned'}")

        _record_ip(user, _client_ip(request))

        client_token = body.clientToken or new_token()
        access_token = _issue_token(user, client_token)
        await session.commit()
        return _user_to_auth_response(user, access_token, client_token, body.requestUser, _base_url(request))


@router.post("/register")
async def register(request: Request, body: RegisterRequest):
    limited = _check_rate(request)
    if limited:
        return limited
    username = (body.username or "").strip()
    password = body.password or ""
    if not username:
        return _error("Username is required", 400)
    if len(username) > 255:
        return _error("Username too long (max 255 characters)", 400)
    if len(password) < 8:
        return _error("Password too short (min 8 characters)", 400)
    if len(password) > 1024:
        return _error("Password too long (max 1024 characters)", 400)

    ip = _client_ip(request)
    from server.mc.bans import find_active_bans
    blocked = await find_active_bans(nick=username, email=body.email or "", ip=ip)
    if blocked:
        ban = blocked[0][0]
        return _error(f"You are banned: {ban.reason or 'Banned'}")

    async with get_session() as session:
        existing = await _get_user_by_username(session, username)
        if existing:
            return _error("Account already exists", 409)

        uid = new_uuid()
        client_token = new_token()
        email_username = body.email or (
            f"{username}@yggdrasil" if "@" not in username else username
        )

        user = UserModel(
            uuid=uid,
            username=email_username,
            display_name=username,
            email=body.email or "",
            password_hash=hash_password(password),
            properties={},
            last_ip=ip,
            ip_history={ip: _now().isoformat()} if ip else {},
        )
        session.add(user)
        await session.flush()
        access_token = _issue_token(user, client_token)
        await session.commit()

        from server.mc.whitelist import sync_all_whitelists
        try:
            await sync_all_whitelists()
        except Exception:
            pass

        resp = _user_to_auth_response(user, access_token, client_token, False, _base_url(request))
        return JSONResponse(resp, status_code=201)


@router.post("/refresh")
async def refresh(request: Request, body: RefreshRequest):
    limited = _check_rate(request)
    if limited:
        return limited
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if not user:
            return _error("Invalid token")
        if body.clientToken and not (
            user.client_token_hash and hash_token(body.clientToken) == user.client_token_hash
        ):
            return _error("Invalid clientToken")

        client_token = body.clientToken if body.clientToken else new_token()
        _record_ip(user, _client_ip(request))
        access_token = _issue_token(user, client_token)
        await session.commit()
        return _user_to_auth_response(user, access_token, client_token, body.requestUser, _base_url(request))


@router.post("/validate")
async def validate(request: Request, body: TokenRequest):
    limited = _check_rate(request)
    if limited:
        return limited
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if not user:
            return _error("Invalid token")
        if body.clientToken and not (
            user.client_token_hash and hash_token(body.clientToken) == user.client_token_hash
        ):
            return _error("Invalid clientToken")
        return {}


@router.post("/invalidate")
async def invalidate(request: Request, body: TokenRequest):
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if user:
            if body.clientToken and user.client_token_hash and (
                hash_token(body.clientToken) != user.client_token_hash
            ):
                return _error("Invalid clientToken")
            user.access_token_hash = ""
            user.client_token_hash = ""
            user.token_expires_at = None
            await session.commit()
    return {}


@router.post("/signout")
async def signout(request: Request, body: SignoutRequest):
    async with get_session() as session:
        user = await _get_user_by_username(session, body.username)
        if user and check_password(body.password, user.password_hash):
            user.access_token_hash = ""
            user.client_token_hash = ""
            user.token_expires_at = None
            await session.commit()
    return {}


@router.post("/join")
async def join_server(request: Request, body: JoinRequest):
    limited = _check_rate(request)
    if limited:
        return limited
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if not user or user.uuid != body.selectedProfile.replace("-", ""):
            return _error("Invalid token or profile")

        from server.mc.bans import get_global_ban
        ban = await get_global_ban(user)
        if ban is not None:
            return _error(f"You are banned: {ban.reason or 'Banned'}")

        stmt = select(ServerSessionModel).where(
            ServerSessionModel.display_name == user.display_name
        )
        result = await session.execute(stmt)
        ss = result.scalar_one_or_none()
        if not ss:
            ss = ServerSessionModel(
                display_name=user.display_name,
                server_id=body.serverId,
                expires_at=_now() + SERVER_SESSION_TTL,
            )
            session.add(ss)
        else:
            ss.server_id = body.serverId
            ss.expires_at = _now() + SERVER_SESSION_TTL
        await session.commit()
        return {}


@router.get("/hasJoined")
async def has_joined(request: Request):
    qs = parse_qs(urlparse(str(request.url)).query)
    username = qs.get("username", [""])[0]
    server_id = qs.get("serverId", [""])[0]

    async with get_session() as session:
        stmt = select(ServerSessionModel).where(
            ServerSessionModel.display_name == username,
            ServerSessionModel.server_id == server_id,
            ServerSessionModel.expires_at > _now(),
        )
        result = await session.execute(stmt)
        ss = result.scalar_one_or_none()

        if ss:
            stmt = select(UserModel).where(UserModel.display_name == username)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                from server.mc.bans import get_global_ban
                ban = await get_global_ban(user)
                if ban is not None:
                    return _error("You are banned")
                return {
                    "id": user.uuid,
                    "name": user.display_name,
                    "properties": _user_properties(user, _base_url(request)),
                }

        return _error("Failed to verify")


@router.get("/profile/{profile_id}")
async def get_profile(profile_id: str, request: Request):
    clean_id = profile_id.replace("-", "")
    async with get_session() as session:
        user = await _get_user_by_uuid(session, clean_id)
        if user:
            return {
                "id": user.uuid,
                "name": user.display_name,
                "properties": _user_properties(user, _base_url(request)),
            }
        return _error("Profile not found", 404)


@router.get("/skin/{profile_id}")
async def get_skin(profile_id: str):
    clean_id = profile_id.replace("-", "")
    async with get_session() as session:
        user = await _get_user_by_uuid(session, clean_id)
        if not user or not user.skin:
            return JSONResponse(content={"error": "Skin not found"}, status_code=404)
        try:
            data = base64.b64decode(user.skin)
        except Exception:
            return JSONResponse(content={"error": "Skin not found"}, status_code=404)
        return Response(content=data, media_type="image/png")


@router.post("/skin")
async def upload_skin(request: Request, file: UploadFile = File(...), model: str = Form("classic")):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    async with get_session() as session:
        user = await _get_user_by_token(session, token)
        if not user:
            return _error("Invalid token")
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            return _error("Skin file too large")
        ctype = (file.content_type or "").lower()
        if ctype not in ("image/png", "image/jpeg"):
            return _error("Skin must be a PNG or JPEG image")
        skin_model = (model or "classic").strip().lower()
        if skin_model not in ("classic", "slim"):
            skin_model = "classic"
        user.skin = base64.b64encode(data).decode("ascii")
        user.skin_model = skin_model
        await session.commit()
        return {"status": "updated", "has_skin": True, "model": skin_model}


@router.post("/skin/remove")
async def remove_skin(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    async with get_session() as session:
        user = await _get_user_by_token(session, token)
        if not user:
            return _error("Invalid token")
        user.skin = ""
        await session.commit()
        return {"status": "removed"}


@router.get("/admin/users", dependencies=[Depends(require_admin)])
async def admin_list_users():
    async with get_session() as session:
        stmt = select(UserModel).order_by(UserModel.id)
        result = await session.execute(stmt)
        users = result.scalars().all()
        return [
            {
                "id": u.id,
                "uuid": u.uuid,
                "username": u.username,
                "display_name": u.display_name,
                "email": u.email,
                "created_at": str(u.created_at),
            }
            for u in users
        ]


@router.get("/admin/sessions", dependencies=[Depends(require_admin)])
async def admin_list_sessions():
    async with get_session() as session:
        stmt = select(ServerSessionModel).order_by(ServerSessionModel.id)
        result = await session.execute(stmt)
        sessions = result.scalars().all()
        return [
            {
                "id": s.id,
                "display_name": s.display_name,
                "server_id": s.server_id,
                "expires_at": str(s.expires_at) if s.expires_at else None,
                "created_at": str(s.created_at),
            }
            for s in sessions
        ]


@router.get("/admin/stats", dependencies=[Depends(require_admin)])
async def admin_stats():
    async with get_session() as session:
        user_count = (await session.execute(select(func.count(UserModel.id)))).scalar()
        session_count = (await session.execute(select(func.count(ServerSessionModel.id)))).scalar()
        return {
            "users": user_count,
            "sessions": session_count,
        }


# ── Yggdrasil (authlib-injector compatible) endpoints ──
#
# authlib-injector expects the Mojang yggdrasil protocol at these paths:
#   POST /authserver/authenticate|refresh|validate|invalidate|signout
#   POST /sessionserver/session/minecraft/join
#   GET  /sessionserver/session/minecraft/hasJoined
#   GET  /sessionserver/session/minecraft/profile/{uuid}
#   GET  /api/user/profile/{uuid}/skin
#   POST /api/profiles/minecraft
#
# These wrappers reuse the handlers above (which already follow the
# yggdrasil JSON format) but expose them at the protocol paths.


@yggdrasil_router.post("/authserver/authenticate")
async def ygg_authenticate(request: Request, body: AuthRequest):
    return await authenticate(request, body)


@yggdrasil_router.post("/authserver/refresh")
async def ygg_refresh(request: Request, body: RefreshRequest):
    return await refresh(request, body)


@yggdrasil_router.post("/authserver/validate")
async def ygg_validate(request: Request, body: TokenRequest):
    limited = _check_rate(request)
    if limited:
        return limited
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if not user:
            return _error("Invalid token")
        if body.clientToken and not (
            user.client_token_hash and hash_token(body.clientToken) == user.client_token_hash
        ):
            return _error("Invalid clientToken")
        return Response(status_code=204)


@yggdrasil_router.post("/authserver/invalidate")
async def ygg_invalidate(request: Request, body: TokenRequest):
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if user:
            user.access_token_hash = ""
            user.client_token_hash = ""
            user.token_expires_at = None
            await session.commit()
    return Response(status_code=204)


@yggdrasil_router.post("/authserver/signout")
async def ygg_signout(request: Request, body: SignoutRequest):
    async with get_session() as session:
        user = await _get_user_by_username(session, body.username)
        if user and check_password(body.password, user.password_hash):
            user.access_token_hash = ""
            user.client_token_hash = ""
            user.token_expires_at = None
            await session.commit()
    return Response(status_code=204)


@yggdrasil_router.post("/sessionserver/session/minecraft/join")
async def ygg_join(request: Request, body: JoinRequest):
    limited = _check_rate(request)
    if limited:
        return limited
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if not user or user.uuid != body.selectedProfile.replace("-", ""):
            return _error("Invalid token or profile")

        from server.mc.bans import get_global_ban
        ban = await get_global_ban(user)
        if ban is not None:
            return _error(f"You are banned: {ban.reason or 'Banned'}")

        stmt = select(ServerSessionModel).where(
            ServerSessionModel.display_name == user.display_name
        )
        result = await session.execute(stmt)
        ss = result.scalar_one_or_none()
        if not ss:
            ss = ServerSessionModel(
                display_name=user.display_name,
                server_id=body.serverId,
                expires_at=_now() + SERVER_SESSION_TTL,
            )
            session.add(ss)
        else:
            ss.server_id = body.serverId
            ss.expires_at = _now() + SERVER_SESSION_TTL
        await session.commit()
        return Response(status_code=204)


@yggdrasil_router.get("/sessionserver/session/minecraft/hasJoined")
async def ygg_has_joined(request: Request):
    qs = parse_qs(urlparse(str(request.url)).query)
    username = qs.get("username", [""])[0]
    server_id = qs.get("serverId", [""])[0]

    async with get_session() as session:
        stmt = select(ServerSessionModel).where(
            ServerSessionModel.display_name == username,
            ServerSessionModel.server_id == server_id,
            ServerSessionModel.expires_at > _now(),
        )
        result = await session.execute(stmt)
        ss = result.scalar_one_or_none()

        if ss:
            stmt = select(UserModel).where(UserModel.display_name == username)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                from server.mc.bans import get_global_ban
                ban = await get_global_ban(user)
                if ban is not None:
                    return Response(status_code=204)
                return {
                    "id": user.uuid,
                    "name": user.display_name,
                    "properties": _user_properties(user, _base_url(request)),
                }

        return Response(status_code=204)


@yggdrasil_router.get("/sessionserver/session/minecraft/profile/{profile_id}")
async def ygg_get_profile(profile_id: str, request: Request):
    clean_id = profile_id.replace("-", "")
    async with get_session() as session:
        user = await _get_user_by_uuid(session, clean_id)
        if user:
            return {
                "id": user.uuid,
                "name": user.display_name,
                "properties": _user_properties(user, _base_url(request)),
            }
        return Response(status_code=204)


@yggdrasil_router.get("/api/user/profile/{profile_id}/skin")
async def ygg_get_skin(profile_id: str):
    return await get_skin(profile_id)


@yggdrasil_router.put("/api/user/profile/{profile_id}/skin")
async def ygg_put_skin(profile_id: str, request: Request, file: UploadFile = File(...), model: str = Form("")):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    clean_id = profile_id.replace("-", "")
    async with get_session() as session:
        user = await _get_user_by_token(session, token)
        if not user:
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "errorMessage": "Invalid token"},
            )
        if user.uuid != clean_id:
            return _error("Invalid token or profile")
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            return _error("Skin file too large")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return _error("Skin must be a PNG image")
        skin_model = (model or "classic").strip().lower()
        if skin_model not in ("classic", "slim"):
            skin_model = "classic"
        user.skin = base64.b64encode(data).decode("ascii")
        user.skin_model = skin_model
        await session.commit()
        return Response(status_code=204)


@yggdrasil_router.delete("/api/user/profile/{profile_id}/skin")
async def ygg_delete_skin(profile_id: str, request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    clean_id = profile_id.replace("-", "")
    async with get_session() as session:
        user = await _get_user_by_token(session, token)
        if not user:
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "errorMessage": "Invalid token"},
            )
        if user.uuid != clean_id:
            return _error("Invalid token or profile")
        user.skin = ""
        await session.commit()
        return Response(status_code=204)


@yggdrasil_router.post("/api/profiles/minecraft")
async def ygg_profiles_minecraft(body: list[str]):
    """Mojang profile-name lookup: body is a JSON array of names."""
    names = [n for n in (body or []) if isinstance(n, str) and n.strip()]
    if not names:
        return []
    async with get_session() as session:
        stmt = select(UserModel).where(
            or_(
                UserModel.display_name.in_(names),
                UserModel.username.in_(names),
            )
        )
        result = await session.execute(stmt)
        users = result.scalars().all()
        by_name = {}
        for u in users:
            by_name[u.display_name] = u
            by_name[u.username] = u
        out = []
        for n in names:
            u = by_name.get(n)
            if u:
                out.append({"id": u.uuid, "name": u.display_name})
        return out
