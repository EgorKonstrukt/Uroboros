from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from server.models import Base


def get_database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


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
