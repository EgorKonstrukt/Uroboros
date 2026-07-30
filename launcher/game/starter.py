import os
import subprocess
import json
import shlex
from pathlib import Path
from typing import Optional, Callable
from threading import Thread

from launcher.utils.storage import get_versions_dir, get_libraries_dir, get_assets_dir, get_work_dir
from launcher.game.version_manager import VersionManager
from launcher.game.libraries_matcher import LibrariesMatcher
from launcher.api.auth import YggdrasilSession


class GameStarter:
    def __init__(self):
        self.version_manager = VersionManager()
        self.process: Optional[subprocess.Popen] = None

    def _get_classpath(self, version_id: str, meta) -> str:
        libs = LibrariesMatcher.filter_libraries(meta.libraries)
        cp_parts = []
        libs_dir = get_libraries_dir()
        for artifact in libs:
            path = artifact.get("path", "")
            if path:
                lib_path = libs_dir / path
                if lib_path.exists():
                    cp_parts.append(str(lib_path))
        vdir = get_versions_dir() / version_id
        jar_path = vdir / f"{version_id}.jar"
        if jar_path.exists():
            cp_parts.append(str(jar_path))
        return os.pathsep.join(cp_parts)

    def _get_jvm_args(self, java_path: str, max_mem: int, min_mem: int, extra_args: str) -> list:
        args = [
            java_path,
            f"-Xmx{max_mem}M",
            f"-Xms{min_mem}M",
        ]
        args.extend(shlex.split(extra_args))
        return args

    def _get_game_args(self, meta, session: YggdrasilSession, game_dir: str = "", server_address: str = "", server_port: str = "") -> list:
        gdir = game_dir or str(get_work_dir())
        auth_uuid = session.uuid.replace("-", "")
        args_dict = {
            "${auth_player_name}": session.display_name or session.username,
            "${auth_session}": session.access_token,
            "${auth_access_token}": session.access_token,
            "${auth_uuid}": auth_uuid,
            "${version_name}": meta.id,
            "${game_assets}": str(get_assets_dir()),
            "${assets_root}": str(get_assets_dir()),
            "${game_directory}": gdir,
            "${user_properties}": json.dumps(session.user_properties or {}),
            "${user_type}": "mojang",
            "${version_type}": meta.type,
            "${natives_directory}": str(get_work_dir() / "natives"),
            "${classpath_separator}": os.pathsep,
            "${library_directory}": str(get_libraries_dir()),
            "${classpath}": self._get_classpath(meta.id, meta),
        }

        game_args = []
        args = meta.arguments if isinstance(meta.arguments, dict) else {}

        game_section = args.get("game", [])
        for arg in game_section:
            if isinstance(arg, str):
                for key, val in args_dict.items():
                    arg = arg.replace(key, val)
                game_args.append(arg)

        if not game_section:
            ma = meta.minecraft_arguments or ""
            for key, val in args_dict.items():
                ma = ma.replace(key, val)
            game_args = shlex.split(ma)

        if server_address and server_port:
            game_args.extend(["--server", server_address, "--port", server_port])

        return game_args

    def start(
        self,
        version_id: str,
        session: YggdrasilSession,
        java_path: str = "java",
        max_mem: int = 2048,
        min_mem: int = 1024,
        extra_jvm_args: str = "",
        server_address: str = "",
        server_port: str = "",
        output_callback: Optional[Callable[[str], None]] = None,
        game_dir: str = "",
    ) -> bool:
        meta = self.version_manager.get_version_meta(version_id)
        if not meta.main_class:
            raise ValueError(f"Version {version_id} has no main class")

        gdir = game_dir or str(get_work_dir())
        jvm_args = self._get_jvm_args(java_path, max_mem, min_mem, extra_jvm_args)
        game_args = self._get_game_args(meta, session, gdir, server_address, server_port)
        natives_dir = get_work_dir() / "natives"
        natives_dir.mkdir(parents=True, exist_ok=True)
        classpath = self._get_classpath(version_id, meta)
        cmd = jvm_args + [
            "-Djava.library.path=" + str(natives_dir),
            "-cp", classpath,
            meta.main_class,
        ] + game_args

        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=gdir, bufsize=1, universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError:
            self.process = None
            return False

        if self.process.poll() is not None:
            self.process = None
            return False

        if output_callback:
            def read_output():
                for line in iter(self.process.stdout.readline, ""):
                    output_callback(line.rstrip("\n"))
            Thread(target=read_output, daemon=True).start()

        return True

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None
