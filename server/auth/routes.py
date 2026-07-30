import traceback
from typing import Optional
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import UserModel, ServerSessionModel
from .schemas import (
    AuthRequest, RegisterRequest, TokenRequest, RefreshRequest,
    JoinRequest, SignoutRequest,
)
from .crypto import hash_password, check_password, new_uuid, new_token

router = APIRouter()


async def _get_user_by_username(session: AsyncSession, username: str) -> Optional[UserModel]:
    stmt = select(UserModel).where(
        or_(UserModel.username == username, UserModel.display_name == username)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_user_by_token(session: AsyncSession, token: str) -> Optional[UserModel]:
    stmt = select(UserModel).where(UserModel.access_token == token)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_user_by_uuid(session: AsyncSession, uid: str) -> Optional[UserModel]:
    stmt = select(UserModel).where(UserModel.uuid == uid)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _user_to_profile(user: UserModel) -> dict:
    return {"id": user.uuid, "name": user.display_name}


async def _user_to_auth_response(user: UserModel, client_token: str) -> dict:
    profiles = [await _user_to_profile(user)]
    return {
        "accessToken": user.access_token,
        "clientToken": client_token,
        "availableProfiles": profiles,
        "selectedProfile": profiles[0],
    }


@router.post("/authenticate")
async def authenticate(body: AuthRequest):
    async with get_session() as session:
        user = await _get_user_by_username(session, body.username)

        if not user:
            for key in (body.username, body.username.split("@")[0]):
                stmt = select(UserModel).where(UserModel.username == key)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if user and check_password(body.password, user.password_hash):
                    break
                user = None
            if not user:
                user = UserModel(
                    uuid=new_uuid(),
                    username=body.username if "@" in body.username else f"{body.username}@yggdrasil",
                    display_name=body.username,
                    email="",
                    password_hash=hash_password(body.password),
                    access_token=new_token(),
                    client_token=body.clientToken or new_token(),
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

        if not check_password(body.password, user.password_hash):
            return JSONResponse(
                status_code=403,
                content={"error": "ForbiddenOperationException", "errorMessage": "Invalid credentials"},
            )

        client_token = body.clientToken or new_token()
        user.access_token = new_token()
        user.client_token = client_token
        await session.commit()

        resp = await _user_to_auth_response(user, client_token)
        if body.requestUser:
            resp["user"] = {"id": user.uuid, "properties": user.properties if user.properties else {}}
        return resp


@router.post("/register")
async def register(body: RegisterRequest):
    try:
        if not body.username or not body.password:
            return JSONResponse(
                status_code=400,
                content={"error": "ForbiddenOperationException", "errorMessage": "Username and password required"},
            )
        if len(body.password) < 4:
            return JSONResponse(
                status_code=400,
                content={"error": "ForbiddenOperationException", "errorMessage": "Password too short (min 4 characters)"},
            )

        async with get_session() as session:
            existing = await _get_user_by_username(session, body.username)
            if existing:
                return JSONResponse(
                    status_code=409,
                    content={"error": "ForbiddenOperationException", "errorMessage": "Account already exists"},
                )

            uid = new_uuid()
            at = new_token()
            ct = new_token()
            email_username = body.email or (
                f"{body.username}@yggdrasil" if "@" not in body.username else body.username
            )

            user = UserModel(
                uuid=uid,
                username=email_username,
                display_name=body.username,
                email=body.email,
                password_hash=hash_password(body.password),
                access_token=at,
                client_token=ct,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            resp = await _user_to_auth_response(user, ct)
            return JSONResponse(resp, status_code=201)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[Register Error] {e}\n{tb}")
        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "errorMessage": str(e), "detail": tb},
        )


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if not user:
            return JSONResponse(
                status_code=403,
                content={"error": "ForbiddenOperationException", "errorMessage": "Invalid token"},
            )

        client_token = body.clientToken or new_token()
        user.access_token = new_token()
        user.client_token = client_token
        await session.commit()

        resp = await _user_to_auth_response(user, client_token)
        if body.requestUser:
            resp["user"] = {"id": user.uuid, "properties": user.properties if user.properties else {}}
        return resp


@router.post("/validate")
async def validate(body: TokenRequest):
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if user:
            return {}
        return JSONResponse(
            status_code=403,
            content={"error": "ForbiddenOperationException", "errorMessage": "Invalid token"},
        )


@router.post("/invalidate")
async def invalidate(body: TokenRequest):
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if user:
            user.access_token = ""
            await session.commit()
    return {}


@router.post("/signout")
async def signout(body: SignoutRequest):
    async with get_session() as session:
        user = await _get_user_by_username(session, body.username)
        if user:
            user.access_token = ""
            await session.commit()
    return {}


@router.post("/join")
async def join_server(body: JoinRequest):
    async with get_session() as session:
        user = await _get_user_by_token(session, body.accessToken)
        if user and user.uuid == body.selectedProfile.replace("-", ""):
            stmt = select(ServerSessionModel).where(
                ServerSessionModel.display_name == user.display_name
            )
            result = await session.execute(stmt)
            ss = result.scalar_one_or_none()
            if not ss:
                ss = ServerSessionModel(display_name=user.display_name, server_id=body.serverId)
                session.add(ss)
            else:
                ss.server_id = body.serverId
            await session.commit()
            return {}
        return JSONResponse(
            status_code=403,
            content={"error": "ForbiddenOperationException", "errorMessage": "Invalid token or profile"},
        )


@router.get("/hasJoined")
async def has_joined(request: Request):
    qs = parse_qs(urlparse(str(request.url)).query)
    username = qs.get("username", [""])[0]
    server_id = qs.get("serverId", [""])[0]

    async with get_session() as session:
        stmt = select(ServerSessionModel).where(
            ServerSessionModel.display_name == username,
            ServerSessionModel.server_id == server_id,
        )
        result = await session.execute(stmt)
        ss = result.scalar_one_or_none()

        if ss:
            stmt = select(UserModel).where(UserModel.display_name == username)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                return {
                    "id": user.uuid,
                    "name": user.display_name,
                    "properties": user.properties if user.properties else [],
                }

        return JSONResponse(
            status_code=403,
            content={"error": "ForbiddenOperationException", "errorMessage": "Failed to verify"},
        )


@router.get("/profile/{profile_id}")
async def get_profile(profile_id: str):
    clean_id = profile_id.replace("-", "")
    async with get_session() as session:
        user = await _get_user_by_uuid(session, clean_id)
        if user:
            return {
                "id": user.uuid,
                "name": user.display_name,
                "properties": user.properties if user.properties else [],
            }
        return JSONResponse(
            status_code=404,
            content={"error": "ForbiddenOperationException", "errorMessage": "Profile not found"},
        )


@router.get("/admin/users")
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
                "password_hash": u.password_hash[:12] + "...",
                "access_token": u.access_token[:12] + "..." if u.access_token else "",
                "client_token": u.client_token[:12] + "..." if u.client_token else "",
                "created_at": str(u.created_at),
            }
            for u in users
        ]


@router.get("/admin/sessions")
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
            }
            for s in sessions
        ]


@router.get("/admin/stats")
async def admin_stats():
    async with get_session() as session:
        user_count = (await session.execute(select(func.count(UserModel.id)))).scalar()
        session_count = (await session.execute(select(func.count(ServerSessionModel.id)))).scalar()
        return {
            "users": user_count,
            "sessions": session_count,
        }
