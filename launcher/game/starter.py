import os
import re
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional, Callable
from threading import Thread

from launcher.utils.storage import (
    get_versions_dir, get_libraries_dir, get_assets_dir, get_work_dir, get_log_config_path,
)
from launcher.game.version_manager import VersionManager
from launcher.game.libraries_matcher import LibrariesMatcher, get_native_classifier_key
from launcher.game.java_manager import JavaManager
from launcher.api.auth import YggdrasilSession


def split_args(text: str) -> list:
    result = []
    buf = []
    quote = ""
    for ch in text or "":
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
        elif ch in ("'", '"'):
            quote = ch
        elif ch.isspace():
            if buf:
                result.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        result.append("".join(buf))
    return result


class GameStarter:
    def __init__(self):
        self.version_manager = VersionManager()
        self.process: Optional[subprocess.Popen] = None

    def _get_classpath(self, version_id: str, meta) -> str:
        libs = LibrariesMatcher.filter_libraries(meta.libraries)
        cp_parts = []
        seen = set()
        libs_dir = get_libraries_dir()
        for artifact in libs:
            path = artifact.get("path", "")
            if path:
                lib_path = libs_dir / path
                if lib_path.exists() and str(lib_path) not in seen:
                    seen.add(str(lib_path))
                    cp_parts.append(str(lib_path))
        jar_path = get_versions_dir() / version_id / f"{version_id}.jar"
        if jar_path.exists():
            cp_parts.append(str(jar_path))
        return os.pathsep.join(cp_parts)

    def extract_natives(self, meta):
        natives_dir = get_work_dir() / "natives"
        if natives_dir.exists():
            shutil.rmtree(natives_dir)
        natives_dir.mkdir(parents=True, exist_ok=True)
        libs_dir = get_libraries_dir()
        native_extensions = (".dll", ".so", ".dylib")
        for lib in meta.libraries:
            if not LibrariesMatcher.match_library(lib):
                continue
            dl = lib.get("downloads", {})
            classifiers = dl.get("classifiers", {})
            key = get_native_classifier_key(classifiers)
            if not key:
                continue
            artifact = classifiers[key]
            path = artifact.get("path", "")
            if not path:
                continue
            lib_path = libs_dir / path
            if not lib_path.exists():
                continue
            extract = lib.get("extract", {})
            excludes = extract.get("exclude", []) or []
            includes = extract.get("include", []) or []
            try:
                with zipfile.ZipFile(lib_path, "r") as zf:
                    for member in zf.namelist():
                        if not member.endswith(native_extensions):
                            continue
                        if includes and not any(member.startswith(inc) for inc in includes):
                            continue
                        if any(member.startswith(exc) for exc in excludes):
                            continue
                        zf.extract(member, natives_dir)
            except (zipfile.BadZipFile, OSError):
                continue
        return natives_dir

    def _get_jvm_args(self, java_path: str, max_mem: int, min_mem: int, extra_args: str,
                      meta, gdir: str = "", session: YggdrasilSession = None,
                      injector_jar: str = "", injector_url: str = "") -> list:
        args = [
            java_path,
            f"-Xmx{max_mem}M",
            f"-Xms{min_mem}M",
        ]
        if injector_jar and injector_url and session and session.access_token and session.access_token != "0":
            args.insert(1, f"-javaagent:{injector_jar}={injector_url}")
        placeholders = self._build_placeholders(meta, gdir, session)
        jvm_section = meta.arguments.get("jvm", []) if isinstance(meta.arguments, dict) else []
        for arg in jvm_section:
            if not isinstance(arg, str):
                continue
            if arg == "-cp" or arg == "--classpath" or arg == "${classpath}":
                continue
            if arg.startswith("-Djava.library.path=") or arg.startswith("-Dlog4j.configurationFile="):
                continue
            for key, val in placeholders.items():
                arg = arg.replace(key, val)
            if "${" in arg:
                continue
            args.append(arg)
        args.extend(split_args(extra_args))
        return args

    def _build_placeholders(self, meta, gdir: str, session: YggdrasilSession) -> dict:
        auth_uuid = session.uuid.replace("-", "") if session.uuid else ""
        return {
            "${auth_player_name}": session.display_name or session.username,
            "${auth_session}": session.access_token,
            "${auth_access_token}": session.access_token,
            "${auth_uuid}": auth_uuid,
            "${version_name}": meta.id,
            "${game_assets}": str(get_assets_dir()),
            "${assets_root}": str(get_assets_dir()),
            "${assets_index_name}": meta.assets,
            "${game_directory}": gdir,
            "${user_properties}": self._user_properties_arg(session.user_properties),
            "${user_type}": "mojang",
            "${version_type}": meta.type,
            "${natives_directory}": str(get_work_dir() / "natives"),
            "${classpath_separator}": os.pathsep,
            "${library_directory}": str(get_libraries_dir()),
            "${classpath}": self._get_classpath(meta.id, meta),
            "${clientid}": "",
            "${auth_xuid}": "0",
            "${launcher_name}": "Uroboros",
            "${launcher_version}": "1.0",
        }

    def _user_properties_arg(self, user_props) -> str:
        items = []
        if isinstance(user_props, list):
            items = user_props
        elif isinstance(user_props, dict):
            import base64
            items = [
                {"name": str(k), "value": base64.b64encode(str(v).encode("utf-8")).decode("ascii")}
                for k, v in user_props.items()
            ]
        return json.dumps(items, separators=(",", ":"))

    def _get_game_args(self, meta, session: YggdrasilSession, game_dir: str = "", server_address: str = "", server_port: str = "") -> list:
        gdir = game_dir or str(get_work_dir())
        args_dict = self._build_placeholders(meta, gdir, session)

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
            game_args = split_args(ma)

        if server_address and server_port:
            mc_id = meta.inherits_from or meta.id
            if self._mc_version_tuple(mc_id) >= (1, 20, 2):
                game_args.extend(["--quickPlayMultiplayer", f"{server_address}:{server_port}"])
            else:
                game_args.extend(["--server", server_address, "--port", server_port])

        return game_args

    @staticmethod
    def _mc_version_tuple(version_id: str) -> tuple:
        m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", version_id or "")
        if not m:
            return (0, 0, 0)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))

    def _resolve_java(self, java_path: str, meta) -> str:
        if java_path and java_path.strip().lower() != "java":
            return java_path
        required = int(
            meta.java_version.get("majorVersion")
            or meta.java_version.get("major")
            or 0
        ) or 0
        manager = JavaManager()
        found = manager.find_java(required) if required else manager.find_java()
        return found or (java_path if java_path else "java")

    def start(
        self,
        version_id: str,
        session: YggdrasilSession,
        java_path: str = "",
        max_mem: int = 2048,
        min_mem: int = 1024,
        extra_jvm_args: str = "",
        server_address: str = "",
        server_port: str = "",
        output_callback: Optional[Callable[[str], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        game_dir: str = "",
        injector_jar: str = "",
        injector_url: str = "",
    ) -> bool:
        meta = self.version_manager.get_version_meta(version_id)
        if not meta.main_class:
            raise ValueError(f"Version {version_id} has no main class")

        gdir = game_dir or str(get_work_dir())
        Path(gdir).mkdir(parents=True, exist_ok=True)

        java_path = self._resolve_java(java_path, meta)
        classpath = self._get_classpath(version_id, meta)
        if not classpath:
            raise RuntimeError(f"No libraries found for version {version_id}, run Install first")

        self.version_manager.download_missing_natives(meta)
        natives_dir = self.extract_natives(meta)
        jvm_args = self._get_jvm_args(java_path, max_mem, min_mem, extra_jvm_args, meta, gdir, session, injector_jar, injector_url)
        log_cfg = get_log_config_path(version_id)
        if log_cfg.exists():
            jvm_args.append(f"-Dlog4j.configurationFile={log_cfg}")
        game_args = self._get_game_args(meta, session, gdir, server_address, server_port)
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
        except (FileNotFoundError, OSError) as e:
            self.process = None
            raise RuntimeError(f"Failed to start Java ({java_path}): {e}") from e

        if self.process.poll() is not None:
            self.process = None
            return False

        if output_callback:
            def read_output():
                for line in iter(self.process.stdout.readline, ""):
                    output_callback(line.rstrip("\n"))
            Thread(target=read_output, daemon=True).start()

        if on_exit:
            def wait_exit():
                self.process.wait()
                on_exit()
            Thread(target=wait_exit, daemon=True).start()

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
