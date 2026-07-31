import time
import threading
from typing import Callable, Optional


class CancelledError(Exception):
    pass


class FileProgress:
    def __init__(self, callback, phase: str, filename: str, total: int = 0,
                 files_done: Optional[int] = None, files_total: Optional[int] = None):
        self.callback = callback
        self.phase = phase
        self.filename = filename
        self.total = total
        self.files_done = files_done
        self.files_total = files_total
        self.current = 0
        self.start = time.monotonic()

    def update(self, current: int, total: Optional[int] = None):
        self.current = current
        if total is not None:
            self.total = total
        self._emit()

    def done(self):
        self.current = self.total
        self._emit()

    def _emit(self):
        if not self.callback:
            return
        elapsed = time.monotonic() - self.start
        speed = self.current / elapsed if elapsed > 0 else 0.0
        self.callback({
            "phase": self.phase,
            "file": self.filename,
            "current": self.current,
            "total": self.total,
            "speed": speed,
            "files_done": self.files_done,
            "files_total": self.files_total,
        })


class ParallelProgress:
    def __init__(self, callback, phase: str, files_total: int):
        self.callback = callback
        self.phase = phase
        self.files_total = files_total
        self.files_done = 0
        self.bytes = 0
        self.start = time.monotonic()
        self.current_file = ""
        self._lock = threading.Lock()

    def start_file(self, filename: str):
        with self._lock:
            self.current_file = filename
            files_done = self.files_done
        self._emit(filename, files_done)

    def tick(self, filename: str, n: int):
        with self._lock:
            self.bytes += n
            self.current_file = filename
            files_done = self.files_done
        self._emit(filename, files_done)

    def finish(self, filename: str):
        with self._lock:
            self.files_done += 1
            files_done = self.files_done
        self._emit(filename, files_done)

    def _emit(self, filename: str, files_done: int):
        if not self.callback:
            return
        elapsed = time.monotonic() - self.start
        speed = self.bytes / elapsed if elapsed > 0 else 0.0
        self.callback({
            "phase": self.phase,
            "file": filename,
            "current": self.bytes,
            "total": 0,
            "speed": speed,
            "files_done": files_done,
            "files_total": self.files_total,
        })
