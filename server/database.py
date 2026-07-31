from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.inspection import inspect

from server.models import Base


def get_database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def _column_names(conn, table: str) -> set:
    return {c["name"] for c in inspect(conn).get_columns(table)}


def _migrate(conn):
    users = _column_names(conn, "users")
    if "access_token" in users and "access_token_hash" not in users:
        conn.execute(text("ALTER TABLE users RENAME COLUMN access_token TO access_token_hash"))
    if "client_token" in users and "client_token_hash" not in users:
        conn.execute(text("ALTER TABLE users RENAME COLUMN client_token TO client_token_hash"))
    if "token_expires_at" not in users:
        conn.execute(text("ALTER TABLE users ADD COLUMN token_expires_at DATETIME"))
    if "last_ip" not in users:
        conn.execute(text("ALTER TABLE users ADD COLUMN last_ip VARCHAR(64) NOT NULL DEFAULT ''"))
    if "ip_history" not in users:
        conn.execute(text("ALTER TABLE users ADD COLUMN ip_history TEXT NOT NULL DEFAULT '{}'"))
    sessions = _column_names(conn, "server_sessions")
    if "expires_at" not in sessions:
        conn.execute(text("ALTER TABLE server_sessions ADD COLUMN expires_at DATETIME"))
    if "created_at" not in sessions:
        conn.execute(text("ALTER TABLE server_sessions ADD COLUMN created_at DATETIME"))
    instances = _column_names(conn, "instances")
    if "whitelist_enabled" not in instances:
        conn.execute(text("ALTER TABLE instances ADD COLUMN whitelist_enabled BOOLEAN NOT NULL DEFAULT 0"))
    conn.execute(text("UPDATE users SET access_token_hash='', client_token_hash='', token_expires_at=NULL"))


class DatabaseManager:
    def __init__(self):
        self._engine = None
        self._async_session = None

    async def init_db(self, db_path: Path):
        url = get_database_url(db_path)
        self._engine = create_async_engine(url, echo=False)
        self._async_session = async_sessionmaker(self._engine, class_=AsyncSession, expire_on_commit=False)
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_migrate)

    async def close_db(self):
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._async_session = None

    def get_session(self) -> AsyncSession:
        if self._async_session is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        return self._async_session()


_db_manager = DatabaseManager()


async def init_db(db_path: Path):
    await _db_manager.init_db(db_path)


async def close_db():
    await _db_manager.close_db()


def get_session() -> AsyncSession:
    return _db_manager.get_session()
