import os
import subprocess
import signal
import threading
from pathlib import Path
from typing import Optional, Callable, List

from server.mc.auth_plugin import create_server_auth_plugin, ServerAuthPlugin
from server.mc.pidfile import write_pid_for, clear_pid_for


class ServerManager:
    def __init__(self, config, auth_plugin: Optional[ServerAuthPlugin] = None):
        self.config = config
        if auth_plugin:
            self.auth_plugin = auth_plugin
        else:
            self.auth_plugin = create_server_auth_plugin(
                config.auth_plugin,
                injector_filename=config.injector_filename,
            )
        self.process: Optional[subprocess.Popen] = None
        self.last_error: Optional[str] = None
        self._lock = threading.RLock()
        self._auto_restart = config.auto_restart
        self._stop_requested = False
        self._stopping = False
        self._starting = False
        self._output_history: list[str] = []
        self._output_callbacks: list[Callable[[str], None]] = []

    def on_output(self, callback: Callable[[str], None]):
        self._output_callbacks.append(callback)

    def _emit_output(self, line: str):
        self._output_history.append(line)
        if len(self._output_history) > 1000:
            self._output_history.pop(0)
        for cb in self._output_callbacks:
            try:
                cb(line)
            except Exception:
                pass

    def get_output(self, tail: int = 100) -> list[str]:
        return self._output_history[-tail:]

    def _preflight_check(self) -> Optional[str]:
        if not self.config.server_filename:
            return "Server JAR filename is not configured"
        if not self.config.java_executable_path:
            return "Java executable path is not configured"
        server_dir = Path(self.config.server_dir) if self.config.server_dir else Path.cwd()
        jar_path = server_dir / self.config.server_filename
        if not jar_path.exists():
            return f"Server JAR not found at {jar_path}"
        return None

    def _build_command(self) -> List[str]:
        server_dir = Path(self.config.server_dir) if self.config.server_dir else Path.cwd()
        server_path = server_dir / self.config.server_filename

        cmd = [
            self.config.java_executable_path,
            f"-Xmx{self.config.max_memory}M",
            f"-Xms{self.config.min_memory}M",
        ]

        if self.config.additional_flags:
            cmd.extend(self.config.additional_flags.split())

        cmd = self.auth_plugin.apply(cmd, self.config.api_url, self.config.server_dir)
        cmd.extend(["-jar", str(server_path)])

        if self.config.arguments:
            cmd.extend(self.config.arguments.split())

        return cmd

    def _accept_eula(self):
        if not getattr(self.config, "auto_accept_eula", False):
            return
        server_dir = Path(self.config.server_dir).resolve() if self.config.server_dir else Path.cwd().resolve()
        server_dir.mkdir(parents=True, exist_ok=True)
        eula_path = server_dir / "eula.txt"
        if not eula_path.exists() or "eula=false" in eula_path.read_text(encoding="utf-8", errors="replace"):
            eula_path.write_text("eula=true\n", encoding="utf-8")

    def start(self, output_callback: Optional[Callable[[str], None]] = None) -> bool:
        with self._lock:
            if self.is_running():
                return False

            self.last_error = None
            self._stop_requested = False
            self._stopping = False
            self.last_error = self._preflight_check()
            if self.last_error:
                return False

            self._accept_eula()
            server_dir = self.config.server_dir or str(Path.cwd())
            Path(server_dir).mkdir(parents=True, exist_ok=True)

            cmd = self._build_command()

            if output_callback:
                self.on_output(output_callback)

            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=server_dir,
                    bufsize=1,
                    universal_newlines=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except FileNotFoundError:
                self.process = None
                self.last_error = f"Java executable not found: {self.config.java_executable_path}"
                return False
            except Exception as e:
                self.process = None
                self.last_error = str(e)
                return False

            write_pid_for(self.config.id, self.process.pid)
            self._starting = True

            def read_output():
                try:
                    for line in iter(self.process.stdout.readline, ""):
                        line = line.rstrip("\n")
                        self._emit_output(line)
                        if self._starting and ("Done (" in line or "For help, type" in line):
                            with self._lock:
                                self._starting = False
                except ValueError:
                    pass
                if self._auto_restart:
                    self._handle_crash()

            threading.Thread(target=read_output, daemon=True).start()
            return True

    def _handle_crash(self):
        exit_code = None
        with self._lock:
            if self.process and self.process.poll() is not None:
                exit_code = self.process.returncode
                clear_pid_for(self.config.id)
                self.process = None
                self._starting = False
        if self._auto_restart and not self._stop_requested and not self._stopping and exit_code is not None and exit_code != 0:
            import time
            time.sleep(2)
            self.start()

    def _send_stdin(self, command: str):
        with self._lock:
            proc = self.process
        if not proc or not proc.stdin or proc.poll() is not None:
            return
        try:
            proc.stdin.write(command + "\n")
            proc.stdin.flush()
        except (ValueError, OSError, BrokenPipeError):
            pass

    def _terminate(self, proc):
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                os.kill(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    def _kill(self, proc):
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.kill(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    def stop(self, timeout: float = 30) -> bool:
        self._stop_requested = True
        self.last_error = None
        with self._lock:
            self._stopping = True
            proc = self.process
            if not proc or proc.poll() is not None:
                clear_pid_for(self.config.id)
                self.process = None
                self._stopping = False
                return True
        try:
            self._send_stdin("stop")
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._kill(proc)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            with self._lock:
                if self.process is proc:
                    self.process = None
                self._stopping = False
                self._starting = False
            clear_pid_for(self.config.id)
        return True

    def request_stop(self, timeout: float = 30) -> bool:
        with self._lock:
            if not self.is_running() or self._stopping:
                return False
        threading.Thread(target=self.stop, kwargs={"timeout": timeout}, daemon=True).start()
        return True

    def is_stopping(self) -> bool:
        with self._lock:
            return self._stopping

    def is_starting(self) -> bool:
        with self._lock:
            return self._starting

    def request_restart(self, timeout: float = 30) -> bool:
        with self._lock:
            if not self.is_running() or self._stopping:
                return False

        def _worker():
            self.stop(timeout=timeout)
            self.start()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def reload(self) -> bool:
        if self.is_stopping() or not self.is_running():
            return False
        self._send_stdin("reload")
        return True

    def restart(self, output_callback: Optional[Callable[[str], None]] = None) -> bool:
        self.stop()
        return self.start(output_callback)

    def is_running(self) -> bool:
        if self.process and self.process.poll() is None:
            return True
        if self.process and self.process.poll() is not None:
            clear_pid_for(self.config.id)
            self.process = None
        return False

    def send_command(self, command: str):
        self._send_stdin(command)
