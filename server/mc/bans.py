import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select, or_

from server.database import get_session
from server.models import UserBanModel, InstanceModel, UserModel

BANNED_PLAYERS_FILE = "banned-players.json"
BAN_SOURCE = "Uroboros"


def _uuid_with_dashes(uid: str) -> str:
    uid = uid.replace("-", "")
    if len(uid) != 32:
        return uid
    return f"{uid[0:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:32]}"


def _format_mc_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return "(Forever)"
    return dt.strftime("%Y-%m-%d %H:%M:%S +0000")


def _now() -> datetime:
    return datetime.now()


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _ip_set(user: UserModel) -> set:
    ips = set()
    if user.last_ip:
        ips.add(user.last_ip)
    for key in (user.ip_history or {}):
        if key:
            ips.add(key)
    return ips


def _matches_identity(banned: UserModel, *, user: Optional[UserModel] = None,
                      nick: str = "", email: str = "", ip: str = "") -> bool:
    if user is not None:
        if banned.id == user.id:
            return True
        nick = nick or user.display_name or user.username
        email = email or user.email
        if not ip:
            ip = user.last_ip or ""
    if nick:
        nick = _norm(nick)
        if _norm(banned.display_name) == nick or _norm(banned.username) == nick:
            return True
    if email and _norm(email) and banned.email and _norm(banned.email) == _norm(email):
        return True
    banned_ips = _ip_set(banned)
    if ip and ip in banned_ips:
        return True
    if user is not None and user.last_ip and user.last_ip in banned_ips:
        return True
    if user is not None:
        user_ips = _ip_set(user)
        if user_ips & banned_ips:
            return True
    return False


def _match_reasons(banned: UserModel, *, user: Optional[UserModel] = None,
                   nick: str = "", email: str = "", ip: str = "") -> list:
    reasons = []
    if user is not None:
        if banned.id == user.id:
            reasons.append("account")
        nick = nick or user.display_name or user.username
        email = email or user.email
        if not ip:
            ip = user.last_ip or ""
    if nick:
        nick = _norm(nick)
        if _norm(banned.display_name) == nick or _norm(banned.username) == nick:
            reasons.append("nickname")
    if email and _norm(email) and banned.email and _norm(banned.email) == _norm(email):
        reasons.append("email")
    banned_ips = _ip_set(banned)
    if ip and ip in banned_ips:
        reasons.append("ip")
    if user is not None:
        user_ips = _ip_set(user)
        if user_ips & banned_ips:
            reasons.append("ip")
    seen = set()
    unique = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


async def _active_ban_rows() -> list:
    now = _now()
    async with get_session() as session:
        stmt = select(UserBanModel, UserModel).join(
            UserModel, UserBanModel.user_id == UserModel.id
        ).where(
            or_(
                UserBanModel.expires_at.is_(None),
                UserBanModel.expires_at > now,
            )
        )
        result = await session.execute(stmt)
        return result.all()


async def _bans_for(instance_id: str):
    now = _now()
    async with get_session() as session:
        stmt = select(UserBanModel, UserModel).join(
            UserModel, UserBanModel.user_id == UserModel.id
        ).where(
            or_(
                UserBanModel.instance_id == instance_id,
                UserBanModel.instance_id.is_(None),
            ),
            or_(
                UserBanModel.expires_at.is_(None),
                UserBanModel.expires_at > now,
            ),
        )
        result = await session.execute(stmt)
        return result.all()


async def find_active_bans(user: Optional[UserModel] = None, *,
                           nick: str = "", email: str = "", ip: str = "") -> list:
    rows = await _active_ban_rows()
    matches = []
    for ban, banned_user in rows:
        if _matches_identity(banned_user, user=user, nick=nick, email=email, ip=ip):
            matches.append((ban, banned_user))
    return matches


async def get_global_ban(user: UserModel, ip: str = "") -> Optional[UserBanModel]:
    if user is None:
        return None
    for ban, _ in await find_active_bans(user=user, ip=ip):
        if ban.instance_id is None:
            return ban
    return None


async def _affected_users(rows) -> list:
    async with get_session() as session:
        all_users = (await session.execute(select(UserModel))).scalars().all()
    affected = []
    seen = set()
    for ban, banned_user in rows:
        for u in all_users:
            if u.id in seen:
                continue
            if _matches_identity(banned_user, user=u):
                seen.add(u.id)
                affected.append((u, ban))
    return affected


def _write_ban_file(server_dir: Path, entries: list):
    server_dir.mkdir(parents=True, exist_ok=True)
    path = server_dir / BANNED_PLAYERS_FILE
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


async def sync_instance_bans(inst) -> dict:
    server_dir = Path(inst.server_dir)
    rows = await _bans_for(inst.id)
    users = await _affected_users(rows)
    entries = [
        {
            "uuid": _uuid_with_dashes(u.uuid),
            "name": u.display_name,
            "created": _format_mc_datetime(ban.created_at),
            "source": BAN_SOURCE,
            "expires": _format_mc_datetime(ban.expires_at),
            "reason": ban.reason or "Banned",
        }
        for u, ban in users
    ]
    _write_ban_file(server_dir, entries)
    return {"count": len(entries)}


async def _load_instances() -> list[InstanceModel]:
    async with get_session() as session:
        stmt = select(InstanceModel).order_by(InstanceModel.name)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def sync_all_bans() -> dict:
    from server.mc.registry import get_manager

    instances = await _load_instances()
    results = {}
    for inst in instances:
        results[inst.id] = await sync_instance_bans(inst)
        mgr = await get_manager(inst.id)
        if mgr and mgr.is_running():
            mgr.send_command("banlist reload")
    return results


async def create_ban(user_id: int, instance_id: Optional[str], reason: str, duration_seconds: Optional[int]) -> int:
    expires_at = None
    if duration_seconds and duration_seconds > 0:
        expires_at = _now() + timedelta(seconds=duration_seconds)
    async with get_session() as session:
        stmt = select(UserBanModel).where(UserBanModel.user_id == user_id)
        result = await session.execute(stmt)
        old_bans = result.scalars().all()
        for b in old_bans:
            if instance_id is None or b.instance_id == instance_id:
                await session.delete(b)
        ban = UserBanModel(
            user_id=user_id,
            instance_id=instance_id,
            reason=reason or "",
            expires_at=expires_at,
        )
        session.add(ban)
        await session.commit()
        return ban.id


async def remove_ban(user_id: int, instance_id: Optional[str] = None) -> int:
    async with get_session() as session:
        stmt = select(UserBanModel).where(UserBanModel.user_id == user_id)
        result = await session.execute(stmt)
        bans = result.scalars().all()
        removed = 0
        for b in bans:
            if instance_id is None or b.instance_id == instance_id:
                await session.delete(b)
                removed += 1
        await session.commit()
        return removed


async def remove_ban_by_id(user_id: int, ban_id: int) -> int:
    async with get_session() as session:
        stmt = select(UserBanModel).where(
            UserBanModel.id == ban_id,
            UserBanModel.user_id == user_id,
        )
        result = await session.execute(stmt)
        ban = result.scalar_one_or_none()
        if ban is None:
            return 0
        await session.delete(ban)
        await session.commit()
        return 1
