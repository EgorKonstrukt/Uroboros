import os
import signal
import time
from pathlib import Path
from typing import Optional

PID_DIR = Path.home() / ".yamcl" / "server" / "pids"


def _ensure():
    PID_DIR.mkdir(parents=True, exist_ok=True)


def _pid_file(instance_id: str) -> Path:
    safe = instance_id.replace("..", "").replace("/", "_").replace("\\", "_")
    return PID_DIR / f"{safe}.pid"


def write_pid_for(instance_id: str, pid: int):
    _ensure()
    _pid_file(instance_id).write_text(str(pid))


def read_pid_for(instance_id: str) -> Optional[int]:
    pf = _pid_file(instance_id)
    if pf.exists():
        try:
            return int(pf.read_text().strip())
        except (ValueError, OSError):
            return None
    return None


def clear_pid_for(instance_id: str):
    pf = _pid_file(instance_id)
    try:
        pf.unlink(missing_ok=True)
    except OSError:
        pass


def is_running(instance_id: str) -> bool:
    pid = read_pid_for(instance_id)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        clear_pid_for(instance_id)
        return False


def stop_process(instance_id: str, timeout: float = 30) -> bool:
    pid = read_pid_for(instance_id)
    if pid is None:
        return False
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                clear_pid_for(instance_id)
                return True
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGKILL)
        clear_pid_for(instance_id)
        return True
    except OSError:
        clear_pid_for(instance_id)
        return False
