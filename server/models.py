from datetime import datetime
from sqlalchemy import String, JSON, DateTime, func, Integer, Boolean, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


_INSTANCE_DEFAULTS = {
    "name": "",
    "project_id": None,
    "enabled": True,
    "server_dir": "",
    "server_filename": "server.jar",
    "java_executable_path": "java",
    "max_memory": 2048,
    "min_memory": 1024,
    "additional_flags": "",
    "arguments": "",
    "api_url": "http://127.0.0.1:25581",
    "auth_plugin": "injector",
    "injector_filename": "authlib-injector.jar",
    "auto_restart": False,
    "auto_accept_eula": True,
    "version": "",
    "jar_url": "",
}


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    client_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    token_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ServerSessionModel(Base):
    __tablename__ = "server_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    server_id: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    icon: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    logo_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    background_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    primary_color: Mapped[str] = mapped_column(String(16), default="#6c63ff", nullable=False)
    accent_color: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    window_title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    brand_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectNewsModel(Base):
    __tablename__ = "project_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    important: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModpackModel(Base):
    __tablename__ = "modpacks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    mc_version: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    loader: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    loader_version: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    min_memory: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    max_memory: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    java_args: Mapped[str] = mapped_column(Text, default="", nullable=False)
    java_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class InstanceModel(Base):
    __tablename__ = "instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=True, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    server_dir: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    server_filename: Mapped[str] = mapped_column(String(255), default="server.jar", nullable=False)
    java_executable_path: Mapped[str] = mapped_column(String(512), default="java", nullable=False)
    max_memory: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    min_memory: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    additional_flags: Mapped[str] = mapped_column(Text, default="", nullable=False)
    arguments: Mapped[str] = mapped_column(Text, default="", nullable=False)
    modpack_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    api_url: Mapped[str] = mapped_column(String(512), default="http://127.0.0.1:25581", nullable=False)
    auth_plugin: Mapped[str] = mapped_column(String(64), default="injector", nullable=False)
    injector_filename: Mapped[str] = mapped_column(String(255), default="authlib-injector.jar", nullable=False)
    auto_restart: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_accept_eula: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    jar_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __init__(self, **kwargs):
        for k, v in _INSTANCE_DEFAULTS.items():
            if k not in kwargs:
                kwargs[k] = v
        super().__init__(**kwargs)
