import secrets
import time
from datetime import timedelta

from fastapi import HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED

from server.config import ServerConfig

_tokens: dict[str, float] = {}
TOKEN_EXPIRY = timedelta(hours=24).total_seconds()

PUBLIC_PREFIXES = {"/admin/login", "/admin/auth-status", "/admin/static"}
EXACT_PUBLIC = {"/admin/", "/admin/dashboard"}


def _cleanup():
    now = time.time()
    expired = [t for t, e in _tokens.items() if e < now]
    for t in expired:
        del _tokens[t]


def create_token() -> str:
    token = secrets.token_hex(32)
    _tokens[token] = time.time() + TOKEN_EXPIRY
    return token


def delete_token(token: str):
    _tokens.pop(token, None)


def validate_token(token: str) -> bool:
    _cleanup()
    return token in _tokens


async def require_admin(request: Request):
    path = request.url.path
    if path in EXACT_PUBLIC:
        return True
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    cfg = ServerConfig.load()
    if not cfg.admin_password:
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    token = auth[7:]
    _cleanup()
    if token not in _tokens:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return True
